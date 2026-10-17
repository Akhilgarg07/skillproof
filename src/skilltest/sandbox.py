"""Fresh temp directories for each run, so runs never touch the user's project.

Sandboxes live in the system temp dir (not inside the user's repo) so agents
that walk up the directory tree looking for config (CLAUDE.md, AGENTS.md, .git)
don't pick up the user's real project.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

# Env vars whose values must never reach logs, saved transcripts, or `command`
# assertions. Matched against the variable *name*.
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
MIN_SECRET_LENGTH = 8  # shorter values are too likely to collide with normal text


def create_sandbox(fixtures: Path | None = None, prefix: str = "skilltest-") -> Path:
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
