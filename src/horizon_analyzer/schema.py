"""The scenario file format: a suite of features, each a list of steps.

A step is a mapping with exactly one action key (``goto``, ``click``, ``expect``...) and that
action's options beside it::

    - click: { role: button, name: Sign In }
      expect_response: { url: "**/login", status: 2xx }

Every model forbids unknown keys, so a typo in a scenario fails validation before any browser
starts instead of silently doing nothing.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*$")


def parse_duration(value: Any) -> float:
    """Turn ``"500ms"``, ``"30s"``, ``"2m"`` or a bare number of seconds into seconds."""
    if isinstance(value, bool):
        raise ValueError("a duration is a number of seconds or a string like '30s'")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and (match := _DURATION.match(value)):
        amount, unit = float(match.group(1)), match.group(2) or "s"
        return amount / 1000 if unit == "ms" else amount * 60 if unit == "m" else amount
    raise ValueError(f"invalid duration {value!r}: expected e.g. 500ms, 30s, 2m or 12")


Duration = Annotated[float, BeforeValidator(parse_duration)]


def check_regex(pattern: str, what: str) -> re.Pattern[str]:
    """Compile ``pattern``, turning a syntax error into a ``ValueError`` validation can report."""
    try:
        return re.compile(pattern)
    except re.error as error:
        raise ValueError(f"{what} {pattern!r} is not a valid regex: {error}") from None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- targets

_TARGET_BASES = ("testid", "role", "label", "text", "placeholder", "title", "id", "css")


class Target(_Strict):
    """What to act on. Exactly one base selector, optionally narrowed.

    Bases, in order of preference: ``testid`` (data-testid), ``role`` (+ ``name``), ``label``,
    ``text``, ``placeholder``, ``title``, ``id``, ``css``. Narrowing: ``within`` (search inside
    another target), ``has_text`` / ``has`` (keep matches containing that text or target) and
    ``nth`` (``first``, ``last`` or an index; without it, several matches is an error).
    ``frame`` is the CSS selector of an iframe to search in (e.g. a Stripe payment form); it
    applies before ``within``.
    """

    frame: str | None = None
    testid: str | None = None
    role: str | None = None
    name: str | None = None
    exact: bool = False
    label: str | None = None
    text: str | None = None
    placeholder: str | None = None
    title: str | None = None
    id: str | None = None
    css: str | None = None
    has_text: str | None = None
    has: Target | None = None
    within: Target | None = None
    nth: int | Literal["first", "last"] | None = None

    @model_validator(mode="after")
    def _one_base(self) -> Target:
        bases = [key for key in _TARGET_BASES if getattr(self, key) is not None]
        if len(bases) != 1:
            found = ", ".join(bases) if bases else "none"
            raise ValueError(f"a target needs exactly one of {', '.join(_TARGET_BASES)} (found: {found})")
        if self.name is not None and self.role is None:
            raise ValueError("'name' only goes with 'role'")
        return self

    def describe(self) -> str:
        """A short human-readable form, e.g. ``role=button "Sign In"``."""
        base = next(key for key in _TARGET_BASES if getattr(self, key) is not None)
        text = f"{base}={getattr(self, base)}"
        if self.name is not None:
            text += f' "{self.name}"'
        if self.has_text is not None:
            text += f' has_text="{self.has_text}"'
        if self.has is not None:
            text += f" has({self.has.describe()})"
        if self.nth is not None:
            text += f" nth={self.nth}"
        if self.within is not None:
            text = f"{self.within.describe()} > {text}"
        if self.frame is not None:
            text = f"frame({self.frame}) > {text}"
        return text


class Point(_Strict):
    """A position in pixels from an element's top-left corner."""

    x: float
    y: float


class ResponseMatch(_Strict):
    """A network response the action must trigger. ``url`` is a glob (``*`` and ``**`` match anything)."""

    url: str
    method: str | None = None
    status: str | int = "2xx"
    timeout: Duration = 30.0

    @field_validator("status")
    @classmethod
    def _status_shape(cls, value: str | int) -> str | int:
        if isinstance(value, int) or re.fullmatch(r"[1-5](xx|\d\d)", value):
            return value
        raise ValueError("status is a code (201) or a class (2xx)")


# --------------------------------------------------------------------------- steps


class _Step(_Strict):
    ACTION: ClassVar[str]

    def describe(self) -> str:
        return self.ACTION


class GotoStep(_Step):
    """Open a URL. ``${base.editor}/`` resolves against the suite's ``base_urls``."""

    ACTION: ClassVar[str] = "goto"
    goto: str
    expect_response: ResponseMatch | None = None

    def describe(self) -> str:
        return f"goto {self.goto}"


