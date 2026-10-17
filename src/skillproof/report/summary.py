"""The report summary: every number a report shows, computed once.

All renderers (terminal, markdown, HTML, JSON, badge) read a `Summary`, so they
can never disagree. `summary.json` is also the machine-readable contract for CI:
add fields freely, but don't rename or remove them without bumping
SCHEMA_VERSION.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from skillproof import __version__
from skillproof.report.format import signed_pct
from skillproof.results import SuiteResult
from skillproof.stats import (
    MIN_RUNS_FOR_CONFIDENCE,
    CaseStats,
    SuiteStats,
    VariantStats,
    Verdict,
    suite_stats,
)

SCHEMA_VERSION = 1


class VariantSummary(BaseModel):
    runs: int
    errors: int
    passed: int
    pass_rate: float | None
    pass_ci: tuple[float, float] | None
    triggered: int
    trigger_known: int
    trigger_rate: float | None
    mean_tokens: float | None
    mean_cost_usd: float | None
    mean_duration_s: float | None


class CaseSummary(BaseModel):
    name: str
    should_trigger: bool
    has_assertions: bool
    with_skill: VariantSummary
    without_skill: VariantSummary
    lift: float | None
    lift_ci: tuple[float, float] | None
    verdict: Verdict
    token_delta: float | None
    cost_delta: float | None
    latency_delta: float | None


class Summary(BaseModel):
    schema_version: int = SCHEMA_VERSION
    skillproof_version: str = __version__
    skill_name: str
    skill_path: str
    runner: str
    approximate: bool
    model: str | None
    judge: str | None
    started_at: datetime
    finished_at: datetime | None
    run_dir: str

    verdict: Verdict
    lift: float | None
    lift_ci: tuple[float, float] | None
    with_skill: VariantSummary
    without_skill: VariantSummary
    triggers: int
    trigger_runs: int
    false_triggers: int
    false_trigger_runs: int
    token_delta: float | None
    cost_delta: float | None
    latency_delta: float | None
    errors: int
    notes: list[str]
    warnings: list[str]
    cases: list[CaseSummary]

    @property
    def trigger_rate(self) -> float | None:
        return self.triggers / self.trigger_runs if self.trigger_runs else None


def variant_summary(v: VariantStats) -> VariantSummary:
    return VariantSummary(
        runs=v.runs,
        errors=v.errors,
        passed=v.passed,
        pass_rate=v.pass_rate,
        pass_ci=v.pass_interval,
        triggered=v.triggered,
        trigger_known=v.trigger_known,
        trigger_rate=v.trigger_rate,
        mean_tokens=v.mean_tokens,
        mean_cost_usd=v.mean_cost_usd,
        mean_duration_s=v.mean_duration_s,
    )


def case_summary(c: CaseStats) -> CaseSummary:
    return CaseSummary(
        name=c.name,
        should_trigger=c.should_trigger,
        has_assertions=c.has_assertions,
        with_skill=variant_summary(c.with_skill),
        without_skill=variant_summary(c.without_skill),
        lift=c.lift,
        lift_ci=c.lift_interval,
        verdict=c.verdict,
        token_delta=c.token_delta,
        cost_delta=c.cost_delta,
        latency_delta=c.latency_delta,
    )


def notes_for(suite: SuiteResult, stats: SuiteStats) -> list[str]:
    """Plain-English caveats. These matter as much as the numbers."""
    notes = []
    if suite.approximate:
        notes.append(
            "Approximate: this runner pastes SKILL.md into the system prompt instead of "
            "letting the agent discover and load it, so trigger rates are not measured."
        )
    if stats.trigger_runs and stats.triggers == 0:
        notes.append(
            "The skill never triggered, so any difference in pass rate is noise "
            "(or comes from the skill merely being listed). Improve the `description`."
        )
    elif stats.trigger_runs and stats.triggers < stats.trigger_runs:
        missed = stats.trigger_runs - stats.triggers
        notes.append(
            f"The skill did not trigger in {missed} of {stats.trigger_runs} runs where it should "
            "have. Those runs count against the lift."
        )
    for case in stats.cases:
        if not case.should_trigger and case.verdict == "hurts":
            notes.append(
                f"The skill makes the unrelated case {case.name!r} worse "
                f"({signed_pct(case.lift)}): it interferes with tasks it shouldn't touch."
            )
    if stats.false_triggers:
        notes.append(
            f"The skill triggered in {stats.false_triggers} of {stats.false_trigger_runs} runs "
            "where it should not have (should_trigger: false)."
        )
    interval = stats.lift_interval
    if interval is not None:
        low, high = interval
        if stats.verdict == "no clear effect":
            notes.append(
                f"The lift is not statistically clear: the 95% interval ({signed_pct(low)} to "
                f"{signed_pct(high)}) includes zero."
            )
    elif stats.lift is None:
        notes.append("No graded runs: add `assert:` checks to measure pass rates and lift.")
    if 0 < stats.min_runs < MIN_RUNS_FOR_CONFIDENCE:
        notes.append(
            f"Small sample: as few as {stats.min_runs} completed run(s) per variant. Treat these "
            f"numbers as rough; use --trials {MIN_RUNS_FOR_CONFIDENCE} or more before quoting them."
        )
    timeouts = sum(t.run.timed_out for c in suite.cases for t in c.trials)
    if timeouts:
        notes.append(
            f"{timeouts} run(s) hit the time limit and count as failures. If the task needs "
            "longer, raise `timeout:` in evals.yaml."
        )
    if not suite.complete:
        notes.append("This run was interrupted or stopped early: results are partial.")
    if stats.errors:
        notes.append(
            f"{stats.errors} run(s) errored (API, CLI or judge failures) and were excluded. "
            "See the saved transcripts."
        )
    return notes


def build_summary(suite: SuiteResult) -> Summary:
    stats = suite_stats(suite)
    models = sorted({t.run.model for c in suite.cases for t in c.trials if t.run.model})
    warnings = sorted({w for c in suite.cases for t in c.trials for w in t.run.warnings})
    return Summary(
        skill_name=suite.skill_name,
        skill_path=suite.skill_path,
        runner=suite.runner,
        approximate=suite.approximate,
        model=suite.model or (", ".join(models) or None),
        judge=suite.judge,
        started_at=suite.started_at,
        finished_at=suite.finished_at,
        run_dir=suite.run_dir,
        verdict=stats.verdict,
        lift=stats.lift,
        lift_ci=stats.lift_interval,
        with_skill=variant_summary(stats.with_skill),
        without_skill=variant_summary(stats.without_skill),
        triggers=stats.triggers,
        trigger_runs=stats.trigger_runs,
        false_triggers=stats.false_triggers,
        false_trigger_runs=stats.false_trigger_runs,
        token_delta=stats.token_delta,
        cost_delta=stats.cost_delta,
        latency_delta=stats.latency_delta,
        errors=stats.errors,
        notes=notes_for(suite, stats),
        warnings=warnings,
        cases=[case_summary(c) for c in stats.cases],
    )
