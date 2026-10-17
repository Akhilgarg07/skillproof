"""Claude Code runner, via the Claude Agent SDK (`claude-agent-sdk` on PyPI).

Isolation:
  * The agent runs in the sandbox (`cwd`), with only *project* settings loaded
    (`setting_sources=["project"]`). Your personal ~/.claude skills, CLAUDE.md,
    settings and plugins are not loaded, for both variants.
  * With the skill: it is copied to `<sandbox>/.claude/skills/<name>/` and is
    the only skill the model may invoke (`skills=[name]`).
  * Baseline: nothing is installed and no skill may be invoked (`skills=[]`).
  * Sessions are not saved to ~/.claude (`--no-session-persistence`).

Trigger detection: a `Skill` tool call naming the skill (see parsers/claude_code.py).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from skilltest.errors import RunnerNotReady
from skilltest.parsers.claude_code import parse_transcript, to_dict
from skilltest.runners.base import AgentRun, Runner, RunRequest
from skilltest.skill import copy_skill

MAX_STDERR_LINES = 50


class ClaudeCodeRunner(Runner):
    name = "claude-code"
    vendor = "anthropic"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        # The sandbox is a throwaway temp dir, so by default the agent may edit
        # files and run commands without prompts, like a real unattended session.
        permission_mode: Literal["default", "acceptEdits", "bypassPermissions", "dontAsk"] = (
            "bypassPermissions"
        )
        max_turns: int | None = None
        max_budget_usd: float | None = None  # per run; the SDK stops the run past this
        effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
        tools: list[str] | None = None  # restrict built-in tools, e.g. ["Read", "Bash"]
        cli_path: str | None = None  # use this `claude` binary instead of the bundled one

    options: Options

    def check_ready(self) -> None:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as exc:
            raise RunnerNotReady(
                "The claude-code runner needs the Claude Agent SDK.",
                hint='Install it with: pip install "claude-agent-sdk"',
            ) from exc
        cli = self.options.cli_path
        if cli and not (Path(cli).is_file() or shutil.which(cli)):
            raise RunnerNotReady(
                f"Claude Code CLI not found at {cli!r}.",
                hint="Fix `runner_options.cli_path`, or remove it to use the bundled CLI.",
            )

    async def run(self, request: RunRequest) -> AgentRun:
        from claude_agent_sdk import ClaudeAgentOptions, query

        skill_name = request.skill.name if request.skill else None
        if request.skill is not None:
            dest = request.workdir / ".claude" / "skills" / request.skill.name
            copy_skill(request.skill, dest, exclude=request.skill_exclude)

        stderr: list[str] = []
        opts = self.options
        options = ClaudeAgentOptions(
            cwd=request.workdir,
            setting_sources=["project"],
            skills=[skill_name] if skill_name else [],
            permission_mode=opts.permission_mode,
            model=request.model,
            max_turns=opts.max_turns,
            max_budget_usd=opts.max_budget_usd,
            effort=opts.effort,
            tools=opts.tools,
            cli_path=opts.cli_path,
            extra_args={"no-session-persistence": None},
            stderr=lambda line: stderr.append(line) if len(stderr) < MAX_STDERR_LINES else None,
        )

        transcript: list[dict[str, Any]] = []
        stream = query(prompt=request.prompt, options=options)
        try:
            async for message in stream:
                transcript.append(to_dict(message))
        except Exception as exc:
            # The SDK raises after yielding an error result; the result says it all.
            if not any(m.get("_type") == "ResultMessage" for m in transcript):
                detail = "\n".join(stderr[-5:])
                raise RuntimeError(f"{exc}\n{detail}".strip()) from exc
        finally:
            await stream.aclose()

        return parse_transcript(transcript, skill_name)
