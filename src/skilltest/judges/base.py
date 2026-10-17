"""The Judge interface used by `llm_judge` assertions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Verdict(BaseModel):
    passed: bool
    reason: str


class Judge(ABC):
    name: str
    vendor: str

    @abstractmethod
    async def grade(self, rubric: str, response: str) -> Verdict: ...


JUDGE_INSTRUCTIONS = """\
You are grading an AI agent's final answer against a rubric.
Be strict: the answer passes only if it clearly satisfies the rubric.
Reply with exactly one line: PASS or FAIL, then a colon and a one-sentence reason.

Rubric:
{rubric}

Agent's answer:
<answer>
{response}
</answer>
"""
