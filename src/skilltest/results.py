"""Result models. These are what gets saved to results.json and fed to reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from skilltest.assertions import AssertionResult
from skilltest.runners.base import AgentRun

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
    cases: list[CaseResult] = Field(default_factory=list)