class ClickStep(_Step):
    """Click ``click``. ``button: right`` opens a context menu; ``position`` clicks at that point of the element."""

    ACTION: ClassVar[str] = "click"
    click: Target
    button: Literal["left", "right", "middle"] = "left"
    position: Point | None = None
    force: bool = False
    expect_response: ResponseMatch | None = None
    timeout: Duration | None = None

    def describe(self) -> str:
        prefix = "click" if self.button == "left" else f"{self.button}-click"
        return f"{prefix} {self.click.describe()}"


class SelectStep(_Step):
    """Make sure ``select`` is selected: click it only if it isn't (``aria-selected`` / checked).

    For rows that toggle on click, such as tree items: a plain click on a selected row would
    deselect it.
    """

    ACTION: ClassVar[str] = "select"
    select: Target
    timeout: Duration | None = None

    def describe(self) -> str:
        return f"select {self.select.describe()}"


class HoverStep(_Step):
    ACTION: ClassVar[str] = "hover"
    hover: Target
    timeout: Duration | None = None

    def describe(self) -> str:
        return f"hover {self.hover.describe()}"


class FillStep(_Step):
    """Replace a field's content with ``value``."""

    ACTION: ClassVar[str] = "fill"
    fill: Target
    value: str
    timeout: Duration | None = None

    def describe(self) -> str:
        return f"fill {self.fill.describe()}"


class PressStep(_Step):
    """Press a key (``Enter``, ``Delete``, ``Control+Z``) on ``target``, or on whatever has focus.

    (Not ``on``: YAML 1.1 reads a bare ``on`` key as the boolean true.)
    """

    ACTION: ClassVar[str] = "press"
    press: str
    target: Target | None = None

    def describe(self) -> str:
        return f"press {self.press}" + (f" on {self.target.describe()}" if self.target else "")


class UploadStep(_Step):
    """Put files into an ``<input type=file>``. Paths are relative to the scenario file."""

    ACTION: ClassVar[str] = "upload"
    upload: Target
    files: list[str] = Field(min_length=1)

    def describe(self) -> str:
        return f"upload {', '.join(self.files)} into {self.upload.describe()}"


class DragStep(_Step):
    """Drag ``drag`` onto ``to`` with the mouse: HTML5 drag and drop (an asset onto the viewport),
    a node moved in the script editor, or a wire pulled from one handle to another.

    ``to_position`` drops at that point of ``to`` (from its top-left corner) instead of its centre.
    ``steps`` moves the mouse there in that many small moves, holding the button, instead of
    Playwright's HTML5 drag: node editors (xyflow) ignore a single jump. With ``steps``, the
    press happens at the centre of ``drag``, whatever covers it.
    """

    ACTION: ClassVar[str] = "drag"
    drag: Target
    to: Target
    to_position: Point | None = None
    steps: int | None = Field(default=None, ge=1, le=100)
    timeout: Duration | None = None

    def describe(self) -> str:
        at = f" at ({self.to_position.x:g}, {self.to_position.y:g})" if self.to_position else ""
        return f"drag {self.drag.describe()} to {self.to.describe()}{at}"


class ChooseStep(_Step):
    """Pick ``option`` (its value or its visible label) in a ``<select>``."""

    ACTION: ClassVar[str] = "choose"
    choose: Target
    option: str
    timeout: Duration | None = None

    def describe(self) -> str:
        return f"choose {self.option!r} in {self.choose.describe()}"


class WaitStep(_Step):
    """A fixed pause. Prefer an ``expect``, which waits only as long as needed."""

    ACTION: ClassVar[str] = "wait"
    wait: Duration

    def describe(self) -> str:
        return f"wait {self.wait:g}s"


class ReloadStep(_Step):
    ACTION: ClassVar[str] = "reload"
    reload: Literal[True]

    def describe(self) -> str:
        return "reload"


class ScreenshotStep(_Step):
    """Save a screenshot named ``screenshot`` (of the page, or only of ``of``) into the run's folder."""

    ACTION: ClassVar[str] = "screenshot"
    screenshot: str = Field(pattern=r"^[\w.-]+$")
    of: Target | None = None

    def describe(self) -> str:
        return f"screenshot {self.screenshot}"


