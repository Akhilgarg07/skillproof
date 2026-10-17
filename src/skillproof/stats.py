"""Turning trial results into numbers: pass rate, lift, trigger rate, deltas.

Conventions:
  * Errored runs (infrastructure failures) are excluded from every rate.
  * Timed-out runs count as failures (the agent didn't finish).
  * Rates are fractions in [0, 1]; lift is a difference of fractions
    (+0.23 means "23 percentage points better with the skill").
  * Token, cost and latency deltas are relative: +0.10 means 10% more with the skill.
  * Intervals are 95%: Wilson score intervals for pass rates and Newcombe's
    method (built from the two Wilson intervals) for the lift. Both behave
    sensibly at small n and at 0% / 100%, unlike the textbook normal formula.
  * The headline (suite-level) lift pools every graded trial of the cases where
    the skill should trigger, treating trials as independent. Negative cases
    (`should_trigger: false`) only check that the skill does no harm, so they
    are reported per case, not mixed into the headline. Cases with very
    different difficulty make pooling approximate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from skillproof.results import CaseResult, SuiteResult, TrialResult

Z_95 = 1.959964
# Below this many completed runs per variant, results get a "small sample" note.
MIN_RUNS_FOR_CONFIDENCE = 10
# Below this many completed runs per variant, no helps/hurts verdict is given at all:
# with 2/2 vs 0/2 the interval already excludes zero, but nobody should quote that.
MIN_RUNS_FOR_VERDICT = 5

Interval = tuple[float, float]
Verdict = Literal["helps", "hurts", "no clear effect", "too few runs", "not measured"]


def wilson_interval(successes: int, n: int, z: float = Z_95) -> Interval | None:
    """95% Wilson score interval for a pass rate."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def lift_interval(with_: VariantStats, without: VariantStats) -> Interval | None:
    """95% interval for (pass rate with) - (pass rate without), Newcombe's hybrid score method."""
    p1, p2 = with_.pass_rate, without.pass_rate
    ci1, ci2 = with_.pass_interval, without.pass_interval
    if p1 is None or p2 is None or ci1 is None or ci2 is None:
        return None
    (l1, u1), (l2, u2) = ci1, ci2
    diff = p1 - p2
    low = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return low, high


def verdict(lift: float | None, interval: Interval | None, runs: int) -> Verdict:
    """`runs` is the smaller number of completed runs of the two variants."""
    if lift is None or interval is None:
        return "not measured"
    if runs < MIN_RUNS_FOR_VERDICT:
        return "too few runs"
    if interval[0] > 0:
        return "helps"
    if interval[1] < 0:
        return "hurts"
    return "no clear effect"


@dataclass
class VariantStats:
    runs: int  # completed runs (errors excluded)
    errors: int
    passed: int
    triggered: int
    trigger_known: int  # runs where the runner could tell whether the skill fired
    mean_tokens: float | None
    mean_cost_usd: float | None  # None unless every completed run reported a cost
    mean_duration_s: float | None

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.runs if self.runs else None

    @property
    def pass_interval(self) -> Interval | None:
        return wilson_interval(self.passed, self.runs)

    @property
    def trigger_rate(self) -> float | None:
        return self.triggered / self.trigger_known if self.trigger_known else None


class _Deltas:
    """Lift and relative deltas shared by case- and suite-level stats."""

    with_skill: VariantStats
    without_skill: VariantStats

    @property
    def graded(self) -> bool:
        return True

    @property
    def lift(self) -> float | None:
        if not self.graded:
            return None
        return _diff(self.with_skill.pass_rate, self.without_skill.pass_rate)

    @property
    def lift_interval(self) -> Interval | None:
        if not self.graded:
            return None
        return lift_interval(self.with_skill, self.without_skill)

    @property
    def verdict(self) -> Verdict:
        runs = min(self.with_skill.runs, self.without_skill.runs)
        return verdict(self.lift, self.lift_interval, runs)

    @property
    def token_delta(self) -> float | None:
        return _relative(self.with_skill.mean_tokens, self.without_skill.mean_tokens)

    @property
    def cost_delta(self) -> float | None:
        return _relative(self.with_skill.mean_cost_usd, self.without_skill.mean_cost_usd)

    @property
    def latency_delta(self) -> float | None:
        return _relative(self.with_skill.mean_duration_s, self.without_skill.mean_duration_s)


@dataclass
class CaseStats(_Deltas):
    name: str
    should_trigger: bool
    has_assertions: bool
    with_skill: VariantStats
    without_skill: VariantStats

    @property
    def graded(self) -> bool:
        return self.has_assertions


@dataclass
class SuiteStats(_Deltas):
    cases: list[CaseStats]
    with_skill: VariantStats  # pooled over graded should_trigger cases
    without_skill: VariantStats
    triggers: int  # skill fired, in with-skill runs of should_trigger cases
    trigger_runs: int
    false_triggers: int  # skill fired, in with-skill runs of should_trigger: false cases
    false_trigger_runs: int
    errors: int

    @property
    def min_runs(self) -> int:
        """Fewest completed runs in any graded variant: the weakest link for confidence."""
        counts = [
            v.runs for c in self.cases if c.has_assertions for v in (c.with_skill, c.without_skill)
        ]
        return min(counts) if counts else 0


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _relative(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b - 1


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def variant_stats(trials: list[TrialResult]) -> VariantStats:
    done = [t for t in trials if not t.errored]
    known = [t for t in done if t.run.triggered is not None]
    costs = [t.run.usage.cost_usd for t in done]
    return VariantStats(
        runs=len(done),
        errors=len(trials) - len(done),
        passed=sum(t.passed for t in done),
        triggered=sum(bool(t.run.triggered) for t in known),
        trigger_known=len(known),
        mean_tokens=_mean([t.run.usage.total_tokens for t in done]),
        mean_cost_usd=None if None in costs else _mean([c for c in costs if c is not None]),
        mean_duration_s=_mean([t.run.duration_s for t in done]),
    )


def case_stats(case: CaseResult) -> CaseStats:
    return CaseStats(
        name=case.name,
        should_trigger=case.should_trigger,
        has_assertions=case.has_assertions,
        with_skill=variant_stats(case.variant("with")),
        without_skill=variant_stats(case.variant("without")),
    )


def suite_stats(suite: SuiteResult) -> SuiteStats:
    cases = [case_stats(c) for c in suite.cases]
    graded = [c for c in suite.cases if c.has_assertions and c.should_trigger]
    if not graded:  # only negative cases: fall back to pooling everything graded
        graded = [c for c in suite.cases if c.has_assertions]
    positive = [s.with_skill for s in cases if s.should_trigger]
    negative = [s.with_skill for s in cases if not s.should_trigger]
    return SuiteStats(
        cases=cases,
        with_skill=variant_stats([t for c in graded for t in c.variant("with")]),
        without_skill=variant_stats([t for c in graded for t in c.variant("without")]),
        triggers=sum(v.triggered for v in positive),
        trigger_runs=sum(v.trigger_known for v in positive),
        false_triggers=sum(v.triggered for v in negative),
        false_trigger_runs=sum(v.trigger_known for v in negative),
        errors=sum(s.with_skill.errors + s.without_skill.errors for s in cases),
    )
