"""The Playwright executor against a local page: real Chromium, headless, no network."""

from pathlib import Path

import pytest

from horizon_analyzer.browser import BrowserOptions, PlaywrightExecutor, drawn_fraction, glob_to_regex, status_matches
from horizon_analyzer.loader import Context
from horizon_analyzer.runner import Status, run_suite
from horizon_analyzer.schema import Suite

PAGE = """<!doctype html><html><head><title>Fixture page</title></head><body>
<h1>Welcome back, Tester</h1>
<label for="email">Email</label><input id="email" type="email">
<div class="flex-col"><span>position</span><label>X <input role="spinbutton" aria-label="X" value="0"></label></div>
<div class="flex-col"><span>scale</span><label>X <input role="spinbutton" aria-label="X" value="1"></label></div>
<input type="file" id="upload">
<ul role="tree"></ul>
<button onclick="add()">Add object</button>
<button title="Delete Project" onclick="if (confirm('sure?')) document.querySelector('h1').remove()">x</button>
<script>
function add() {
  const li = document.createElement('li'); li.setAttribute('role', 'treeitem'); li.textContent = 'Object';
  setTimeout(() => document.querySelector('[role=tree]').appendChild(li), 300);
  console.log('scene: object spawned');
}
document.getElementById('upload').addEventListener('change', e => console.log('uploaded ' + e.target.files[0].name));
</script>
<div role="listbox" id="rows">
  <div role="option" aria-selected="false" onclick="this.setAttribute('aria-selected', this.getAttribute('aria-selected') === 'true' ? 'false' : 'true')">Camera</div>
</div>
<div id="zone" style="width:200px;height:100px;background:#eee" oncontextmenu="event.preventDefault(); document.getElementById('menu').hidden = false; this.dataset.x = event.offsetX"></div>
<div id="menu" role="menu" hidden><div role="menuitem">Directional Light</div></div>
<label><input type="radio" name="tool" value="rotate"> rotate</label>
<a id="legal" href="about:blank#legal" target="_blank">Conditions</a>
<select id="kind"><option value="int">int</option><option value="float">float</option></select>
<canvas id="spin" width="120" height="80" style="background:#3366cc"></canvas>
<div id="node" draggable="true" style="width:40px;height:20px;background:#ccc">node</div>
<div id="board" style="width:300px;height:100px;background:#eee"
     ondragover="event.preventDefault()" ondrop="event.preventDefault(); this.dataset.drop = Math.round(event.offsetX) + ',' + Math.round(event.offsetY)"></div>
<div id="pad" style="width:300px;height:100px;background:#ddd"
     onmousedown="this.dataset.moves = 0" onmousemove="if (event.buttons) this.dataset.moves = +this.dataset.moves + 1"
     onmouseup="this.dataset.up = Math.round(event.offsetX) + ',' + Math.round(event.offsetY)"></div>
<script>
const s = document.getElementById('spin').getContext('2d'); let angle = 0;
(function frame() { s.clearRect(0, 0, 120, 80); s.save(); s.translate(60, 40); s.rotate(angle += 0.1);
  s.fillStyle = '#fff'; s.fillRect(-15, -15, 30, 30); s.restore(); requestAnimationFrame(frame); })();
</script>
<canvas id="blank" width="120" height="80" style="background:#111"></canvas>
<canvas id="drawn" width="120" height="80" style="background:#111"></canvas>
<iframe id="pay" srcdoc="<label for=card>Card</label><input id=card><button data-testid=submit onclick=&quot;document.body.dataset.paid='yes'&quot;>Pay</button>"></iframe>
<script>
const g = document.getElementById('drawn').getContext('2d'); g.fillStyle = '#eaeaea'; g.fillRect(40, 20, 40, 40);
</script>
</body></html>"""


@pytest.fixture(scope="module")
def page_url(tmp_path_factory):
    folder = tmp_path_factory.mktemp("site")
    (folder / "index.html").write_text(PAGE, encoding="utf-8")
    (folder / "fixtures").mkdir()
    (folder / "fixtures" / "model.glb").write_bytes(b"glTF")
    return folder, (folder / "index.html").as_uri()


