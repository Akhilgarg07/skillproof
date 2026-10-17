"""Codex CLI runner (non-interactive mode). Implemented in phase 2."""

from __future__ import annotations

from skilltest.errors import RunnerNotReady
from skilltest.runners.base import AgentRun, Runner, RunRequest


class CodexRunner(Runner):
    name = "codex"
    vendor = "openai"

    def check_ready(self) -> None:
        raise RunnerNotReady(
            "The codex runner is not implemented yet.",
            hint="Use `runner: mock` for now; real runners land in phase 2.",
        )

    async def run(self, request: RunRequest) -> AgentRun:
        raise NotImplementedError
