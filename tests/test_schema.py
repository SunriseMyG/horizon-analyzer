import pytest
from pydantic import ValidationError

from horizon_analyzer.schema import ClickStep, ExpectStep, Suite, Target, json_schema, parse_duration


def suite(**overrides):
    data = {"suite": "s", "features": [{"id": "A", "name": "a", "steps": [{"goto": "https://x"}]}]}
    data.update(overrides)
    return Suite.model_validate(data)


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [(12, 12.0), (1.5, 1.5), ("500ms", 0.5), ("30s", 30.0), ("2m", 120.0), (" 7 ", 7.0)],
)
def test_parse_duration(raw, seconds):
    assert parse_duration(raw) == seconds


@pytest.mark.parametrize("raw", ["soon", "3h", True, None])
def test_parse_duration_rejects(raw):
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_step_is_picked_by_its_action_key():
    parsed = suite().features[0].steps[0]
    assert parsed.ACTION == "goto"


def test_step_options_sit_beside_the_action():
    feature = {
        "id": "A",
        "name": "a",
        "steps": [{"click": {"role": "button", "name": "OK"}, "expect_response": {"url": "**/x", "status": 201}}],
    }
    step = suite(features=[feature]).features[0].steps[0]
    assert isinstance(step, ClickStep)
    assert step.expect_response.status == 201


@pytest.mark.parametrize(
    ("step", "message"),
    [
        ({"clik": {"text": "a"}}, "exactly one action"),
        ({"click": {"text": "a"}, "goto": "x"}, "exactly one action"),
        ({"click": {"text": "a"}, "valeu": "x"}, "Extra inputs"),
        ({"click": {}}, "exactly one of testid"),
        ({"click": {"text": "a", "css": "b"}}, "exactly one of testid"),
        ({"click": {"label": "a", "name": "b"}}, "'name' only goes with 'role'"),
        ({"expect": {"visible": True}}, "need a 'target'"),
        ({"expect": {"target": {"text": "a"}}}, "at least one check"),
        ({"expect": {"target": {"text": "a"}, "url": "**/x"}}, "a 'target' needs one of"),
        ({"expect": {"console": "("}}, "not a valid regex"),
        ({"store": "x"}, "exactly one of url_pattern, text_of, js"),
        ({"store": "x", "js": "1", "text_of": {"text": "a"}}, "exactly one of url_pattern, text_of, js"),
        ({"click": {"text": "a"}, "button": "double"}, "button"),
        ({"select": {"text": "a"}, "value": "x"}, "Extra inputs"),
        ({"store": "x", "url_pattern": "id=\\w+"}, "capture group"),
        ("goto", "a step is a mapping"),
    ],
)
def test_invalid_steps_are_explained(step, message):
    with pytest.raises(ValidationError, match=message):
        suite(features=[{"id": "A", "name": "a", "steps": [step]}])


def test_dependencies_must_be_declared_earlier():
    features = [
        {"id": "B", "name": "b", "depends_on": ["A"], "steps": [{"goto": "x"}]},
        {"id": "A", "name": "a", "steps": [{"goto": "x"}]},
    ]
    with pytest.raises(ValidationError, match="must be a feature declared before it"):
        suite(features=features)


def test_duplicate_feature_ids_are_refused():
    feature = {"id": "A", "name": "a", "steps": [{"goto": "x"}]}
    with pytest.raises(ValidationError, match="used twice"):
        suite(features=[feature, feature])


def test_invalid_console_pattern_is_refused():
    with pytest.raises(ValidationError, match="not a valid regex"):
        suite(fail_on_console=["("])


def test_target_describe_reads_like_a_path():
    target = Target.model_validate({"role": "spinbutton", "name": "X", "within": {"css": "div", "has_text": "position"}})
    assert target.describe() == 'css=div has_text="position" > role=spinbutton "X"'


def test_expect_describe_lists_checks():
    step = ExpectStep.model_validate({"expect": {"target": {"id": "a"}, "value": "5"}})
    assert step.describe() == "expect id=a value='5'"


def test_json_schema_spells_every_step():
    schema = json_schema()
    items = schema["$defs"]["Feature"]["properties"]["steps"]["items"]
    assert {ref["$ref"].rsplit("/", 1)[1] for ref in items["anyOf"]} >= {"ClickStep", "ExpectStep", "UploadStep"}
    assert "Target" in schema["$defs"]
