"""Turning trial results into numbers: pass rate, lift, trigger rate, deltas.

Conventions:
  * Errored runs (infrastructure failures) are excluded from every rate.
  * Timed-out runs count as failures (the agent didn't finish).
  * Rates are fractions in [0, 1]; lift is a difference of fractions
    (+0.23 means "23 percentage points better with the skill").
  * Token and latency deltas are relative: +0.10 means 10% more with the skill.
"""

from __future__ import annotations

from dataclasses import dataclass

from skilltest.results import CaseResult, SuiteResult, TrialResult


@dataclass
class VariantStats:
    runs: int  # completed runs (errors excluded)
    errors: int
    passed: int
    triggered: int
    trigger_known: int  # runs where the runner could tell whether the skill fired
    mean_tokens: float | None
    mean_duration_s: float | None

    @property
    def pass_rate(self) -> float | None:
        return self.passed / self.runs if self.runs else None

    @property
    def trigger_rate(self) -> float | None:
        return self.triggered / self.trigger_known if self.trigger_known else None


@dataclass
class CaseStats:
    name: str
    should_trigger: bool
    has_assertions: bool
    with_skill: VariantStats
    without_skill: VariantStats

    @property
    def lift(self) -> float | None:
        if not self.has_assertions:
            return None
        return _diff(self.with_skill.pass_rate, self.without_skill.pass_rate)

    @property
    def token_delta(self) -> float | None:
        return _relative(self.with_skill.mean_tokens, self.without_skill.mean_tokens)

    @property
    def latency_delta(self) -> float | None:
        return _relative(self.with_skill.mean_duration_s, self.without_skill.mean_duration_s)


@dataclass
class SuiteStats:
    cases: list[CaseStats]
    with_skill: VariantStats  # pooled over cases that have assertions
    without_skill: VariantStats
    triggers: int  # skill fired, in with-skill runs of should_trigger cases
    trigger_runs: int
    false_triggers: int  # skill fired, in with-skill runs of should_trigger: false cases
    false_trigger_runs: int
    errors: int

    @property
    def lift(self) -> float | None:
        return _diff(self.with_skill.pass_rate, self.without_skill.pass_rate)

    @property
    def token_delta(self) -> float | None:
        return _relative(self.with_skill.mean_tokens, self.without_skill.mean_tokens)

    @property
    def latency_delta(self) -> float | None:
        return _relative(self.with_skill.mean_duration_s, self.without_skill.mean_duration_s)


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
    return VariantStats(
        runs=len(done),
        errors=len(trials) - len(done),
        passed=sum(t.passed for t in done),
        triggered=sum(bool(t.run.triggered) for t in known),
        trigger_known=len(known),
        mean_tokens=_mean([t.run.usage.total_tokens for t in done]),
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