def run_steps(folder, url, steps, **suite_fields):
    suite = Suite.model_validate(
        {"suite": "local", "timeout": "3s", "vars": {"url": url}, "features": [{"id": "T", "name": "t", "steps": steps}], **suite_fields}
    )
    context = Context(suite=suite, base_dir=folder, run_id="R")
    out = folder / "out"
    out.mkdir(exist_ok=True)
    with PlaywrightExecutor(context, out, BrowserOptions(headless=True, trace=False)) as executor:
        result = run_suite(suite, suite.features, executor, context)
    return result.features[0], context


@pytest.mark.browser
def test_a_full_journey_passes(page_url):
    folder, url = page_url
    position_x = {"role": "spinbutton", "name": "X", "within": {"css": "div.flex-col", "has": {"css": ":scope > span", "has_text": "position"}}}
    feature, context = run_steps(
        folder,
        url,
        [
            {"goto": "${var.url}"},
            {"expect": {"title": "Fixture", "target": {"role": "heading", "name": "Welcome back"}, "visible": True}},
            {"fill": {"label": "Email"}, "value": "a@b.c"},
            {"expect": {"target": {"label": "Email"}, "value": "a@b.c"}},
            {"fill": position_x, "value": "5"},
            {"press": "Enter", "target": position_x},
            {"expect": {"target": position_x, "value": "5"}},
            {"upload": {"id": "upload"}, "files": ["fixtures/model.glb"]},
            {"expect": {"console": "uploaded model\\.glb"}},
            {"click": {"role": "button", "name": "Add object"}},
            {"expect": {"target": {"role": "treeitem", "within": {"role": "tree"}}, "count": 1}},
            {"store": "first", "text_of": {"role": "treeitem", "nth": "first"}},
            {"expect": {"js": "document.title.length > 3"}},
            {"click": {"title": "Delete Project"}},
            {"expect": {"target": {"role": "heading", "name": "Welcome back"}, "count": 0}},
            {"screenshot": "end"},
        ],
    )
    assert feature.status is Status.PASSED, feature.reason
    assert context.variables["first"] == "Object"
    assert feature.steps[-1].attachments == ["screenshots/T-end.png"]
    assert (folder / "out" / "screenshots" / "T-end.png").is_file()


@pytest.mark.browser
def test_engine_style_interactions(page_url):
    folder, url = page_url
    row = {"role": "option", "name": "Camera"}
    frame = "iframe#pay"
    feature, context = run_steps(
        folder,
        url,
        [
            {"goto": "${var.url}"},
            # select clicks once, then leaves an already selected row alone (a click would toggle it off)
            {"select": row},
            {"select": row},
            {"expect": {"js": "document.querySelector('[role=option]').getAttribute('aria-selected') === 'true'"}},
            {"click": {"id": "zone"}, "button": "right", "position": {"x": 150, "y": 50}},
            {"expect": {"target": {"role": "menuitem", "name": "Directional Light"}, "visible": True}},
            {"expect": {"js": "document.getElementById('zone').dataset.x === '150'"}},
            {"click": {"css": "label:has(input[value=rotate])"}},
            {"expect": {"target": {"css": "input[value=rotate]"}, "checked": True}},
            {"expect": {"target": {"id": "drawn"}, "rendered": True}},
            {"expect": {"target": {"id": "blank"}, "rendered": False}},
            {"fill": {"frame": frame, "label": "Card"}, "value": "4242424242424242"},
            {"expect": {"target": {"frame": frame, "id": "card"}, "value": "4242424242424242"}},
            {"click": {"frame": frame, "testid": "submit"}},
            {"fill": {"role": "spinbutton", "name": "X", "within": {"css": "div.flex-col", "has_text": "scale"}}, "value": "45.000004"},
            {"expect": {"target": {"role": "spinbutton", "name": "X", "within": {"css": "div.flex-col", "has_text": "scale"}}, "number": 45, "tolerance": 0.01}},
            {"store": "lang", "js": "async () => navigator.language"},
            {"expect": {"js": "async () => { await new Promise(r => setTimeout(r, 50)); return document.title === 'Fixture page'; }"}},
        ],
        locale="fr-FR",
    )
    assert feature.status is Status.PASSED, feature.reason
    assert context.variables["lang"] == "fr-FR"


