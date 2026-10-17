"""Fresh temp directories for each run, so runs never touch the user's project.

Sandboxes live in the system temp dir (not inside the user's repo) so agents
that walk up the directory tree looking for config (CLAUDE.md, AGENTS.md, .git)
don't pick up the user's real project.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

# Env vars whose values must never reach logs, saved transcripts, or `command`
# assertions. Matched against the variable *name*.
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
MIN_SECRET_LENGTH = 8  # shorter values are too likely to collide with normal text


def create_sandbox(fixtures: Path | None = None, prefix: str = "skillproof-") -> Path:
    workdir = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    if fixtures is not None:
        shutil.copytree(fixtures, workdir, dirs_exist_ok=True)
    return workdir


def remove_sandbox(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)


def scrubbed_env() -> dict[str, str]:
    """A copy of os.environ without anything that looks like a credential."""
    return {k: v for k, v in os.environ.items() if not SECRET_NAME.search(k)}


def secret_values() -> list[str]:
    values = [
        v for k, v in os.environ.items() if SECRET_NAME.search(k) and len(v) >= MIN_SECRET_LENGTH
    ]
    return sorted(set(values), key=len, reverse=True)


def redact(text: str) -> str:
    """Replace any credential values from the environment with ***."""
    for value in secret_values():
        text = text.replace(value, "***")
    return text


def _run_shell(command: str, cwd: Path, timeout: float) -> tuple[int | None, str]:
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        env=scrubbed_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # so a timeout can kill the whole process group
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.communicate()
        return None, ""
    return proc.returncode, out.decode(errors="replace")


async def run_shell(command: str, cwd: Path, timeout: float) -> tuple[int | None, str]:
    """Run a shell command in the sandbox without credentials in its environment.

    Returns (exit code, combined output); exit code None means it timed out.
    Runs in a worker thread with plain `subprocess` rather than asyncio
    subprocesses: on Python 3.10/3.11, asyncio's child watcher can collide with
    the Agent SDK's own subprocesses and misreport exit codes as 255.
    """
    return await asyncio.to_thread(_run_shell, command, cwd, timeout)
