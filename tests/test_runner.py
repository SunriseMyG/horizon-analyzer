from pathlib import Path

import pytest

from horizon_analyzer.loader import Context, ScenarioError
from horizon_analyzer.runner import Status, StepFailure, run_suite, select_features
from horizon_analyzer.schema import Suite


def feature(fid, *, deps=(), tags=(), mutating=False, webgpu=False, steps=1, cleanup=0, teardown=0):
    return {
        "id": fid,
        "name": fid.lower(),
        "depends_on": list(deps),
        "tags": list(tags),
        "mutating": mutating,
        "requires_webgpu": webgpu,
        "steps": [{"goto": f"https://x/{fid}/{i}"} for i in range(steps)],
        "teardown": [{"goto": f"https://x/{fid}/teardown/{i}"} for i in range(teardown)],
        "cleanup": [{"goto": f"https://x/{fid}/cleanup/{i}"} for i in range(cleanup)],
    }


def make_suite(*features, **fields):
    return Suite.model_validate({"suite": "s", "features": list(features), **fields})


class FakeExecutor:
    """Records each goto; fails the ones listed in ``fail``; logs ``console`` lines per feature."""

    def __init__(self, fail=(), webgpu=True, console=None):
        self.fail = set(fail)
        self.webgpu = webgpu
        self.console = console or {}
        self.calls = []
        self.current = None

    def start_feature(self, feature):
        self.current = feature.id

    def run_step(self, step, feature):
        self.calls.append(step.goto)
        if step.goto in self.fail:
            raise StepFailure(f"boom at {step.goto}")
        return []

    def webgpu_available(self):
        return self.webgpu

    def capture_failure(self, feature):
        return f"failures/{feature.id}.png"

    def console_errors(self):
        return self.console.get(self.current, [])


def run(suite, executor, **filters):
    context = Context(suite=suite, base_dir=Path("."), run_id="R")
    return run_suite(suite, select_features(suite, **filters), executor, context)


def statuses(result):
    return {f.id: f.status for f in result.features}


def test_failure_skips_dependants_but_not_others():
    suite = make_suite(feature("A"), feature("B", deps=["A"]), feature("C"))
    result = run(suite, FakeExecutor(fail={"https://x/A/0"}))
    assert statuses(result) == {"A": Status.FAILED, "B": Status.SKIPPED, "C": Status.PASSED}
    assert "depends on A (failed)" in result.features[1].reason
    assert result.features[0].screenshot == "failures/A.png"
    assert not result.ok


def test_a_failed_step_stops_its_feature():
    suite = make_suite(feature("A", steps=3))
    executor = FakeExecutor(fail={"https://x/A/1"})
    result = run(suite, executor)
    assert executor.calls == ["https://x/A/0", "https://x/A/1"]
    assert [s.status for s in result.features[0].steps] == [Status.PASSED, Status.FAILED]
    assert result.features[0].reason.startswith("step 2 (goto https://x/A/1): boom")


def test_teardown_runs_right_after_a_failed_feature_and_keeps_its_reason():
    suite = make_suite(feature("A", steps=2, teardown=2), feature("B"))
    executor = FakeExecutor(fail={"https://x/A/0"})
    result = run(suite, executor)
    assert executor.calls == ["https://x/A/0", "https://x/A/teardown/0", "https://x/A/teardown/1", "https://x/B/0"]
    a = result.features[0]
    assert a.status is Status.FAILED and a.reason.startswith("step 1 (goto https://x/A/0): boom")
    assert [s.description for s in a.steps][1:] == ["teardown: goto https://x/A/teardown/0", "teardown: goto https://x/A/teardown/1"]
    assert [s.index for s in a.steps] == [1, 3, 4]


def test_failing_teardown_fails_a_passing_feature():
    suite = make_suite(feature("A", teardown=2))
    executor = FakeExecutor(fail={"https://x/A/teardown/0"})
    result = run(suite, executor)
    assert executor.calls == ["https://x/A/0", "https://x/A/teardown/0"]
    assert result.features[0].status is Status.FAILED
    assert result.features[0].reason.startswith("step 2 (teardown: goto https://x/A/teardown/0)")


def test_no_webgpu_blocks_instead_of_failing():
    suite = make_suite(feature("A"), feature("G", deps=["A"], webgpu=True), feature("H", deps=["G"]))
    result = run(suite, FakeExecutor(webgpu=False))
    assert statuses(result) == {"A": Status.PASSED, "G": Status.BLOCKED, "H": Status.SKIPPED}
    assert not result.ok


def test_cleanups_run_last_newest_first_even_after_failure():
    suite = make_suite(feature("A", cleanup=1), feature("B", deps=["A"], cleanup=2), feature("C"))
    executor = FakeExecutor(fail={"https://x/B/0"})
    result = run(suite, executor)
    assert executor.calls == [
        "https://x/A/0",
        "https://x/B/0",
        "https://x/C/0",
        "https://x/B/cleanup/0",
        "https://x/B/cleanup/1",
        "https://x/A/cleanup/0",
    ]
    assert all(entry.error is None for entry in result.cleanup)


def test_skipped_feature_registers_no_cleanup():
    suite = make_suite(feature("A"), feature("B", deps=["A"], cleanup=1))
    executor = FakeExecutor(fail={"https://x/A/0"})
    run(suite, executor)
    assert "https://x/B/cleanup/0" not in executor.calls


def test_a_failing_cleanup_stops_that_feature_cleanup_only():
    suite = make_suite(feature("A", cleanup=2), feature("B", cleanup=1))
    executor = FakeExecutor(fail={"https://x/B/cleanup/0"})
    result = run(suite, executor)
    assert executor.calls[-2:] == ["https://x/A/cleanup/0", "https://x/A/cleanup/1"]
    assert [entry.error is not None for entry in result.cleanup] == [True, False, False]


def test_fail_on_console_fails_a_passing_feature():
    suite = make_suite(feature("A"), feature("B"), fail_on_console=["panicked at"])
    executor = FakeExecutor(console={"A": ["[error] panicked at wgpu/src/backend.rs:1"], "B": ["[error] 404 favicon"]})
    result = run(suite, executor)
    assert statuses(result) == {"A": Status.FAILED, "B": Status.PASSED}
    assert "panicked at" in result.features[0].reason


def test_select_by_tag_pulls_dependencies():
    suite = make_suite(feature("A"), feature("B", deps=["A"], tags=["3d"]), feature("C", tags=["smoke"]))
    assert [f.id for f in select_features(suite, tags={"3d"})] == ["A", "B"]


def test_select_only_pulls_transitive_dependencies():
    suite = make_suite(feature("A"), feature("B", deps=["A"]), feature("C", deps=["B"]), feature("D"))
    assert [f.id for f in select_features(suite, only={"C"})] == ["A", "B", "C"]


def test_safe_only_drops_mutating_and_their_dependants_skip():
    suite = make_suite(feature("A"), feature("M", deps=["A"], mutating=True), feature("N", deps=["M"]))
    result = run(suite, FakeExecutor(), safe_only=True)
    assert statuses(result) == {"A": Status.PASSED, "N": Status.SKIPPED}
    assert "M (not run)" in result.features[1].reason


def test_unknown_only_id_is_an_error():
    with pytest.raises(ScenarioError, match="unknown feature"):
        select_features(make_suite(feature("A")), only={"Z"})