@pytest.mark.browser
def test_script_editor_style_interactions(page_url):
    """choose in a <select>, drag to a point, a canvas that keeps moving, a background colour."""
    folder, url = page_url
    feature, _ = run_steps(
        folder,
        url,
        [
            {"goto": "${var.url}"},
            {"choose": {"id": "kind"}, "option": "float"},
            {"expect": {"target": {"id": "kind"}, "value": "float"}},
            {"drag": {"id": "node"}, "to": {"id": "board"}, "to_position": {"x": 250, "y": 30}},
            {"expect": {"js": "document.getElementById('board').dataset.drop === '250,30'"}},
            # steps: a mouse drag in small moves, as a node editor needs
            {"drag": {"id": "pad"}, "to": {"id": "pad"}, "to_position": {"x": 280, "y": 20}, "steps": 8},
            {"expect": {"js": "document.getElementById('pad').dataset.up === '280,20' && +document.getElementById('pad').dataset.moves >= 8"}},
            {"expect": {"target": {"id": "spin"}, "animated": True}},
            {"expect": {"target": {"id": "drawn"}, "animated": False}},
            {"expect": {"target": {"id": "spin"}, "dominant_color": "#3366CC"}},
            {"expect": {"target": {"id": "drawn"}, "dominant_color": "#111111", "color_tolerance": 2}},
        ],
    )
    assert feature.status is Status.PASSED, feature.reason


@pytest.mark.browser
def test_element_screenshot_is_cut_out_of_the_viewport(page_url):
    """`screenshot: of:` and the pixel checks crop a viewport capture to the element's box."""
    from PIL import Image

    folder, url = page_url
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"screenshot": "canvas", "of": {"id": "spin"}}])
    assert feature.status is Status.PASSED, feature.reason
    image = Image.open(folder / "out" / "screenshots" / "T-canvas.png").convert("RGB")
    assert image.size == (120, 80)
    assert image.getpixel((3, 3)) == (0x33, 0x66, 0xCC)


@pytest.mark.browser
def test_still_element_fails_animated_and_wrong_colour_fails(page_url):
    folder, url = page_url
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"expect": {"target": {"id": "drawn"}, "animated": True, "timeout": "1s"}}])
    assert feature.status is Status.FAILED and "holds still" in feature.reason
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"expect": {"target": {"id": "drawn"}, "dominant_color": "#3366CC", "timeout": "500ms"}}])
    assert feature.status is Status.FAILED and "dominant colour is #111111" in feature.reason


@pytest.mark.browser
def test_console_wait_sees_messages_logged_before_the_feature(page_url):
    """A message logged during the previous feature, after the last navigation, still counts."""
    folder, url = page_url
    suite = Suite.model_validate(
        {
            "suite": "local",
            "timeout": "2s",
            "vars": {"url": url},
            "features": [
                {"id": "A", "name": "a", "steps": [{"goto": "${var.url}"}, {"click": {"role": "button", "name": "Add object"}}]},
                {"id": "B", "name": "b", "steps": [{"expect": {"console": "object spawned", "timeout": "1s"}}]},
            ],
        }
    )
    context = Context(suite=suite, base_dir=folder, run_id="R")
    with PlaywrightExecutor(context, folder / "out", BrowserOptions(headless=True, trace=False)) as executor:
        result = run_suite(suite, suite.features, executor, context)
    assert [f.status for f in result.features] == [Status.PASSED, Status.PASSED], result.features[1].reason


@pytest.mark.browser
def test_a_tab_opened_by_the_site_is_closed(page_url):
    """A stray click on a target=_blank link must not leave the run stuck behind a new tab."""
    folder, url = page_url
    suite = Suite.model_validate(
        {
            "suite": "local",
            "timeout": "2s",
            "vars": {"url": url},
            "features": [
                {
                    "id": "T",
                    "name": "t",
                    "steps": [{"goto": "${var.url}"}, {"click": {"id": "legal"}}, {"wait": "500ms"}, {"expect": {"title": "Fixture"}}],
                }
            ],
        }
    )
    context = Context(suite=suite, base_dir=folder, run_id="R")
    with PlaywrightExecutor(context, folder / "out", BrowserOptions(headless=True, trace=False)) as executor:
        result = run_suite(suite, suite.features, executor, context)
        assert result.features[0].status is Status.PASSED, result.features[0].reason
        assert executor.closed_tabs == ["about:blank#legal"]
        assert executor.page.context.pages == [executor.page]


