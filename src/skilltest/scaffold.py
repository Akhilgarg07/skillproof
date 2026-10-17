"""`skilltest init`: write a starter evals.yaml and fixtures folder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from skilltest.errors import SkilltestError
from skilltest.skill import SKILL_FILE, SkillError, load_skill

EVALS_TEMPLATE = """\
# skilltest evals for the "{name}" skill.
#
# Every case runs `trials` times WITH the skill installed and `trials` times
# WITHOUT it (the baseline). skilltest then reports whether the skill was
# triggered, pass rate with vs. without (the "lift"), and token/latency deltas.
#
# Run it:   skilltest run {display_path}

skill: ./                # folder containing SKILL.md, relative to this file
runner: {runner}{runner_pad}# claude-code | codex | openai-compatible
{model_line}
trials: 5                # runs per case, per variant. More trials = tighter numbers.
timeout: 300             # seconds per run

# Only needed for llm_judge assertions. `auto` picks a judge from a different
# vendor than the agent under test, so a model never grades itself.
# judge:
#   provider: auto       # auto | anthropic | openai
#   model: ...

cases:
  # A task the skill SHOULD help with. Write it the way a real user would:
  # don't name the skill, that's what the trigger rate measures.
  - name: "example task"
    prompt: |
      TODO: replace with a realistic request that needs this skill:
      {description}
    fixtures: ./fixtures/example/   # copied into a fresh temp dir for every run
    assert:
      # Deterministic checks first: cheap, fast and reproducible.
      - type: contains            # final answer contains this text (case-insensitive)
        value: "TODO"
      # - type: not_contains
      #   value: "I can't"
      # - type: regex
      #   pattern: "line \\\\d+"
      # - type: file_exists       # path is relative to the sandbox
      #   path: "output.md"
      # - type: file_contains
      #   path: "output.md"
      #   value: "## Summary"
      # - type: command           # runs in the sandbox, passes on exit code 0
      #   run: "python -m pytest -q"
      # - type: max_tokens        # input + output + cache tokens for the run
      #   value: 50000
      # - type: llm_judge         # optional, graded by a different-vendor model
      #   rubric: "States the root cause in the first sentence."

  # A request the skill should NOT activate for. Catches over-eager
  # descriptions that load the skill (and burn tokens) when it isn't needed.
  - name: "unrelated request"
    prompt: "What is the capital of France? Answer in one word."
    should_trigger: false
    assert:
      - type: contains
        value: "Paris"
"""

MODEL_LINES = {
    "openai-compatible": "model: gpt-6.1-sol       # required: any model your endpoint serves\n"
    "runner_options:\n"
    "  # base_url: http://localhost:11434/v1   # e.g. Ollama; default is api.openai.com",
    "default": "# model: ...             # optional; defaults to the agent's own default model",
}

FIXTURE_README = """\
Files in this folder are copied into a fresh temporary directory before every
run, so the agent can read and edit them without touching your real project.

Replace this file with whatever the "example task" case needs: a repo snippet,
a log file, a CSV, a failing test...
"""

SKILL_TEMPLATE = """\
---
name: {name}
description: TODO - what this skill does and when the agent should use it.
---

# {name}

TODO: instructions for the agent.
"""


@dataclass
class InitResult:
    created: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def init_skill(path: Path, runner: str = "claude-code", force: bool = False) -> InitResult:
    result = InitResult()
    path.mkdir(parents=True, exist_ok=True)
    evals_path = path / "evals.yaml"
    if evals_path.exists() and not force:
        raise SkilltestError(
            f"{evals_path} already exists.",
            hint="Use --force to overwrite it, or edit it by hand.",
        )

    name = path.resolve().name
    description = "TODO: describe the task."
    if (path / SKILL_FILE).is_file():
        try:
            skill = load_skill(path)
            name, description = skill.name, skill.description
        except SkillError as exc:
            result.warnings.append(f"{exc.message} {exc.hint or ''}".strip())
    else:
        (path / SKILL_FILE).write_text(SKILL_TEMPLATE.format(name=name), encoding="utf-8")
        result.created.append(path / SKILL_FILE)
        result.warnings.append(f"No {SKILL_FILE} found, so a placeholder was created. Fill it in.")

    evals_path.write_text(
        EVALS_TEMPLATE.format(
            name=name,
            display_path=_display(path),
            runner=runner,
            runner_pad=" " * max(1, 17 - len(runner)),
            model_line=MODEL_LINES.get(runner, MODEL_LINES["default"]),
            description=" ".join(description.split()),
        ),
        encoding="utf-8",
    )
    result.created.append(evals_path)

    fixtures = path / "fixtures" / "example"
    fixtures.mkdir(parents=True, exist_ok=True)
    readme = fixtures / "README.txt"
    if not readme.exists():
        readme.write_text(FIXTURE_README, encoding="utf-8")
        result.created.append(readme)
    return result


def _display(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path.cwd())
        return f"./{rel}" if str(rel) != "." else "."
    except ValueError:
        return str(path)
