"""Loading a skill folder (a directory with a SKILL.md) and copying it into sandboxes."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel

from skilltest.errors import SkillError

SKILL_FILE = "SKILL.md"

# Never copied into the sandbox along with the skill. The agent must not be able
# to read the eval cases (and their assertions) while it is being evaluated.
ALWAYS_EXCLUDED = {".git", ".skilltest", "evals.yaml", "evals.yml", "__pycache__", ".venv"}


class Skill(BaseModel):
    path: Path
    name: str
    description: str
    body: str  # SKILL.md content without the frontmatter

    @property
    def skill_md(self) -> str:
        return (self.path / SKILL_FILE).read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body). Missing frontmatter -> {}."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            raw = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            try:
                data = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                raise SkillError(
                    f"SKILL.md frontmatter is not valid YAML: {exc}",
                    hint="Fix the YAML between the two '---' lines at the top of SKILL.md.",
                ) from exc
            if not isinstance(data, dict):
                return {}, body
            return data, body
    return {}, text


def load_skill(path: Path) -> Skill:
    path = path.resolve()
    skill_md = path / SKILL_FILE
    if not path.is_dir():
        raise SkillError(
            f"Skill folder not found: {path}",
            hint="Set `skill:` in evals.yaml to the folder that contains SKILL.md.",
        )
    if not skill_md.is_file():
        raise SkillError(
            f"No {SKILL_FILE} in {path}",
            hint="A skill is a folder with a SKILL.md file. Point `skill:` at that folder.",
        )
    meta, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    if not name or not description:
        raise SkillError(
            f"{skill_md} must have `name` and `description` in its frontmatter.",
            hint=(
                "Start SKILL.md with:\n---\nname: my-skill\n"
                "description: What it does and when to use it.\n---"
            ),
        )
    return Skill(path=path, name=name, description=description, body=body)


def copy_skill(skill: Skill, dest: Path, exclude: list[Path] | None = None) -> Path:
    """Copy the skill folder to `dest`, leaving out eval files and fixtures.

    `exclude` holds absolute paths (e.g. fixture folders that live inside the
    skill folder) that must not be visible to the agent.
    """
    excluded = {p.resolve() for p in (exclude or [])}

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set()
        for name in names:
            full = (Path(directory) / name).resolve()
            if name in ALWAYS_EXCLUDED or full in excluded:
                skipped.add(name)
        return skipped

    shutil.copytree(skill.path, dest, ignore=ignore, dirs_exist_ok=True)
    return dest
