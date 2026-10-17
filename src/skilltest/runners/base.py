"""The Runner interface. Adding a new agent = one subclass of `Runner`.

A runner gets a `RunRequest` (prompt, a sandbox directory with fixtures already
copied in, and the skill or None for the baseline) and returns an `AgentRun`.

Rules every runner must follow:
  * Only touch `request.workdir` (and temp dirs you create yourself).
  * When `request.skill` is None the agent must NOT be able to see the skill,
    including any copy installed in the user's home config.
  * Fill `triggered` from the transcript if you can tell, else leave it None.
  * Infrastructure failures (API down, CLI crashed) can be raised or put in
    `error`; either way the run is reported as errored, not failed.
  * The engine enforces the timeout by cancelling `run()`. If you start a
    subprocess, kill it in a `finally:` block.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from skilltest.skill import Skill


class ToolCall(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float | None = None  # only when the agent reports it

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


class AgentRun(BaseModel):
    """Everything we captured from one agent run."""

    final_text: str = ""
    transcript: list[dict[str, Any]] = Field(default_factory=list)  # raw, runner-specific
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    duration_s: float = 0.0
    num_turns: int | None = None
    model: str | None = None  # the model that actually ran, when the agent reports it
    triggered: bool | None = None  # None = this runner can't tell
    timed_out: bool = False
    error: str | None = None  # infrastructure error; the run is excluded from pass rates
    warnings: list[str] = Field(default_factory=list)  # e.g. "skill not listed at startup"


@dataclass
class RunRequest:
    prompt: str
    workdir: Path  # fresh sandbox, fixtures already copied in
    skill: Skill | None  # None = baseline run
    skill_exclude: list[Path]  # pass to copy_skill() when installing the skill
    model: str | None
    timeout_s: float
    case_name: str
    trial: int  # 0-based


class Runner(ABC):
    name: ClassVar[str]
    # Who makes the model. Used to pick a judge from a *different* vendor.
    vendor: ClassVar[str]
    # True when the runner only simulates skill loading (e.g. stuffing SKILL.md
    # into the system prompt). Reports label these results as approximate.
    approximate: ClassVar[bool] = False
    # True when there is no sensible default model, so evals.yaml must set `model:`.
    requires_model: ClassVar[bool] = False

    class Options(BaseModel):
        """Runner-specific settings from `runner_options:` in evals.yaml."""

        model_config = ConfigDict(extra="forbid")

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = self.Options.model_validate(options or {})

    def check_ready(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Raise RunnerNotReady (with a hint) if the runner can't start."""

    @abstractmethod
    async def run(self, request: RunRequest) -> AgentRun: ...
