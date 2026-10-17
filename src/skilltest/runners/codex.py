"""Codex CLI runner, via `codex exec --json` (non-interactive mode).

Isolation (each run):
  * A fresh CODEX_HOME and HOME, so your ~/.codex config, AGENTS.md and personal
    skills (~/.codex/skills, ~/.agents/skills) are not loaded for either variant.
    Auth is carried over: CODEX_API_KEY / OPENAI_API_KEY from the environment,
    else your `codex login` auth.json is copied into the temp CODEX_HOME.
  * Codex's bundled system skills are disabled (`skills.bundled.enabled=false`).
  * With the skill: it is copied to `<sandbox>/.agents/skills/<name>/`, where
    Codex discovers repo skills. Baseline: nothing is installed.
  * `--ephemeral`: no session files are written.

Trigger detection: a shell command touching `skills/<name>/` (see parsers/codex.py).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from skilltest.errors import RunnerNotReady
from skilltest.parsers.codex import parse_events, parse_jsonl
from skilltest.runners.base import AgentRun, Runner, RunRequest
from skilltest.skill import copy_skill

STREAM_LIMIT = 64 * 1024 * 1024  # JSONL lines carry whole command outputs


def user_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


class CodexRunner(Runner):
    name = "codex"
    vendor = "openai"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        sandbox: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
        cli_path: str = "codex"
        # Extra `-c key=value` overrides, e.g. {"model_reasoning_effort": "low"}.
        config: dict[str, str] = Field(default_factory=dict)

    options: Options

    def check_ready(self) -> None:
        if shutil.which(self.options.cli_path) is None:
            raise RunnerNotReady(
                f"Codex CLI not found ({self.options.cli_path!r}).",
                hint="Install it with: npm install -g @openai/codex",
            )
        has_key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not has_key and not (user_codex_home() / "auth.json").is_file():
            raise RunnerNotReady(
                "No credentials for Codex.",
                hint="export CODEX_API_KEY=... (or OPENAI_API_KEY), or run `codex login`.",
            )

    def command(self, request: RunRequest) -> list[str]:
        cmd = [
            self.options.cli_path,
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--sandbox",
            self.options.sandbox,
            "-C",
            str(request.workdir),
            "-c",
            "skills.bundled.enabled=false",
            # Otherwise a network problem makes codex retry forever.
            "--disable",
            "unbounded_connection_retries",
        ]
        if request.model:
            cmd += ["-m", request.model]
        for key, value in self.options.config.items():
            cmd += ["-c", f"{key}={value}"]
        return [*cmd, request.prompt]

    def environment(self, home: Path) -> dict[str, str]:
        codex_home = home / "codex_home"
        codex_home.mkdir(parents=True)
        env = dict(os.environ)
        key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            env["CODEX_API_KEY"] = key  # codex exec reads CODEX_API_KEY, not OPENAI_API_KEY
        elif (user_codex_home() / "auth.json").is_file():
            shutil.copy2(user_codex_home() / "auth.json", codex_home / "auth.json")
        env["CODEX_HOME"] = str(codex_home)
        env["HOME"] = str(home)  # ~/.agents/skills is looked up under $HOME
        return env

    async def run(self, request: RunRequest) -> AgentRun:
        skill_name = request.skill.name if request.skill else None
        if request.skill is not None:
            dest = request.workdir / ".agents" / "skills" / request.skill.name
            copy_skill(request.skill, dest, exclude=request.skill_exclude)

        home = Path(tempfile.mkdtemp(prefix="skilltest-codex-home-"))
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command(request),
                cwd=request.workdir,
                env=self.environment(home),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT,
            )
            stdout, stderr = await proc.communicate()
        finally:
            if proc is not None and proc.returncode is None:  # cancelled by the timeout
                proc.kill()
                await proc.wait()
            shutil.rmtree(home, ignore_errors=True)

        run = parse_events(parse_jsonl(stdout.decode(errors="replace")), skill_name)
        run.model = request.model
        if run.error and proc.returncode != 0:
            tail = stderr.decode(errors="replace").strip().splitlines()[-3:]
            run.error = "\n".join([run.error, *tail]).strip()
        return run
