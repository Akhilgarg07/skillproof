"""Base class for assertions.

An assertion is a pydantic model (so evals.yaml is validated for free) with an
async `check()` that looks at one finished run and returns an AssertionResult.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from skillproof.judges.base import Judge
from skillproof.runners.base import AgentRun


@dataclass
class CheckContext:
    run: AgentRun
    workdir: Path  # the sandbox the agent worked in
    judge: Judge | None = None


class AssertionResult(BaseModel):
    type: str
    passed: bool
    message: str


class BaseAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str

    def describe(self) -> str:
        """Short human label, e.g. `contains "NullPointerException"`."""
        return self.type

    async def check(self, ctx: CheckContext) -> AssertionResult:
        raise NotImplementedError

    def result(self, passed: bool, message: str) -> AssertionResult:
        return AssertionResult(type=self.type, passed=passed, message=message)
