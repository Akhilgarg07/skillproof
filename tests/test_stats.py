from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skilltest.assertions import AssertionResult
from skilltest.results import CaseResult, SuiteResult, TrialResult
from skilltest.runners import AgentRun, Usage
from skilltest.stats import case_stats, suite_stats


def trial(
    variant, passed=True, tokens=100, duration=1.0, triggered=None, error=None, timed_out=False
):
    return TrialResult(
        case="c",
        variant=variant,
        trial=0,
        run=AgentRun(
            usage=Usage(output_tokens=tokens),
            duration_s=duration,
            triggered=triggered,
            error=error,
            timed_out=timed_out,
        ),
        assertions=[AssertionResult(type="contains", passed=passed, message="")],
    )


def test_case_stats() -> None:
    case = CaseResult(
        name="c",
        trials=[
            trial("with", True, tokens=80, duration=2.0, triggered=True),
            trial("with", True, tokens=80, duration=2.0, triggered=False),
            trial("with", False, error="boom"),  # excluded
            trial("without", False, tokens=100, duration=1.0),
            trial("without", True, tokens=100, duration=1.0),
        ],
    )
    stats = case_stats(case)
    assert stats.with_skill.runs == 2
    assert stats.with_skill.errors == 1
    assert stats.with_skill.pass_rate == 1.0
    assert stats.without_skill.pass_rate == 0.5
    assert stats.lift == pytest.approx(0.5)
    assert stats.with_skill.trigger_rate == 0.5
    assert stats.without_skill.trigger_rate is None  # runner couldn't tell
    assert stats.token_delta == pytest.approx(-0.2)
    assert stats.latency_delta == pytest.approx(1.0)


def test_timed_out_is_a_failure_not_an_error() -> None:
    case = CaseResult(name="c", trials=[trial("with", True, timed_out=True)])
    stats = case_stats(case).with_skill
    assert stats.runs == 1 and stats.passed == 0 and stats.errors == 0


def test_no_runs_gives_none() -> None:
    stats = case_stats(CaseResult(name="c", trials=[trial("with", error="x")]))
    assert stats.with_skill.pass_rate is None
    assert stats.lift is None
    assert stats.token_delta is None


def test_case_without_assertions_has_no_lift() -> None:
    case = CaseResult(name="c", has_assertions=False, trials=[trial("with"), trial("without")])
    assert case_stats(case).lift is None


def test_suite_stats_separates_false_triggers() -> None:
    positive = CaseResult(
        name="pos",
        trials=[trial("with", triggered=True), trial("with", triggered=False), trial("without")],
    )
    negative = CaseResult(
        name="neg", should_trigger=False, trials=[trial("with", triggered=True), trial("without")]
    )
    suite = SuiteResult(
        skill_name="s",
        skill_path="/s",
        runner="mock",
        run_dir="/tmp/x",
        started_at=datetime.now(timezone.utc),
        cases=[positive, negative],
    )
    stats = suite_stats(suite)
    assert (stats.triggers, stats.trigger_runs) == (1, 2)
    assert (stats.false_triggers, stats.false_trigger_runs) == (1, 1)