class StoreStep(_Step):
    """Remember a value as ``${var.<store>}``.

    Sources: group 1 of ``url_pattern`` on the URL, a target's text (``text_of``), or the result
    of a JavaScript expression run in the page (``js``; it may return a promise, e.g. a fetch).
    """

    ACTION: ClassVar[str] = "store"
    store: str = Field(pattern=r"^[A-Za-z_][\w-]*$")
    url_pattern: str | None = None
    text_of: Target | None = None
    js: str | None = None

    @model_validator(mode="after")
    def _one_source(self) -> StoreStep:
        if sum(source is not None for source in (self.url_pattern, self.text_of, self.js)) != 1:
            raise ValueError("store needs exactly one of url_pattern, text_of, js")
        if self.url_pattern is not None and check_regex(self.url_pattern, "url_pattern").groups < 1:
            raise ValueError("url_pattern needs a capture group, e.g. 'id=(\\w+)'")
        return self

    def describe(self) -> str:
        return f"store {self.store}"


_TARGET_CHECKS = ("visible", "text", "value", "number", "count", "enabled", "checked", "rendered", "animated", "dominant_color")
_HEX_COLOR = r"^(#[0-9A-Fa-f]{6}|\$\{[^}]+\})$"  # or a ${var.x} holding one, checked once rendered
_PAGE_CHECKS = ("url", "title", "console", "no_console", "js")


class Expectation(_Strict):
    """One or more checks, retried until they hold or ``timeout`` runs out.

    On a ``target``: ``visible`` (true/false), ``text`` (contains), ``value`` (exact, for
    inputs), ``number`` (the input's value or the text, read as a number, equals this within
    ``tolerance``: for engine values such as a rotation that comes back as 45.000004 after a
    quaternion round trip), ``count``, ``enabled``, ``checked`` (checkbox or radio), ``rendered`` (true: the
    element's pixels are not one flat colour, e.g. a game canvas that draws something; false: it
    is blank), ``animated`` (true: two captures a moment apart differ, e.g. an object a script
    keeps turning; false: the image holds still), ``dominant_color`` (``#RRGGBB``: the element's
    most common colour, e.g. a game's background, is this one within ``color_tolerance`` per
    channel). On the page: ``url`` (glob), ``title`` (contains), ``console`` (a console message
    matching this regex appears), ``no_console`` (no message matching this regex since the
    feature started), ``js`` (expression or function, possibly async, becomes truthy).
    """

    target: Target | None = None
    visible: bool | None = None
    text: str | None = None
    value: str | None = None
    number: float | str | None = None
    tolerance: float = Field(default=0.001, ge=0)
    count: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    checked: bool | None = None
    rendered: bool | None = None
    animated: bool | None = None
    dominant_color: str | None = Field(default=None, pattern=_HEX_COLOR)
    color_tolerance: int = Field(default=12, ge=0, le=255)
    url: str | None = None
    title: str | None = None
    console: str | None = None
    no_console: str | None = None
    js: str | None = None
    timeout: Duration | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Expectation:
        target_checks = [key for key in _TARGET_CHECKS if getattr(self, key) is not None]
        page_checks = [key for key in _PAGE_CHECKS if getattr(self, key) is not None]
        if not target_checks and not page_checks:
            raise ValueError(f"expect needs at least one check: {', '.join(_TARGET_CHECKS + _PAGE_CHECKS)}")
        if target_checks and self.target is None:
            raise ValueError(f"{', '.join(target_checks)} need a 'target'")
        if self.target is not None and not target_checks:
            raise ValueError(f"a 'target' needs one of {', '.join(_TARGET_CHECKS)}")
        for key in ("console", "no_console"):
            if (pattern := getattr(self, key)) is not None:
                check_regex(pattern, key)
        return self

    def describe(self) -> str:
        checks = [f"{key}={getattr(self, key)!r}" for key in _TARGET_CHECKS + _PAGE_CHECKS if getattr(self, key) is not None]
        on = f"{self.target.describe()} " if self.target else ""
        return f"expect {on}{' '.join(checks)}"


class ExpectStep(_Step):
    ACTION: ClassVar[str] = "expect"
    expect: Expectation

    def describe(self) -> str:
        return self.expect.describe()


STEP_MODELS: dict[str, type[_Step]] = {
    model.ACTION: model
    for model in (
        GotoStep,
        ClickStep,
        SelectStep,
        HoverStep,
        FillStep,
        PressStep,
        UploadStep,
        DragStep,
        ChooseStep,
        WaitStep,
        ReloadStep,
        ScreenshotStep,
        StoreStep,
        ExpectStep,
    )
}

Step = (
    GotoStep
    | ClickStep
    | SelectStep
    | HoverStep
    | FillStep
    | PressStep
    | UploadStep
    | DragStep
    | ChooseStep
    | WaitStep
    | ReloadStep
    | ScreenshotStep
    | StoreStep
    | ExpectStep
)


