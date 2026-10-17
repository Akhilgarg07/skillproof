"""Rough cost estimate before a run starts, so nobody burns $50 by accident.

Per-run cost comes from your last run of the same skill with the same runner
when there is one (agents like Claude Code report cost per run). Otherwise a
deliberately rough default per runner is used; tasks vary 10x in cost, so the
first estimate is a ballpark, and later ones learn from your real runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skillproof.engine import Engine
from skillproof.results import RESULTS_FILE, SuiteResult

# USD per agent run when there's no history: ballpark for a small coding task
# (our example skills averaged ~$0.05 per Claude Code run on claude-opus-5-5).
DEFAULT_COST_PER_RUN = {
    "claude-code": 0.10,
    "codex": 0.15,
    "openai-compatible": 0.02,
    "mock": 0.0,
}
# Ask before spending more than this (override with --confirm-above).
CONFIRM_ABOVE_USD = 5.0


@dataclass
class Estimate:
    runs: int
    judge_calls: int
    cost_per_run: float | None  # None: unknown runner and no history
    source: str  # where cost_per_run came from, shown to the user

    @property
    def total_usd(self) -> float | None:
        return None if self.cost_per_run is None else self.runs * self.cost_per_run

    def describe(self) -> str:
        text = f"{self.runs} agent runs"
        if self.judge_calls:
            text += f" + {self.judge_calls} judge calls"
        if self.total_usd is None:
            return text + " · cost unknown"
        if self.total_usd == 0:
            return text + " · no API cost"
        return (
            f"{text} · estimated ~${self.total_usd:.2f} "
            f"(${self.cost_per_run:.3f}/run, {self.source})"
        )


def past_cost_per_run(out_dir: Path, skill_path: Path, runner: str) -> float | None:
    """Mean reported cost per run in the newest saved run of this skill and runner."""
    for results in sorted((out_dir / "runs").glob(f"*/{RESULTS_FILE}"), reverse=True):
        try:
            suite = SuiteResult.model_validate_json(results.read_text(encoding="utf-8"))
        except ValueError:
            continue  # unreadable or from an incompatible version
        if Path(suite.skill_path) != skill_path or suite.runner != runner:
            continue
        costs = [
            t.run.usage.cost_usd
            for c in suite.cases
            for t in c.trials
            if t.run.usage.cost_usd is not None
        ]
        if costs:
            return sum(costs) / len(costs)
    return None


def estimate(engine: Engine, out_dir: Path) -> Estimate:
    jobs = engine.jobs()
    judge_calls = sum(sum(a.type == "llm_judge" for a in job.case.assertions) for job in jobs)
    runner = engine.runner.name
    past = past_cost_per_run(out_dir, engine.config.skill, runner)
    if past is not None:
        return Estimate(len(jobs), judge_calls, past, "from your last run")
    default = DEFAULT_COST_PER_RUN.get(runner)
    source = f"rough default for {runner}" if default else "no estimate for this runner"
    return Estimate(len(jobs), judge_calls, default, source)
