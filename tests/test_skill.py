from __future__ import annotations

from pathlib import Path

import pytest

from skillproof.errors import SkillError
from skillproof.skill import copy_skill, load_skill, parse_frontmatter


def test_parse_frontmatter() -> None:
    meta, body = parse_frontmatter("---\nname: x\ndescription: y\n---\nhello\n")
    assert meta == {"name": "x", "description": "y"}
    assert body == "hello\n"


def test_parse_frontmatter_missing() -> None:
    assert parse_frontmatter("# just markdown") == ({}, "# just markdown")


def test_load_skill(skill_dir: Path) -> None:
    skill = load_skill(skill_dir)
    assert skill.name == "stack-trace-explainer"
    assert "Java stack traces" in skill.description
    assert skill.body.startswith("\n# Stack trace explainer")


def test_load_skill_without_skill_md(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match=r"No SKILL\.md") as exc:
        load_skill(tmp_path)
    assert exc.value.hint


def test_load_skill_missing_description(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text("---\nname: x\n---\nbody")
    with pytest.raises(SkillError, match="description"):
        load_skill(tmp_path)


def test_copy_skill_hides_eval_files(skill_dir: Path, tmp_path: Path) -> None:
    (skill_dir / "evals.yaml").write_text("cases: []")
    (skill_dir / ".skillproof").mkdir()
    dest = tmp_path / "installed"
    copy_skill(load_skill(skill_dir), dest, exclude=[skill_dir / "fixtures" / "case1"])

    assert (dest / "SKILL.md").is_file()
    assert (dest / "reference.md").is_file()
    assert not (dest / "evals.yaml").exists()
    assert not (dest / ".skillproof").exists()
    assert not (dest / "fixtures" / "case1").exists()
