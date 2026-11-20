"""The Playwright executor: one Chromium page shared by every feature of a run.

Features run on the same page, one after the other, like a person going through the journey:
the login of the first feature carries over to the next ones.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import CDPSession, FrameLocator, Locator, Page, Playwright, Response, Route, expect, sync_playwright

from horizon_analyzer.loader import Context, ScenarioError
from horizon_analyzer.runner import StepFailure
from horizon_analyzer.schema import (
    ChooseStep,
    ClickStep,
    DragStep,
    Expectation,
    ExpectStep,
    Feature,
    FillStep,
    GotoStep,
    HoverStep,
    PressStep,
    ReloadStep,
    ResponseMatch,
    ScreenshotStep,
    SelectStep,
    Step,
    StoreStep,
    Target,
    UploadStep,
    WaitStep,
)

# Headless Chromium hides WebGPU unless asked; these flags expose a software (SwiftShader)
# adapter. Headed runs use the machine's real GPU and need no flag.
HEADLESS_WEBGPU_ARGS = ["--enable-unsafe-webgpu", "--enable-features=Vulkan"]

_WEBGPU_PROBE = """async () => {
  if (!navigator.gpu) return null;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    if (!adapter) return null;
    const info = adapter.info || {};
    return [info.vendor, info.architecture].filter(Boolean).join(' ') || 'unknown adapter';
  } catch (e) { return null; }
}"""

_ERROR_LINES = 8
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class BrowserOptions:
    headless: bool = False
    slow_mo: int = 0
    viewport: tuple[int, int] = (1600, 900)
    trace: bool = True
    asset_cache: Path | None = None  # folder for AssetCache; None downloads everything each run


# SvelteKit serves the front's code and the Bevy wasm (9 MB for the editor alone) under
# /_app/immutable/, with a content hash in each file name: a URL there never changes content, and
# a new deploy ships new URLs. Each run starts from an empty browser, so without this cache every
# run downloads all of it again, which takes minutes on a slow connection.
IMMUTABLE_ASSETS = re.compile(r"^https?://[^/]+/_app/immutable/")
_CACHE_DAYS = 14
_DROPPED_HEADERS = {"content-length", "content-encoding", "transfer-encoding"}  # the body is stored decoded


class AssetCache:
    """Serves /_app/immutable/ files from disk, downloading each one once."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.hits = 0
        self.downloads = 0
        folder.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - _CACHE_DAYS * 86400
        for path in folder.iterdir():  # files of past deploys nobody asked for lately
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.folder / key, self.folder / f"{key}.json"

    def handle(self, route: Route) -> None:
        request = route.request
        if request.method != "GET":
            route.continue_()
            return
        body_path, meta_path = self._paths(request.url)
        if body_path.is_file() and meta_path.is_file():
            body_path.touch()
            self.hits += 1
            route.fulfill(status=200, headers=json.loads(meta_path.read_text("utf-8")), body=body_path.read_bytes())
            return
        try:
            # No time limit: the editor's wasm is 39 MB decoded and the default 30 s cut it off on a
            # slow connection, so it was never cached. The step waiting on it has its own timeout.
            response = route.fetch(timeout=0)
            body = response.body()
        except PlaywrightError:
            route.continue_()  # let the browser hit the error itself, so the step reports it
            return
        headers = {name: value for name, value in response.headers.items() if name.lower() not in _DROPPED_HEADERS}
        if response.status == 200:
            partial = body_path.with_suffix(".part")
            partial.write_bytes(body)
            partial.replace(body_path)
            meta_path.write_text(json.dumps(headers), "utf-8")
            self.downloads += 1
        route.fulfill(status=response.status, headers=headers, body=body)


# A frame counts as rendered when at least this share of its pixels differs from its most common
# colour (the clear colour). A 1 m cube seen from 6 m covers about 2 % of the game view.
RENDERED_MIN_FRACTION = 0.005


