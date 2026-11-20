"""Running a suite: which features run, in what order, with which outcome.

The runner knows nothing about browsers: it drives an ``Executor``, so its rules (dependencies,
filters, cleanup, blocked versus failed) are tested without one.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from horizon_analyzer.loader import Context, ScenarioError
from horizon_analyzer.schema import Feature, Step, Suite


class Status(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class StepFailure(Exception):
    """A step did not do what the scenario expects. The message is meant for the report."""


class Executor(Protocol):
    """What the runner needs from a browser session."""

    def start_feature(self, feature: Feature) -> None:
        """Called before a feature's first step, e.g. to reset per-feature console logs."""

    def run_step(self, step: Step, feature: Feature) -> list[str]:
        """Perform one step; return the paths of files it produced. Raise ``StepFailure`` if it fails."""

    def webgpu_available(self) -> bool:
        """Whether the browser exposes a WebGPU adapter."""

    def capture_failure(self, feature: Feature) -> str | None:
        """Save what the page looks like right now; return the file path, if any."""

    def console_errors(self) -> list[str]:
        """Console errors seen since the current feature started."""


@dataclass
class StepResult:
    index: int
    description: str
    status: Status
    duration: float
    error: str | None = None
    attachments: list[str] = field(default_factory=list)


@dataclass
class FeatureResult:
    id: str
    name: str
    tags: list[str]
    status: Status
    duration: float = 0.0
    reason: str | None = None
    steps: list[StepResult] = field(default_factory=list)
    screenshot: str | None = None
    console_errors: list[str] = field(default_factory=list)


@dataclass
class CleanupResult:
    feature_id: str
    description: str
    error: str | None


@dataclass
class RunResult:
    suite: str
    run_id: str
    started_at: str
    duration: float = 0.0
    features: list[FeatureResult] = field(default_factory=list)
    cleanup: list[CleanupResult] = field(default_factory=list)
    browser: str = ""

    def count(self, status: Status) -> int:
        return sum(1 for feature in self.features if feature.status is status)

    @property
    def ok(self) -> bool:
        return self.count(Status.FAILED) == 0 and self.count(Status.BLOCKED) == 0


def select_features(
    suite: Suite,
    *,
    tags: set[str] | None = None,
    only: set[str] | None = None,
    safe_only: bool = False,
) -> list[Feature]:
    """The features to run, in file order.

    ``tags`` keeps features carrying any of them, ``only`` keeps the named ones; both pull in
    the features they depend on, so a selected feature always gets its preconditions.
    ``safe_only`` then drops mutating features (their dependants will be skipped).
    """
    if only:
        unknown = only - {feature.id for feature in suite.features}
        if unknown:
            raise ScenarioError(f"unknown feature id(s): {', '.join(sorted(unknown))}")
    wanted = {
        feature.id
        for feature in suite.features
        if (not tags or tags & set(feature.tags)) and (not only or feature.id in only)
    }
    for feature in reversed(suite.features):
        if feature.id in wanted:
            wanted.update(feature.depends_on)
    return [
        feature
        for feature in suite.features
        if feature.id in wanted and not (safe_only and feature.mutating)
    ]


def run_suite(
    suite: Suite,
    features: list[Feature],
    executor: Executor,
    context: Context,
    *,
    browser: str = "",
) -> RunResult:
    """Run ``features`` in order, then every registered cleanup, newest first."""
    result = RunResult(suite=suite.suite, run_id=context.run_id, started_at=datetime.now().isoformat(timespec="seconds"), browser=browser)
    started = time.monotonic()
    outcomes: dict[str, Status] = {}
    cleanups: list[Feature] = []

    for feature in features:
        feature_result = _run_feature(feature, executor, context, outcomes, cleanups)
        outcomes[feature.id] = feature_result.status
        result.features.append(feature_result)

    for feature in reversed(cleanups):
        for step in feature.cleanup:
            description = context.mask(_describe(step, context))
            try:
                executor.run_step(step, feature)
                result.cleanup.append(CleanupResult(feature.id, description, None))
            except (StepFailure, ScenarioError) as error:
                result.cleanup.append(CleanupResult(feature.id, description, context.mask(str(error))))
                break

    result.duration = round(time.monotonic() - started, 2)
    return result


