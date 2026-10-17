"""OpenAI-compatible endpoint runner. Implemented in phase 2.

This runner can't load skills the way a real agent does; it injects SKILL.md
into the system prompt, so its results are labeled approximate.
"""

from __future__ import annotations

from skilltest.errors import RunnerNotReady
from skilltest.runners.base import AgentRun, Runner, RunRequest


class OpenAICompatibleRunner(Runner):
    name = "openai-compatible"
    vendor = "openai"
    approximate = True

    def check_ready(self) -> None:
        raise RunnerNotReady(
            "The openai-compatible runner is not implemented yet.",
            hint="Use `runner: mock` for now; real runners land in phase 2.",
        )

    async def run(self, request: RunRequest) -> AgentRun:
        raise NotImplementedError
