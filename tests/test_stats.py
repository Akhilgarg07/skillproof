from __future__ import annotations

from datetime import datetime, timezone

import pytest

from skillproof.assertions import AssertionResult
from skillproof.results import CaseResult, SuiteResult, TrialResult
from skillproof.runners import AgentRun, Usage
from skillproof.stats import (
    case_stats,
    lift_interval,
    suite_stats,
    variant_stats,
    verdict,
    wilson_interval,
)


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


def test_wilson_interval_known_values() -> None:
    assert wilson_interval(0, 0) is None
    low, high = wilson_interval(0, 5)
    assert low == 0 and high == pytest.approx(0.4345, abs=1e-3)
    low, high = wilson_interval(5, 5)
    assert low == pytest.approx(0.5655, abs=1e-3) and high == 1
    low, high = wilson_interval(50, 100)
    assert (low, high) == (pytest.approx(0.4038, abs=1e-3), pytest.approx(0.5962, abs=1e-3))


def counts(passed: int, runs: int, variant: str = "with") -> list[TrialResult]:
    return [trial(variant, i < passed) for i in range(runs)]


def test_lift_interval_matches_newcombe_example() -> None:
    # Newcombe (1998), method 10: 56/70 vs 48/80 -> difference 0.2, CI 0.0524 to 0.3339
    low, high = lift_interval(variant_stats(counts(56, 70)), variant_stats(counts(48, 80)))
    assert low == pytest.approx(0.0524, abs=1e-3)
    assert high == pytest.approx(0.3339, abs=1e-3)


@pytest.mark.parametrize(
    ("lift", "ci", "runs", "expected"),
    [
        (0.3, (0.05, 0.5), 10, "helps"),
        (-0.3, (-0.5, -0.05), 10, "hurts"),
        (0.2, (-0.1, 0.5), 10, "no clear effect"),
        (1.0, (0.07, 1.0), 2, "too few runs"),  # 2/2 vs 0/2: "significant", but not quotable
        (None, None, 10, "not measured"),
    ],
)
def test_verdict(lift, ci, runs, expected) -> None:
    assert verdict(lift, ci, runs) == expected


def test_cost_delta_needs_every_run_to_report_cost() -> None:
    def priced(variant: str, cost: float | None) -> TrialResult:
        t = trial(variant)
        t.run.usage.cost_usd = cost
        return t

    full = CaseResult(name="c", trials=[priced("with", 0.2), priced("without", 0.1)])
    assert case_stats(full).cost_delta == pytest.approx(1.0)
    partial = CaseResult(name="c", trials=[priced("with", 0.2), priced("without", None)])
    assert case_stats(partial).cost_delta is None


def suite_of(*cases: CaseResult) -> SuiteResult:
    return SuiteResult(
        skill_name="s",
        skill_path="/s",
        runner="mock",
        run_dir="/tmp/x",
        started_at=datetime.now(timezone.utc),
        cases=list(cases),
    )


def test_headline_lift_ignores_negative_cases() -> None:
    positive = CaseResult(name="pos", trials=counts(4, 4) + counts(0, 4, "without"))
    negative = CaseResult(
        name="neg", should_trigger=False, trials=counts(4, 4) + counts(4, 4, "without")
    )
    stats = suite_stats(suite_of(positive, negative))
    assert stats.lift == pytest.approx(1.0)  # not diluted to 0.5 by the negative case
    assert stats.min_runs == 4