def _format_errors(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        where = ".".join(str(part) for part in item["loc"])
        parts.append(f"{where}: {item['msg']}" if where else item["msg"])
    return "; ".join(parts)


def parse_step(raw: Any) -> Any:
    """Pick the step model from the one action key the mapping carries, then validate it."""
    if isinstance(raw, _Step):
        return raw
    if not isinstance(raw, dict):
        raise ValueError("a step is a mapping, e.g. '- click: { role: button, name: OK }'")
    actions = [key for key in raw if key in STEP_MODELS]
    if len(actions) != 1:
        found = ", ".join(actions) if actions else f"none (keys: {', '.join(map(str, raw))})"
        raise ValueError(f"a step needs exactly one action among {', '.join(STEP_MODELS)}; found {found}")
    try:
        return STEP_MODELS[actions[0]].model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"{actions[0]}: {_format_errors(error)}") from None


StepField = Annotated[Step, BeforeValidator(parse_step)]


# --------------------------------------------------------------------------- features and suite


class Feature(_Strict):
    """A user-facing feature, checked by its ``steps``.

    ``depends_on`` lists features declared earlier: if one did not pass, this one is skipped.
    ``cleanup`` steps undo what the feature created; they run at the end of the run, in reverse
    order of the features, even when something failed. ``teardown`` steps run right after the
    feature, whether it passed or failed, to put the page back in a state the next features can
    work from (close a dialog, stop the game); a failing teardown fails a feature that had
    passed. ``mutating`` marks a feature that writes
    to production (``--safe-only`` leaves it out). ``requires_webgpu`` marks it ``blocked``
    rather than failed when the browser has no WebGPU adapter.
    """

    id: str = Field(pattern=r"^[A-Za-z0-9][\w.-]*$")
    name: str
    tags: list[str] = []
    depends_on: list[str] = []
    mutating: bool = False
    requires_webgpu: bool = False
    steps: list[StepField] = Field(min_length=1)
    teardown: list[StepField] = []
    cleanup: list[StepField] = []


class Suite(_Strict):
    """A scenario file. ``base_urls`` are reachable as ``${base.<name>}``, ``vars`` as ``${var.<name>}``.

    ``locale`` (e.g. ``fr-FR``) fixes the browser language, so text selectors don't change with
    the machine running the suite (the launcher and Stripe follow the browser's language).

    ``ignore_console`` hides matching console errors from the report. ``fail_on_console`` fails
    a feature whose steps all passed when one of its console errors matches, whenever it
    appeared during the feature (a wasm panic can land after the step that would have caught it).
    """

    suite: str
    description: str | None = None
    base_urls: dict[str, str] = {}
    vars: dict[str, str] = {}
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    timeout: Duration = 15.0
    dialogs: Literal["accept", "dismiss"] = "accept"
    ignore_console: list[str] = []
    fail_on_console: list[str] = []
    features: list[Feature] = Field(min_length=1)

    @field_validator("ignore_console", "fail_on_console")
    @classmethod
    def _valid_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            check_regex(pattern, "console pattern")
        return patterns

    @model_validator(mode="after")
    def _dependencies_declared_before(self) -> Suite:
        seen: set[str] = set()
        for feature in self.features:
            if feature.id in seen:
                raise ValueError(f"feature id {feature.id!r} is used twice")
            for dependency in feature.depends_on:
                if dependency not in seen:
                    raise ValueError(
                        f"{feature.id} depends on {dependency!r}, which must be a feature declared before it"
                    )
            seen.add(feature.id)
        return self

    def feature(self, feature_id: str) -> Feature:
        return next(feature for feature in self.features if feature.id == feature_id)


def json_schema() -> dict[str, Any]:
    """The JSON Schema of a scenario file, with each step spelled as one of the step models.

    ``parse_step`` picks the model by its action key, which a plain union can't express, so the
    generated schema's step items are replaced by an ``anyOf`` of the step models.
    """
    schema = Suite.model_json_schema()
    definitions = schema.setdefault("$defs", {})
    for model in STEP_MODELS.values():
        step_schema = model.model_json_schema(ref_template="#/$defs/{model}")
        definitions.update(step_schema.pop("$defs", {}))
        definitions[model.__name__] = step_schema
    any_step = {"anyOf": [{"$ref": f"#/$defs/{model.__name__}"} for model in STEP_MODELS.values()]}
    for key in ("steps", "teardown", "cleanup"):
        definitions["Feature"]["properties"][key]["items"] = any_step
    return schema
