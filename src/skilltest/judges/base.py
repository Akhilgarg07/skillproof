"""The Judge interface used by `llm_judge` assertions."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from pydantic import BaseModel


class Verdict(BaseModel):
    passed: bool
    reason: str


class JudgeUnavailable(Exception):
    """The judge itself failed (API error, refusal). The run is marked errored,
    not failed, so judge outages don't skew pass rates."""


class Judge(ABC):
    name: str
    vendor: str
    model: str | None = None

    @abstractmethod
    async def grade(self, rubric: str, response: str) -> Verdict: ...

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}" if self.model else self.name


JUDGE_PROMPT = """\
You are grading an AI agent's final answer against a rubric.
Be strict: the answer passes only if it clearly satisfies the rubric.
Judge only what is in the answer; do not give credit for intent.

<rubric>
{rubric}
</rubric>

<answer>
{response}
</answer>

Respond with JSON: {{"passed": true or false, "reason": "<one sentence>"}}
"""

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["passed", "reason"],
    "additionalProperties": False,
}


def judge_prompt(rubric: str, response: str) -> str:
    return JUDGE_PROMPT.format(rubric=rubric.strip(), response=response.strip() or "(empty)")


def parse_verdict(text: str) -> Verdict:
    try:
        return Verdict.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise JudgeUnavailable(f"judge returned an unreadable verdict: {text[:200]!r}") from exc
