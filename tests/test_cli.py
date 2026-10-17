from __future__ import annotations

import json
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


def run_mock(write_evals, skill_dir: Path, tmp_path: Path, *args: str):
    write_evals(
        {
            "trials": 2,
            "runner_options": {"default": {"with": {"text": "Paris"}, "without": {"text": "?"}}},
            "cases": [
                {
                    "name": "capital",
                    "prompt": "?",
                    "assert": [{"type": "contains", "value": "Paris"}],
                }
            ],
        }
    )
    out = tmp_path / "out"
    return out, cli.invoke(app, ["run", str(skill_dir), "--out", str(out), *args])


def test_run_saves_reports(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    out, result = run_mock(write_evals, skill_dir, tmp_path)
    assert result.exit_code == 0, result.output
    run_dir = next((out / "runs").iterdir())
    for name in ("results.json", "summary.json", "report.md", "report.html"):
        assert (run_dir / name).is_file()


def test_run_json_goes_to_stdout(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    _, result = run_mock(write_evals, skill_dir, tmp_path, "--format", "json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["lift"] == 1.0


def test_run_writes_output_file(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "reports" / "skill.md"
    _, result = run_mock(write_evals, skill_dir, tmp_path, "--format", "md", "-o", str(target))
    assert result.exit_code == 0
    assert target.read_text().startswith("## skilltest:")


def test_report_and_badge_from_saved_run(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    out, _ = run_mock(write_evals, skill_dir, tmp_path)
    result = cli.invoke(app, ["report", "--out", str(out), "--format", "md"])
    assert result.exit_code == 0
    assert "| capital |" in result.stdout

    result = cli.invoke(app, ["badge", str(skill_dir), "--out", str(out)])
    assert result.exit_code == 0
    assert result.stdout.startswith("[![skilltest: +100% lift · 2/2 triggered]")

    result = cli.invoke(app, ["badge", str(skill_dir), "--out", str(out), "--json"])
    assert json.loads(result.stdout)["color"] == "brightgreen"


def test_badge_without_runs(skill_dir: Path, tmp_path: Path) -> None:
    result = cli.invoke(app, ["badge", str(skill_dir), "--out", str(tmp_path / "none")])
    assert result.exit_code == 2
    assert "skilltest run" in result.output


def mock_evals(write_evals, **extra) -> None:
    write_evals(
        {
            "trials": 2,
            "runner_options": {"default": {"with": {"text": "Paris"}, "without": {"text": "?"}}},
            "cases": [
                {
                    "name": "capital",
                    "prompt": "?",
                    "assert": [{"type": "contains", "value": "Paris"}],
                }
            ],
            **extra,
        }
    )


def test_dry_run_runs_nothing(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    mock_evals(write_evals)
    out = tmp_path / "out"
    result = cli.invoke(app, ["run", str(skill_dir), "--dry-run", "--out", str(out)])
    assert result.exit_code == 0
    assert "plan: 4 agent runs · no API cost" in result.output
    assert not out.exists()


def test_cost_guard_blocks_without_yes(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    write_evals(
        {
            "runner": "openai-compatible",
            "model": "m",
            "trials": 100,
            "cases": [{"name": "c", "prompt": "p"}],
        }
    )
    args = ["run", str(skill_dir), "--out", str(tmp_path / "out"), "--confirm-above", "1"]
    result = cli.invoke(app, args, env={"OPENAI_API_KEY": "sk-test"})
    assert result.exit_code == 2
    assert "Estimated cost ~$4.00 is above $1.00" in result.output
    assert "--yes" in result.output


def test_gates(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    mock_evals(write_evals)
    out = ["--out", str(tmp_path / "out")]
    ok = cli.invoke(
        app, ["run", str(skill_dir), *out, "--min-lift", "50", "--min-trigger-rate", "100"]
    )
    assert ok.exit_code == 0, ok.output
    bad = cli.invoke(app, ["run", str(skill_dir), *out, "--min-lift", "150"])
    assert bad.exit_code == 1
    assert "gate failed: lift +100% is below --min-lift +150%" in bad.output


def test_refuses_todo_placeholders(skill_dir: Path, tmp_path: Path) -> None:
    cli.invoke(app, ["init", str(skill_dir), "--runner", "mock"])
    result = cli.invoke(app, ["run", str(skill_dir), "--out", str(tmp_path / "out")])
    assert result.exit_code == 2
    assert "still has TODO placeholders" in result.output


def test_crash_handler(monkeypatch, capsys) -> None:
    from skilltest import cli as cli_module

    def boom() -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli_module, "app", boom)
    monkeypatch.delenv("SKILLTEST_DEBUG", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli_module.main()
    assert exc.value.code == 70
    assert "skilltest crashed: RuntimeError: kaboom" in capsys.readouterr().err
    monkeypatch.setenv("SKILLTEST_DEBUG", "1")
    with pytest.raises(RuntimeError):
        cli_module.main()