@pytest.mark.browser
def test_immutable_assets_are_downloaded_once(tmp_path):
    """The second run gets /_app/immutable/ files from the disk cache, with their content type."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    site = tmp_path / "site"
    (site / "_app" / "immutable").mkdir(parents=True)
    (site / "_app" / "immutable" / "app.abc123.js").write_text("console.log('app booted ' + typeof WebAssembly)", encoding="utf-8")
    (site / "index.html").write_text("<title>Cached</title><script src='/_app/immutable/app.abc123.js'></script>", encoding="utf-8")
    hits = []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            hits.append(self.path)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        suite = Suite.model_validate(
            {"suite": "local", "timeout": "3s", "features": [{"id": "T", "name": "t", "steps": [{"goto": url}, {"expect": {"console": "app booted object"}}]}]}
        )
        context = Context(suite=suite, base_dir=tmp_path, run_id="R")
        counts = []
        for _ in range(2):
            options = BrowserOptions(headless=True, trace=False, asset_cache=tmp_path / "cache")
            with PlaywrightExecutor(context, tmp_path / "out", options) as executor:
                result = run_suite(suite, suite.features, executor, context)
                assert result.features[0].status is Status.PASSED, result.features[0].reason
                counts.append((executor.asset_cache.downloads, executor.asset_cache.hits))
    finally:
        server.shutdown()
    assert counts == [(1, 0), (0, 1)]
    assert sum("/_app/immutable/" in path for path in hits) == 1


@pytest.mark.browser
def test_number_outside_tolerance_fails(page_url):
    folder, url = page_url
    position_x = {"role": "spinbutton", "name": "X", "within": {"css": "div.flex-col", "has_text": "position"}}
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"expect": {"target": position_x, "number": 1, "timeout": "500ms"}}])
    assert feature.status is Status.FAILED
    assert "expected the number 1" in feature.reason and "'0'" in feature.reason


@pytest.mark.browser
def test_blank_canvas_fails_rendered(page_url):
    folder, url = page_url
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"expect": {"target": {"id": "blank"}, "rendered": True, "timeout": "1s"}}])
    assert feature.status is Status.FAILED
    assert "is blank" in feature.reason


def test_drawn_fraction():
    from io import BytesIO

    from PIL import Image

    def png(draw):
        image = Image.new("RGB", (100, 100), (17, 17, 17))
        draw(image)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    assert drawn_fraction(png(lambda image: None)) == 0.0
    square = drawn_fraction(png(lambda image: image.paste((234, 234, 234), (40, 40, 60, 60))))
    assert square == pytest.approx(0.04, abs=0.01)


@pytest.mark.browser
def test_failure_message_and_screenshot(page_url):
    folder, url = page_url
    feature, _ = run_steps(
        folder,
        url,
        [{"goto": "${var.url}"}, {"expect": {"target": {"role": "button", "name": "Missing"}, "visible": True, "timeout": "500ms"}}],
    )
    assert feature.status is Status.FAILED
    assert "step 2" in feature.reason
    assert feature.screenshot == "failures/T.png"


@pytest.mark.browser
def test_ambiguous_target_is_an_error(page_url):
    folder, url = page_url
    feature, _ = run_steps(folder, url, [{"goto": "${var.url}"}, {"fill": {"role": "spinbutton", "name": "X"}, "value": "1", "timeout": "1s"}])
    assert feature.status is Status.FAILED
    assert "strict mode violation" in feature.reason


@pytest.mark.browser
def test_no_console_catches_logged_text(page_url):
    folder, url = page_url
    feature, _ = run_steps(
        folder,
        url,
        [{"goto": "${var.url}"}, {"click": {"role": "button", "name": "Add object"}}, {"expect": {"no_console": "object spawned"}}],
    )
    assert feature.status is Status.FAILED
    assert "object spawned" in feature.steps[-1].error


def test_glob_to_regex():
    assert glob_to_regex("**/catalog/*/lookup").match("https://api.x/catalog/abc123/lookup")
    assert glob_to_regex("**/editor?id=*").match("https://e.x/editor?id=42")
    assert not glob_to_regex("**/convert").match("https://api.x/convert/extra")


@pytest.mark.parametrize(("expected", "actual", "ok"), [("2xx", 201, True), ("2xx", 404, False), (201, 201, True), ("404", 404, True)])
def test_status_matches(expected, actual, ok):
    assert status_matches(expected, actual) is ok
