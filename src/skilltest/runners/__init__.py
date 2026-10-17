"""Runner registry.

To add a runner: write a `Runner` subclass in this package and add one line to
`RUNNERS` below. Runners are imported lazily so that an optional SDK for one
agent is never required to use another.
"""

from __future__ import annotations

import importlib
from typing import Any

from skilltest.runners.base import AgentRun, Runner, RunRequest, ToolCall, Usage

# runner name -> "module:ClassName"
RUNNERS: dict[str, str] = {
    "claude-code": "skilltest.runners.claude_code:ClaudeCodeRunner",
    "codex": "skilltest.runners.codex:CodexRunner",
    "openai-compatible": "skilltest.runners.openai_compat:OpenAICompatibleRunner",
    "mock": "skilltest.runners.mock:MockRunner",
}


def get_runner_class(name: str) -> type[Runner]:
    module_name, class_name = RUNNERS[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)


def get_runner(name: str, options: dict[str, Any] | None = None) -> Runner:
    return get_runner_class(name)(options)


__all__ = ["RUNNERS", "AgentRun", "RunRequest", "Runner", "ToolCall", "Usage", "get_runner"]
