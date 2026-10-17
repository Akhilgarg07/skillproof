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

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from skillproof.errors import RunnerNotReady
from skillproof.parsers.claude_code import parse_transcript, to_dict
from skillproof.runners.base import AgentRun, Runner, RunRequest
from skillproof.skill import copy_skill

MAX_STDERR_LINES = 50

# Pre-approved tools when skipping permission prompts isn't allowed (see run()).
DEFAULT_ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Glob",
    "Grep",
    "LS",
    "NotebookEdit",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Task",
]


def running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _hide_reaped_child_warning(record: logging.LogRecord) -> bool:
    """CPython 3.10/3.11 race: when a finished subprocess object is garbage-collected,
    a later `subprocess.Popen` (e.g. a `command` assertion) can reap it before
    asyncio's child watcher does. asyncio then logs "Unknown child process pid ...,
    will report returncode 255". It only affects Claude Code processes that already
    delivered their result (which is what skillproof uses), so hide the noise."""
    return "will report returncode 255" not in record.getMessage()


logging.getLogger("asyncio").addFilter(_hide_reaped_child_warning)


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
        # Tools that run without asking (for permission_mode default/acceptEdits/dontAsk).
        allowed_tools: list[str] = []
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
        mode, allowed = opts.permission_mode, list(opts.allowed_tools)
        warnings = []
        if mode == "bypassPermissions" and running_as_root() and not os.environ.get("IS_SANDBOX"):
            # Claude Code refuses to skip permission prompts as root (common in
            # Docker). Pre-approving the usual tools gives the agent the same
            # abilities through a supported setting instead.
            mode, allowed = "dontAsk", allowed or DEFAULT_ALLOWED_TOOLS
            warnings.append(
                "running as root: used permission_mode dontAsk with pre-approved tools "
                "instead of bypassPermissions"
            )
        options = ClaudeAgentOptions(
            cwd=request.workdir,
            setting_sources=["project"],
            skills=[skill_name] if skill_name else [],
            permission_mode=mode,
            allowed_tools=allowed,
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

        run = parse_transcript(transcript, skill_name)
        run.warnings.extend(warnings)
        return run
