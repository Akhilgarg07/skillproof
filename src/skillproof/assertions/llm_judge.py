"""The optional LLM-graded assertion. Non-deterministic: use deterministic ones first."""

from __future__ import annotations

from typing import Literal

from skillproof.assertions.base import AssertionResult, BaseAssertion, CheckContext


class LLMJudge(BaseAssertion):
    """A judge model decides whether the final answer satisfies `rubric`."""

    type: Literal["llm_judge"]
    rubric: str

    def describe(self) -> str:
        rubric = self.rubric if len(self.rubric) <= 40 else self.rubric[:39] + "…"
        return f'llm_judge "{rubric}"'

    async def check(self, ctx: CheckContext) -> AssertionResult:
        if ctx.judge is None:
            return self.result(False, "no judge configured")
        verdict = await ctx.judge.grade(self.rubric, ctx.run.final_text)
        return self.result(verdict.passed, f"judge ({ctx.judge.name}): {verdict.reason}")
