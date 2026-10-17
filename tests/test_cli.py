from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from skilltest import __version__
from skilltest.cli import app
from skilltest.config import parse_config

cli = CliRunner()


def test_version() -> None:
    result = cli.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_init_on_existing_skill(skill_dir: Path) -> None:
    result = cli.invoke(app, ["init", str(skill_dir)])
    assert result.exit_code == 0, result.output
    assert (skill_dir / "evals.yaml").is_file()
    assert (skill_dir / "fixtures" / "example" / "README.txt").is_file()
    text = (skill_dir / "evals.yaml").read_text()
    assert '"stack-trace-explainer"' in text
    assert "Explains Java stack traces" in text


def test_init_scaffold_is_a_valid_config(skill_dir: Path) -> None:
    cli.invoke(app, ["init", str(skill_dir), "--runner", "codex"])
    data = yaml.safe_load((skill_dir / "evals.yaml").read_text())
    config = parse_config(data, skill_dir)
    assert config.runner == "codex"
    assert [c.should_trigger for c in config.cases] == [True, False]
    assert config.cases[0].fixtures == (skill_dir / "fixtures" / "example").resolve()


def test_init_creates_placeholder_skill_md(tmp_path: Path) -> None:
    target = tmp_path / "new-skill"
    result = cli.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    assert (target / "SKILL.md").is_file()
    assert "placeholder" in result.output


def test_init_refuses_to_overwrite(skill_dir: Path) -> None:
    (skill_dir / "evals.yaml").write_text("mine")
    result = cli.invoke(app, ["init", str(skill_dir)])
    assert result.exit_code == 2
    assert "--force" in result.output
    assert (skill_dir / "evals.yaml").read_text() == "mine"
    assert cli.invoke(app, ["init", str(skill_dir), "--force"]).exit_code == 0


def test_run_with_mock_runner(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    write_evals(
        {
            "trials": 2,
            "runner_options": {
                "default": {
                    "with": {"text": "Paris", "output_tokens": 100},
                    "without": {"text": "?"},
                }
            },
            "cases": [
                {
                    "name": "capital",
                    "prompt": "Capital of France?",
                    "assert": [{"type": "contains", "value": "Paris"}],
                }
            ],
        }
    )
    out = tmp_path / "out"
    result = cli.invoke(app, ["run", str(skill_dir), "--out", str(out)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "skill lift: +100%" in result.output
    assert "triggers 2/2" in result.output
    assert "stack-trace-explainer" in result.output
    assert list(out.glob("runs/*/results.json"))


@pytest.mark.parametrize(
    ("evals", "expected"),
    [
        (
            {
                "cases": [
                    {"name": "c", "prompt": "p", "assert": [{"type": "contain", "value": "x"}]}
                ]
            },
            "unknown assertion type 'contain'",
        ),
        (
            {
                "runner": "claude-code",
                "runner_options": {"cli_path": "/nonexistent/claude"},
                "cases": [{"name": "c", "prompt": "p"}],
            },
            "Claude Code CLI not found",
        ),
    ],
)
def test_run_errors_show_a_fix(write_evals, skill_dir: Path, evals: dict, expected: str) -> None:
    write_evals(evals)
    result = cli.invoke(app, ["run", str(skill_dir)])
    assert result.exit_code == 2
    assert expected in result.output
    assert "fix:" in result.output
    assert "Traceback" not in result.output


def test_run_without_evals(tmp_path: Path) -> None:
    result = cli.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 2
    assert "skilltest init" in result.output


def test_unknown_format(skill_dir: Path) -> None:
    result = cli.invoke(app, ["run", str(skill_dir), "--format", "pdf"])
    assert result.exit_code == 2


def test_badge_is_stubbed(skill_dir: Path) -> None:
    result = cli.invoke(app, ["badge", str(skill_dir)])
    assert result.exit_code == 2
    assert "not implemented yet" in result.output
