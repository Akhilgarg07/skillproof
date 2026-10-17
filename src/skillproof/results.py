"""Result models. These are what gets saved to results.json and fed to reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from skillproof.assertions import AssertionResult
from skillproof.errors import SkillproofError
from skillproof.runners.base import AgentRun

Variant = Literal["with", "without"]


class TrialResult(BaseModel):
    case: str
    variant: Variant
    trial: int  # 0-based
    run: AgentRun
    assertions: list[AssertionResult] = Field(default_factory=list)
    artifact: str | None = None  # path of the saved transcript, relative to the run dir

    @property
    def errored(self) -> bool:
        """Infrastructure failure: excluded from pass rates, reported separately."""
        return self.run.error is not None

    @property
    def passed(self) -> bool:
        return (
            not self.errored and not self.run.timed_out and all(a.passed for a in self.assertions)
        )


class CaseResult(BaseModel):
    name: str
    should_trigger: bool = True
    has_assertions: bool = True
    trials: list[TrialResult] = Field(default_factory=list)

    def variant(self, variant: Variant) -> list[TrialResult]:
        return [t for t in self.trials if t.variant == variant]


class SuiteResult(BaseModel):
    skill_name: str
    skill_path: str
    runner: str
    approximate: bool = False  # the runner only simulates skill loading
    model: str | None = None
    judge: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    run_dir: str
    complete: bool = True  # False when the run was interrupted or stopped early
    cases: list[CaseResult] = Field(default_factory=list)


RESULTS_FILE = "results.json"


def load_suite(path: Path) -> SuiteResult:
    """Load a saved run from its results.json or its run directory."""
    file = path / RESULTS_FILE if path.is_dir() else path
    if not file.is_file():
        raise SkillproofError(
            f"No {RESULTS_FILE} at {path}",
            hint="Pass a run directory like .skillproof/runs/20261017-120000.",
        )
    return SuiteResult.model_validate_json(file.read_text(encoding="utf-8"))


def find_latest_run(out_dir: Path, skill_path: Path | None = None) -> Path:
    """The newest run directory under <out_dir>/runs, optionally for one skill."""
    runs = sorted((out_dir / "runs").glob(f"*/{RESULTS_FILE}"), reverse=True)
    for results in runs:
        if skill_path is None:
            return results.parent
        if Path(load_suite(results).skill_path) == skill_path.resolve():
            return results.parent
    where = f" for {skill_path}" if skill_path else ""
    raise SkillproofError(
        f"No skillproof runs found in {out_dir / 'runs'}{where}.",
        hint="Run `skillproof run <skill>` first, or pass --out if you saved runs elsewhere.",
    )
