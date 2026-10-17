from __future__ import annotations

from pathlib import Path
from typing import Any

import claude_agent_sdk
import pytest
import yaml

from skillproof.runners.codex import CodexRunner

SKILL_MD = """\
---
name: stack-trace-explainer
description: Explains Java stack traces and writes a fix.patch.
---

# Stack trace explainer

Read the log, name the exception in the first sentence, write fix.patch.
"""


@pytest.fixture(autouse=True)
def no_real_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never call a real agent or API. Tests that exercise a
    runner replace these with fakes; anything that slips through fails fast."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a test tried to start a real Claude Code session")

    monkeypatch.setattr(claude_agent_sdk, "query", refuse)
    # The codex runner's default CLI is the real `codex` on PATH; tests must pass a fake.
    real_command = CodexRunner.command

    def guarded_command(self: CodexRunner, request: Any) -> list[str]:
        if self.options.cli_path == "codex":
            raise AssertionError("a test tried to run the real codex CLI")
        return real_command(self, request)

    monkeypatch.setattr(CodexRunner, "command", guarded_command)
    for var in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")  # nothing listens on the discard port


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """A minimal skill folder with SKILL.md and one fixture folder."""
    skill = tmp_path / "my-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(SKILL_MD)
    (skill / "reference.md").write_text("extra docs")
    fixtures = skill / "fixtures" / "case1"
    fixtures.mkdir(parents=True)
    (fixtures / "error.log").write_text("java.lang.NullPointerException at Foo.java:3")
    return skill


@pytest.fixture
def write_evals(skill_dir: Path):
    """Write evals.yaml into the skill folder from a dict and return its path."""

    def write(data: dict[str, Any]) -> Path:
        data = {"skill": "./", "runner": "mock", **data}
        path = skill_dir / "evals.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False))
        return path

    return write