def _thumbnail(png: bytes) -> Image.Image:
    """The image without its outer 3 %, shrunk to at most 320 px.

    An element screenshot is clipped on fractional coordinates and can catch a row of the
    neighbouring pixels: the inset keeps them out.
    """
    image = Image.open(io.BytesIO(png)).convert("RGB")
    inset_x, inset_y = max(2, image.width * 3 // 100), max(2, image.height * 3 // 100)
    if image.width > 2 * inset_x and image.height > 2 * inset_y:
        image = image.crop((inset_x, inset_y, image.width - inset_x, image.height - inset_y))
    image.thumbnail((320, 320))
    return image


def dominant_color(png: bytes) -> tuple[int, int, int]:
    """The image's most common colour, e.g. the clear colour behind a 3D scene."""
    image = _thumbnail(png)
    colors = image.getcolors(maxcolors=image.width * image.height) or [(0, (0, 0, 0))]
    return max(colors)[1]


def drawn_fraction(png: bytes) -> float:
    """Share of the image's pixels that are not its most common colour (0 = one flat colour)."""
    image = _thumbnail(png)
    colors = image.getcolors(maxcolors=image.width * image.height)
    if not colors:
        return 0.0
    background = max(count for count, _ in colors)
    return 1 - background / (image.width * image.height)


# Two captures of a scene count as different (something moves) when at least this share of their
# pixels changed noticeably. A still WebGPU scene redraws identically (0 %); a 1 m cube turning
# 2° a frame, seen from 6 m, changes about 0.15 % of the game view in a second.
ANIMATED_MIN_FRACTION = 0.0005
_PIXEL_CHANGE = 24  # luminance difference out of 255 that counts as a change: ignores dithering noise


def changed_fraction(before: bytes, after: bytes) -> float:
    """Share of pixels that changed noticeably between two captures of the same element."""
    first = Image.open(io.BytesIO(before)).convert("L")
    second = Image.open(io.BytesIO(after)).convert("L")
    if first.size != second.size:
        return 1.0
    changed = ImageChops.difference(first, second).point(lambda value: 255 if value > _PIXEL_CHANGE else 0)
    return changed.histogram()[255] / (first.width * first.height)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """``*`` and ``**`` match any run of characters; everything else is literal."""
    return re.compile("^" + ".*".join(re.escape(part) for part in re.split(r"\*+", pattern)) + "$")


def status_matches(expected: str | int, actual: int) -> bool:
    if isinstance(expected, int):
        return expected == actual
    if expected.endswith("xx"):
        return str(actual).startswith(expected[0])
    return int(expected) == actual


def _short(error: Exception) -> str:
    """Playwright errors carry a long call log; the first lines say what went wrong."""
    lines = [line for line in str(error).splitlines() if line.strip()]
    return "\n".join(lines[:_ERROR_LINES])


class PlaywrightExecutor:
    """Runs steps in a Chromium page. Use as a context manager."""

    def __init__(self, context: Context, out_dir: Path, options: BrowserOptions) -> None:
        self.context = context
        self.out_dir = out_dir
        self.options = options
        self._playwright: Playwright | None = None
        self._page: Page | None = None
        self._console: list[str] = []
        self._feature_start = 0
        self._mark = 0
        self._webgpu: str | None | bool = False  # False = not probed yet
        self._cdp: CDPSession | None = None
        self._window_id: int | None = None
        self.window_restores = 0
        self._stray: list[Page] = []
        self.closed_tabs: list[str] = []
        self.asset_cache: AssetCache | None = None
        self.browser_description = ""

    # ------------------------------------------------------------------ lifecycle

    def __enter__(self) -> PlaywrightExecutor:
        self._playwright = sync_playwright().start()
        args = HEADLESS_WEBGPU_ARGS if self.options.headless else []
        browser = self._playwright.chromium.launch(headless=self.options.headless, slow_mo=self.options.slow_mo, args=args)
        width, height = self.options.viewport
        locale = self.context.suite.locale
        browser_context = browser.new_context(
            viewport={"width": width, "height": height},
            accept_downloads=False,
            **({"locale": locale} if locale else {}),
        )
        if self.options.trace:
            browser_context.tracing.start(screenshots=True, snapshots=True)
        if self.options.asset_cache is not None:
            self.asset_cache = AssetCache(self.options.asset_cache)
            browser_context.route(IMMUTABLE_ASSETS, self.asset_cache.handle)
        page = browser_context.new_page()
        page.set_default_timeout(self.context.suite.timeout * 1000)
        page.on("console", lambda message: self._console.append(f"[{message.type}] {message.text}"))
        page.on("pageerror", lambda error: self._console.append(f"[pageerror] {error}"))
        # `expect: console` looks at messages since the page's last navigation, whatever caused
        # it (goto, reload, or the app's own routing): the editor can boot Bevy and log its
        # adapter while the previous feature is still finishing.
        page.on("framenavigated", lambda frame: self._mark_navigation() if frame == page.main_frame else None)
        dialogs = self.context.suite.dialogs
        page.on("dialog", lambda dialog: dialog.accept() if dialogs == "accept" else dialog.dismiss())
        self._page = page
        # Registered after the main page exists: every page seen here is a tab the site opened.
        browser_context.on("page", lambda tab: self._stray.append(tab))
        if not self.options.headless:
            self._cdp = browser_context.new_cdp_session(page)
            self._window_id = self._cdp.send("Browser.getWindowForTarget")["windowId"]
        mode = "headless" if self.options.headless else "headed"
        self.browser_description = f"Chromium {browser.version} ({mode})"
        return self

    def __exit__(self, *exc: object) -> None:
        if self._playwright is None:
            return
        try:
            if self._page is not None:
                browser_context = self._page.context
                if self.options.trace:
                    browser_context.tracing.stop(path=self.out_dir / "trace.zip")
                browser_context.browser.close()
        finally:
            self._playwright.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None, "use PlaywrightExecutor as a context manager"
        return self._page

    # ------------------------------------------------------------------ Executor protocol

    def start_feature(self, feature: Feature) -> None:
        self._feature_start = len(self._console)

    def _mark_navigation(self) -> None:
        self._mark = len(self._console)

    def console_errors(self) -> list[str]:
        ignored = [re.compile(pattern) for pattern in self.context.suite.ignore_console]
        return [
            line
            for line in self._console[self._feature_start :]
            if line.startswith(("[error]", "[pageerror]")) and not any(pattern.search(line) for pattern in ignored)
        ]

    def webgpu_available(self) -> bool:
        if self._webgpu is False:
            try:
                self._webgpu = self.page.evaluate(_WEBGPU_PROBE)
            except PlaywrightError:
                self._webgpu = None
            if self._webgpu:
                self.browser_description += f", WebGPU: {self._webgpu}"
        return bool(self._webgpu)

    def capture_failure(self, feature: Feature) -> str | None:
        path = self.out_dir / "failures" / f"{feature.id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # A failed network check fires the moment the response arrives: give the page a
            # moment to show its reaction (an error message) before the capture.
            self.page.wait_for_timeout(500)
            self.page.screenshot(path=path)
        except PlaywrightError:
            return None
        return path.relative_to(self.out_dir).as_posix()

    def close_stray_tabs(self) -> None:
        """Close any tab the site opened (a target=_blank link) and put the test page back in front.

        Every step runs on one page. A click that lands on a link such as Stripe's legal footer
        opens a new tab over it: the run looks stopped on that tab while the steps keep waiting
        on the hidden page.
        """
        while self._stray:
            tab = self._stray.pop()
            try:
                url = tab.url
                tab.close()
                self.page.bring_to_front()
            except PlaywrightError:
                continue  # already closed by the site itself
            self.closed_tabs.append(url)
            print(f"  ! onglet ouvert par le site pendant le run, refermé : {url}")

    def keep_window_open(self) -> None:
        """Restore the browser window if someone minimized it during the run.

        A minimized Chromium window drops from ~165 to ~2 animation frames a second while the
        page still reports itself visible: Bevy nearly stops rendering, the game takes ages to
        load and steps time out. A window covered by others or moved off-screen keeps rendering
        (Playwright launches Chromium with the backgrounding flags off), so only this case needs
        handling.
        """
        if self._cdp is None or self._window_id is None:
            return
        try:
            bounds = self._cdp.send("Browser.getWindowBounds", {"windowId": self._window_id})["bounds"]
            if bounds.get("windowState") == "minimized":
                self._cdp.send("Browser.setWindowBounds", {"windowId": self._window_id, "bounds": {"windowState": "normal"}})
                self.window_restores += 1
                print("  ! fenêtre du navigateur réduite pendant le run : restaurée (le rendu 3D était quasi gelé)")
        except PlaywrightError:
            pass  # the window is closing; the step itself will report what went wrong

    def run_step(self, step: Step, feature: Feature) -> list[str]:
        self.close_stray_tabs()
        self.keep_window_open()
        try:
            return self._dispatch(step, feature)
        except (StepFailure, ScenarioError):
            raise
        except AssertionError as error:
            raise StepFailure(_short(error)) from None
        except PlaywrightError as error:
            raise StepFailure(_short(error)) from None

    # ------------------------------------------------------------------ steps

    def _dispatch(self, step: Step, feature: Feature) -> list[str]:
        page, render = self.page, self.context.render
        match step:
            case GotoStep():
                with self._response(step.expect_response):
                    page.goto(render(step.goto), wait_until="load")
            case ClickStep():
                position = {"x": step.position.x, "y": step.position.y} if step.position else None
                with self._response(step.expect_response):
                    self.locate(step.click).click(
                        button=step.button, position=position, force=step.force, timeout=self._ms(step.timeout)
                    )
            case SelectStep():
                locator = self.locate(step.select)
                timeout = self._ms(step.timeout)
                if not _is_selected(locator, timeout):
                    locator.click(timeout=timeout)
                expect(locator).to_have_attribute("aria-selected", "true", timeout=timeout)
            case HoverStep():
                self.locate(step.hover).hover(timeout=self._ms(step.timeout))
            case FillStep():
                self.locate(step.fill).fill(render(step.value), timeout=self._ms(step.timeout))
            case PressStep():
                if step.target is not None:
                    self.locate(step.target).press(step.press)
                else:
                    page.keyboard.press(step.press)
            case UploadStep():
                files = [self.context.resolve_file(path) for path in step.files]
                self.locate(step.upload).set_input_files(files)
            case DragStep():
                position = {"x": step.to_position.x, "y": step.to_position.y} if step.to_position else None
                source, target, timeout = self.locate(step.drag), self.locate(step.to), self._ms(step.timeout)
                if step.steps is None:
                    source.drag_to(target, target_position=position, timeout=timeout)
                else:
                    self._mouse_drag(source, target, position, step.steps, timeout)
            case ChooseStep():
                self.locate(step.choose).select_option(render(step.option), timeout=self._ms(step.timeout))
            case WaitStep():
                page.wait_for_timeout(step.wait * 1000)
            case ReloadStep():
                page.reload(wait_until="load")
            case ScreenshotStep():
                path = self.out_dir / "screenshots" / f"{feature.id}-{step.screenshot}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                if step.of is not None:
                    path.write_bytes(self._capture(self.locate(step.of), self._ms(None)))
                else:
                    page.screenshot(path=path)
                return [path.relative_to(self.out_dir).as_posix()]
            case StoreStep():
                self.context.variables[step.store] = self._stored_value(step)
            case ExpectStep():
                self._check(step.expect)
        return []

    def _mouse_drag(self, source: Locator, target: Locator, position: dict[str, float] | None, steps: int, timeout: float) -> None:
        """Press at the centre of ``source``, move to ``target`` in ``steps`` moves, release."""
        mouse = self.page.mouse
        start = _box(source, timeout)
        end = _box(target, timeout)
        to_x, to_y = (end["x"] + position["x"], end["y"] + position["y"]) if position else (end["x"] + end["width"] / 2, end["y"] + end["height"] / 2)
        mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
        mouse.down()
        mouse.move(to_x, to_y, steps=steps)
        mouse.up()

    def _stored_value(self, step: StoreStep) -> str:
        if step.text_of is not None:
            return self.locate(step.text_of).inner_text().strip()
        if step.js is not None:
            value = self.page.evaluate(self.context.render(step.js))
            if value is None:
                raise StepFailure(f"store {step.store}: the expression returned nothing")
            return str(value)
        assert step.url_pattern is not None
        match = re.search(self.context.render(step.url_pattern), self.page.url)
        if match is None:
            raise StepFailure(f"url {self.page.url} does not match {step.url_pattern!r}")
        return match.group(1)

    def _response(self, wanted: ResponseMatch | None) -> Any:
        """Wrap an action so it must trigger a matching response with the expected status."""
        if wanted is None:
            return nullcontext()
        return _ExpectedResponse(self.page, self.context.render(wanted.url), wanted)

    # ------------------------------------------------------------------ targets

    def locate(self, target: Target, root: Page | Locator | FrameLocator | None = None) -> Locator:
        """Turn a scenario target into a Playwright locator."""
        render = self.context.render
        scope: Page | Locator | FrameLocator = root or self.page
        if target.frame is not None:
            scope = scope.frame_locator(render(target.frame))
        if target.within is not None:
            scope = self.locate(target.within, scope)
        if target.testid is not None:
            locator = scope.get_by_test_id(render(target.testid))
        elif target.role is not None:
            name = render(target.name) if target.name is not None else None
            locator = scope.get_by_role(target.role, name=name, exact=target.exact)  # type: ignore[arg-type]
        elif target.label is not None:
            locator = scope.get_by_label(render(target.label), exact=target.exact)
        elif target.text is not None:
            locator = scope.get_by_text(render(target.text), exact=target.exact)
        elif target.placeholder is not None:
            locator = scope.get_by_placeholder(render(target.placeholder), exact=target.exact)
        elif target.title is not None:
            locator = scope.get_by_title(render(target.title), exact=target.exact)
        elif target.id is not None:
            locator = scope.locator(f"[id={_css_string(render(target.id))}]")
        else:
            assert target.css is not None
            locator = scope.locator(render(target.css))
        if target.has_text is not None or target.has is not None:
            locator = locator.filter(
                has_text=render(target.has_text) if target.has_text is not None else None,
                has=self.locate(target.has) if target.has is not None else None,
            )
        if target.nth == "first":
            locator = locator.first
        elif target.nth == "last":
            locator = locator.last
        elif isinstance(target.nth, int):
            locator = locator.nth(target.nth)
        return locator

    # ------------------------------------------------------------------ expectations

    def _check(self, check: Expectation) -> None:
        timeout = self._ms(check.timeout)
        render = self.context.render
        if check.target is not None:
            locator = self.locate(check.target)
            if check.count is not None:
                expect(locator).to_have_count(check.count, timeout=timeout)
            if check.visible is True:
                expect(locator).to_be_visible(timeout=timeout)
            elif check.visible is False:
                expect(locator).to_be_hidden(timeout=timeout)
            if check.text is not None:
                expect(locator).to_contain_text(render(check.text), timeout=timeout)
            if check.value is not None:
                expect(locator).to_have_value(render(check.value), timeout=timeout)
            if check.number is not None:
                self._wait_number(locator, float(render(str(check.number))), check.tolerance, timeout)
            if check.enabled is True:
                expect(locator).to_be_enabled(timeout=timeout)
            elif check.enabled is False:
                expect(locator).to_be_disabled(timeout=timeout)
            if check.checked is not None:
                expect(locator).to_be_checked(checked=check.checked, timeout=timeout)
            if check.rendered is not None:
                self._wait_rendered(locator, check.rendered, timeout)
            if check.animated is not None:
                self._wait_animated(locator, check.animated, timeout)
            if check.dominant_color is not None:
                color = render(check.dominant_color)
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                    raise ScenarioError(f"dominant_color: {color!r} is not a #RRGGBB colour")
                self._wait_dominant_color(locator, color, check.color_tolerance, timeout)
        if check.url is not None:
            expect(self.page).to_have_url(glob_to_regex(render(check.url)), timeout=timeout)
        if check.title is not None:
            expect(self.page).to_have_title(re.compile(re.escape(render(check.title))), timeout=timeout)
        if check.js is not None:
            self.page.wait_for_function(render(check.js), timeout=timeout)
        if check.console is not None:
            self._wait_console(re.compile(render(check.console)), timeout)
        if check.no_console is not None:
            pattern = re.compile(render(check.no_console))
            hits = [line for line in self._console[self._feature_start :] if pattern.search(line)]
            if hits:
                first = " ".join(hits[0].split())[:300]
                raise StepFailure(f"console shows {pattern.pattern!r} ({len(hits)}x): {first}\n" + "\n".join(hit[:300] for hit in hits[1:3]))

    def _wait_number(self, locator: Locator, wanted: float, tolerance: float, timeout_ms: float) -> None:
        """Poll until the element's value (input) or text, read as a number, is ``wanted`` ± ``tolerance``."""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            is_input = locator.evaluate("e => e instanceof HTMLInputElement || e instanceof HTMLTextAreaElement", timeout=timeout_ms)
            raw = locator.input_value(timeout=timeout_ms) if is_input else locator.inner_text(timeout=timeout_ms)
            match = _NUMBER.search(raw.replace(" ", "").replace("\xa0", "").replace(",", "."))
            if match and abs(float(match.group()) - wanted) <= tolerance:
                return
            if time.monotonic() > deadline:
                raise StepFailure(f"expected the number {wanted:g} (± {tolerance:g}), found {raw!r}")
            self.page.wait_for_timeout(250)

    def _wait_rendered(self, locator: Locator, wanted: bool, timeout_ms: float) -> None:
        """Poll screenshots of ``locator`` until it draws something (or stays blank, if ``wanted`` is false)."""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            coverage = drawn_fraction(self._capture(locator, timeout_ms))
            if (coverage >= RENDERED_MIN_FRACTION) == wanted:
                return
            if time.monotonic() > deadline:
                state = "is blank" if wanted else "draws something"
                raise StepFailure(
                    f"element {state}: {coverage:.2%} of its pixels differ from the background "
                    f"(threshold {RENDERED_MIN_FRACTION:.1%})"
                )
            self.close_stray_tabs()
            self.keep_window_open()
            self.page.wait_for_timeout(500)

    def _capture(self, locator: Locator, timeout_ms: float) -> bytes:
        """A PNG of the element, cut out of a screenshot of the whole viewport.

        Playwright's element screenshot makes a headed Chromium window flash: for one or two
        frames it shows only that element, top-left, on a grey background (seen in a screen
        recording of a run, reproduced with a screencast: 2 odd frames in 10 captures). A
        screenshot of the whole viewport leaves the window alone (0 in 10).
        """
        box = _box(locator, timeout_ms)
        shot = Image.open(io.BytesIO(self.page.screenshot(timeout=timeout_ms)))
        viewport = self.page.viewport_size
        scale = shot.width / viewport["width"] if viewport else 1.0
        left, top = max(0, round(box["x"] * scale)), max(0, round(box["y"] * scale))
        right = min(shot.width, round((box["x"] + box["width"]) * scale))
        bottom = min(shot.height, round((box["y"] + box["height"]) * scale))
        if right <= left or bottom <= top:
            raise StepFailure(f"{locator} is outside the visible page")
        buffer = io.BytesIO()
        shot.crop((left, top, right, bottom)).save(buffer, format="PNG")
        return buffer.getvalue()

    def _wait_animated(self, locator: Locator, wanted: bool, timeout_ms: float) -> None:
        """Compare captures 500 ms apart until the element moves (or holds still, if ``wanted`` is false)."""
        deadline = time.monotonic() + timeout_ms / 1000
        before = self._capture(locator, timeout_ms)
        while True:
            self.page.wait_for_timeout(500)
            after = self._capture(locator, timeout_ms)
            change = changed_fraction(before, after)
            if (change >= ANIMATED_MIN_FRACTION) == wanted:
                return
            if time.monotonic() > deadline:
                state = "holds still" if wanted else "keeps moving"
                raise StepFailure(
                    f"element {state}: {change:.3%} of its pixels changed in 500 ms "
                    f"(threshold {ANIMATED_MIN_FRACTION:.2%})"
                )
            before = after
            self.close_stray_tabs()
            self.keep_window_open()

    def _wait_dominant_color(self, locator: Locator, wanted: str, tolerance: int, timeout_ms: float) -> None:
        """Poll until the element's most common colour is ``wanted`` (#RRGGBB) ± ``tolerance`` per channel."""
        target = tuple(int(wanted[i : i + 2], 16) for i in (1, 3, 5))
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            found = dominant_color(self._capture(locator, timeout_ms))
            if all(abs(a - b) <= tolerance for a, b in zip(found, target, strict=True)):
                return
            if time.monotonic() > deadline:
                raise StepFailure(f"dominant colour is #{found[0]:02X}{found[1]:02X}{found[2]:02X}, expected {wanted.upper()} (± {tolerance})")
            self.close_stray_tabs()
            self.keep_window_open()
            self.page.wait_for_timeout(500)

    def _wait_console(self, pattern: re.Pattern[str], timeout_ms: float) -> None:
        """Wait for a console message matching ``pattern`` since the last navigation."""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            if any(pattern.search(line) for line in self._console[self._mark :]):
                return
            if time.monotonic() > deadline:
                raise StepFailure(f"no console message matching {pattern.pattern!r} within {timeout_ms / 1000:g}s")
            self.close_stray_tabs()
            self.keep_window_open()
            self.page.wait_for_timeout(250)

    def _ms(self, seconds: float | None) -> float:
        return (seconds if seconds is not None else self.context.suite.timeout) * 1000


class _ExpectedResponse:
    """Context manager: the wrapped action must trigger a response matching ``wanted``."""

    def __init__(self, page: Page, url: str, wanted: ResponseMatch) -> None:
        self._url = glob_to_regex(url)
        self._wanted = wanted
        self._waiter = page.expect_response(self._matches, timeout=wanted.timeout * 1000)

    def _matches(self, response: Response) -> bool:
        method = self._wanted.method
        return bool(self._url.match(response.url)) and (method is None or response.request.method == method.upper())

    def __enter__(self) -> None:
        self._info = self._waiter.__enter__()

    def __exit__(self, exc_type: type[BaseException] | None, *rest: object) -> None:
        try:
            self._waiter.__exit__(exc_type, *rest)
        except PlaywrightError as error:
            if exc_type is None:
                raise StepFailure(f"no response matching {self._wanted.url} within {self._wanted.timeout:g}s") from error
            return
        if exc_type is not None:
            return
        response = self._info.value
        if not status_matches(self._wanted.status, response.status):
            raise StepFailure(
                f"{response.request.method} {response.url} answered {response.status}, expected {self._wanted.status}"
                + _body_excerpt(response)
            )


def _body_excerpt(response: Response) -> str:
    """': <the start of the response body>', which often says why the server refused; '' if none."""
    try:
        text = " ".join(response.text().split())
    except PlaywrightError:
        return ""
    return f": {text[:300]}" if text else ""


def _box(locator: Locator, timeout_ms: float) -> dict[str, float]:
    """The element's on-screen box, once it is visible and scrolled into view."""
    locator.scroll_into_view_if_needed(timeout=timeout_ms)
    box = locator.bounding_box(timeout=timeout_ms)
    if box is None:
        raise StepFailure(f"{locator} is not visible")
    return box


def _is_selected(locator: Locator, timeout_ms: float) -> bool:
    return locator.get_attribute("aria-selected", timeout=timeout_ms) == "true"


def _css_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
