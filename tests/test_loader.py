import os
from pathlib import Path

import pytest

from horizon_analyzer.loader import Context, ScenarioError, load_dotenv, load_suite, referenced_variables
from horizon_analyzer.schema import Suite

SCENARIOS = Path(__file__).resolve().parent.parent / "scenarios"


def make_context(tmp_path: Path, **suite_fields) -> Context:
    data = {
        "suite": "s",
        "base_urls": {"editor": "https://editor.example/"},
        "vars": {"name": "cube"},
        "features": [{"id": "A", "name": "a", "steps": [{"goto": "x"}]}],
        **suite_fields,
    }
    return Context(suite=Suite.model_validate(data), base_dir=tmp_path, run_id="RUN1")


def test_render_resolves_every_namespace(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_TEST_USER", "alice@example.com")
    context = make_context(tmp_path)
    text = context.render("${base.editor}/p/e2e-${run.id}/${var.name}?u=${env.HA_TEST_USER}")
    assert text == "https://editor.example/p/e2e-RUN1/cube?u=alice@example.com"


def test_env_values_are_masked(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_TEST_PASSWORD", "s3cret!")
    context = make_context(tmp_path)
    context.render("${env.HA_TEST_PASSWORD}")
    assert context.mask("login failed for s3cret!") == "login failed for ***"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("${env.HA_TEST_MISSING}", "is not set"),
        ("${base.nope}", "unknown base url"),
        ("${var.later}", "not defined yet"),
        ("${run.date}", "only ${run.id}"),
    ],
)
def test_render_explains_unknown_variables(tmp_path, monkeypatch, text, message):
    monkeypatch.delenv("HA_TEST_MISSING", raising=False)
    with pytest.raises(ScenarioError, match=message.replace("$", r"\$").replace("{", r"\{").replace("}", r"\}")):
        make_context(tmp_path).render(text)


def test_stored_variables_resolve(tmp_path):
    context = make_context(tmp_path)
    context.variables["project_id"] = "abc"
    assert context.render("id=${var.project_id}") == "id=abc"


def test_dotenv_does_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HA_TEST_KEPT", "from-shell")
    monkeypatch.delenv("HA_TEST_NEW", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nHA_TEST_KEPT=from-file\nHA_TEST_NEW='quoted value'\n\n", encoding="utf-8")
    load_dotenv(env)
    assert os.environ["HA_TEST_KEPT"] == "from-shell"
    assert os.environ["HA_TEST_NEW"] == "quoted value"
    monkeypatch.delenv("HA_TEST_NEW")


def test_load_suite_reports_by_feature_id(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "suite: s\nfeatures:\n  - id: F1-login\n    name: a\n    steps:\n      - clik: { text: a }\n",
        encoding="utf-8",
    )
    with pytest.raises(ScenarioError, match=r"features\[F1-login\]\.steps\[1\]"):
        load_suite(path)


def test_load_suite_reads_json(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"suite": "s", "features": [{"id": "A", "name": "a", "steps": [{"wait": "1s"}]}]}', encoding="utf-8")
    assert load_suite(path).features[0].steps[0].wait == 1.0


def test_resolve_file_is_relative_to_the_scenario(tmp_path):
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "a.glb").write_bytes(b"x")
    context = make_context(tmp_path)
    assert context.resolve_file("fixtures/a.glb") == (tmp_path / "fixtures" / "a.glb").resolve()
    with pytest.raises(ScenarioError, match="not found"):
        context.resolve_file("fixtures/missing.glb")


@pytest.mark.parametrize("name", ["critical.yaml", "smoke.yaml"])
def test_shipped_scenarios_are_valid(name):
    suite = load_suite(SCENARIOS / name)
    assert ("env", "HORIZON_PASSWORD") in referenced_variables(suite)
