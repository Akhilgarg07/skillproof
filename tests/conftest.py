from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

SKILL_MD = """\
---
name: stack-trace-explainer
description: Explains Java stack traces and writes a fix.patch.
---

# Stack trace explainer

Read the log, name the exception in the first sentence, write fix.patch.
"""


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
