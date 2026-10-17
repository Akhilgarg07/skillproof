from __future__ import annotations

from pathlib import Path

import pytest

from skillproof.config import load_config
from skillproof.engine import Engine, RunOptions
from skillproof.errors import hint_for_error
from skillproof.estimate import Estimate, estimate, past_cost_per_run
from skillproof.results import CaseResult, SuiteResult, TrialResult
from skillproof.runners import AgentRun, Usage

CASES = [
    {"name": "a", "prompt": "p", "assert": [{"type": "llm_judge", "rubric": "r"}]},
    {"name": "b", "prompt": "p"},
]


def engine_for(write_evals, runner: str = "mock", **extra) -> Engine:
    data = {"runner": runner, "trials": 5, "cases": CASES, **extra}
    if runner == "openai-compatible":
        data["model"] = "m"
    return Engine(load_config(write_evals(data)), RunOptions())


def save_run(out: Path, name: str, skill: Path, runner: str, cost: float | None) -> None:
    run_dir = out / "runs" / name
    run_dir.mkdir(parents=True)
    trial = TrialResult(case="a", variant="with", trial=0, run=AgentRun(usage=Usage(cost_usd=cost)))
    suite = SuiteResult(
        skill_name="s",
        skill_path=str(skill),
        runner=runner,
        run_dir=str(run_dir),
        started_at="2026-10-17T12:00:00Z",
        cases=[CaseResult(name="a", trials=[trial])],
    )
    (run_dir / "results.json").write_text(suite.model_dump_json())


def test_counts_runs_and_judge_calls(write_evals, tmp_path: Path) -> None:
    plan = estimate(engine_for(write_evals), tmp_path)
    assert (plan.runs, plan.judge_calls) == (20, 10)
    assert plan.total_usd == 0
    assert plan.describe() == "20 agent runs + 10 judge calls · no API cost"


def test_default_cost_per_runner(write_evals, tmp_path: Path) -> None:
    plan = estimate(engine_for(write_evals, "openai-compatible"), tmp_path)
    assert plan.cost_per_run == 0.02
    assert plan.total_usd == pytest.approx(0.4)
    assert "rough default for openai-compatible" in plan.describe()


def test_learns_from_the_last_run(write_evals, skill_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    skill = skill_dir.resolve()
    save_run(out, "20261016-000000", skill, "openai-compatible", 0.50)
    save_run(out, "20261017-000000", skill, "openai-compatible", 0.10)  # newest wins
    save_run(out, "20261018-000000", skill, "codex", 9.0)  # other runner: ignored
    save_run(out, "20261019-000000", tmp_path / "other", "openai-compatible", 9.0)
    assert past_cost_per_run(out, skill, "openai-compatible") == pytest.approx(0.10)
    plan = estimate(engine_for(write_evals, "openai-compatible"), out)
    assert plan.total_usd == pytest.approx(2.0)
    assert "from your last run" in plan.describe()


def test_unknown_cost() -> None:
    assert Estimate(4, 0, None, "x").describe() == "4 agent runs · cost unknown"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("API error 401: invalid x-api-key", "API key"),
        ("Not logged in · Please run /login", "API key"),
        ("Error code: 429 - rate_limit_error", "Lower --parallel"),
        ("API error 529: overloaded", "Lower --parallel"),
        ("The model `gpt-9` does not exist", "model name"),
        ("Your credit balance is too low", "credits"),
        ("Connection failed: error sending request", "Network"),
        ("--dangerously-skip-permissions cannot be used with root/sudo", "as root"),
        ("something odd", "transcripts"),
    ],
)
def test_hint_for_error(error: str, expected: str) -> None:
    assert expected in hint_for_error(error)