def _run_feature(
    feature: Feature,
    executor: Executor,
    context: Context,
    outcomes: dict[str, Status],
    cleanups: list[Feature],
) -> FeatureResult:
    result = FeatureResult(id=feature.id, name=feature.name, tags=list(feature.tags), status=Status.PASSED)

    not_passed = [dependency for dependency in feature.depends_on if outcomes.get(dependency) is not Status.PASSED]
    if not_passed:
        result.status = Status.SKIPPED
        result.reason = "; ".join(
            f"depends on {dependency} ({outcomes[dependency].value if dependency in outcomes else 'not run'})"
            for dependency in not_passed
        )
        return result

    if feature.requires_webgpu and not executor.webgpu_available():
        result.status = Status.BLOCKED
        result.reason = "no WebGPU adapter in this browser (run headed on a machine with a GPU)"
        return result

    if feature.cleanup:
        cleanups.append(feature)
    executor.start_feature(feature)
    started = time.monotonic()
    for index, step in enumerate(feature.steps, start=1):
        description = context.mask(_describe(step, context))
        step_started = time.monotonic()
        try:
            attachments = executor.run_step(step, feature)
        except (StepFailure, ScenarioError) as error:
            message = context.mask(str(error))
            result.steps.append(StepResult(index, description, Status.FAILED, _since(step_started), message))
            result.status = Status.FAILED
            result.reason = f"step {index} ({description}): {message.splitlines()[0]}"
            result.screenshot = executor.capture_failure(feature)
            break
        result.steps.append(StepResult(index, description, Status.PASSED, _since(step_started), attachments=attachments))
    _run_teardown(feature, executor, context, result)
    result.duration = _since(started)
    result.console_errors = [context.mask(line) for line in executor.console_errors()]
    if result.status is Status.PASSED:
        fatal = _first_fatal(result.console_errors, context.suite.fail_on_console)
        if fatal is not None:
            result.status = Status.FAILED
            result.reason = f"console error during the feature: {fatal.splitlines()[0][:300]}"
            result.screenshot = executor.capture_failure(feature)
    return result


def _run_teardown(feature: Feature, executor: Executor, context: Context, result: FeatureResult) -> None:
    """Run the feature's teardown steps, listed after its steps; stop at the first that fails.

    A feature that already failed keeps its reason and screenshot (they show the real problem);
    a teardown failure only fails a feature that had passed.
    """
    for offset, step in enumerate(feature.teardown, start=1):
        index = len(feature.steps) + offset
        description = "teardown: " + context.mask(_describe(step, context))
        step_started = time.monotonic()
        try:
            attachments = executor.run_step(step, feature)
        except (StepFailure, ScenarioError) as error:
            message = context.mask(str(error))
            result.steps.append(StepResult(index, description, Status.FAILED, _since(step_started), message))
            if result.status is Status.PASSED:
                result.status = Status.FAILED
                result.reason = f"step {index} ({description}): {message.splitlines()[0]}"
                result.screenshot = executor.capture_failure(feature)
            return
        result.steps.append(StepResult(index, description, Status.PASSED, _since(step_started), attachments=attachments))


def _first_fatal(lines: list[str], patterns: list[str]) -> str | None:
    compiled = [re.compile(pattern) for pattern in patterns]
    return next((line for line in lines if any(pattern.search(line) for pattern in compiled)), None)


def _describe(step: Step, context: Context) -> str:
    """The step's description with variables resolved where possible (secrets get masked later)."""
    text = step.describe()
    try:
        return context.render(text)
    except ScenarioError:
        return text


def _since(started: float) -> float:
    return round(time.monotonic() - started, 2)
