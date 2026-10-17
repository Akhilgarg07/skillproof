"""leaderboard/leaderboard.py, driven with the mock runner (no API calls)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "leaderboard", ROOT / "leaderboard" / "leaderboard.py"
)
leaderboard = importlib.util.module_from_spec(spec)
sys.modules["leaderboard"] = leaderboard  # so pydantic can resolve its type hints
spec.loader.exec_module(leaderboard)

SELFTEST = {
    "name": "selftest",
    "path": "tests/selftest-skill",
    "evals": "../tests/selftest-skill/evals.yaml",
}


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, sub in (("CACHE", ".cache"), ("RESULTS", "results")):
        monkeypatch.setattr(leaderboard, name, tmp_path / sub)
    monkeypatch.setattr(leaderboard, "OUTPUT", tmp_path / "LEADERBOARD.md")
    skills = tmp_path / "skills.yaml"
    skills.write_text(json.dumps({"skills": [SELFTEST]}))
    real_load = leaderboard.load_entries
    monkeypatch.setattr(leaderboard, "load_entries", lambda: real_load(skills))
    return tmp_path


def test_shipped_skills_yaml_is_valid() -> None:
    entries = leaderboard.load_entries()
    assert {e.name for e in entries} >= {"release-notes", "python-style", "over-eager-formatter"}
    for entry in entries:
        assert (leaderboard.HERE / entry.evals).is_file(), entry.evals
        assert (ROOT / entry.path / "SKILL.md").is_file(), entry.path


def test_entry_links() -> None:
    entry = leaderboard.Entry(
        name="pdf", evals="x.yaml", repo="https://github.com/o/r.git", ref="v1", path="skills/pdf"
    )
    assert entry.link == "https://github.com/o/r/tree/v1/skills/pdf"
    assert leaderboard.Entry(name="local", evals="x.yaml").link is None
    with pytest.raises(ValueError):
        leaderboard.Entry(name="typo", evals="x.yaml", rpo="oops")


def test_run_and_render_end_to_end(isolated: Path) -> None:
    assert leaderboard.main(["run", "--trials", "5"]) == 0
    result = json.loads((isolated / "results" / "selftest.json").read_text())
    assert result["summary"]["verdict"] == "helps"
    table = (isolated / "LEADERBOARD.md").read_text()
    assert "| 1 | selftest | ✅ helps | +100% (" in table
    assert "| 5/variant | mock |" in table


def test_dry_run_runs_nothing(isolated: Path, capsys) -> None:
    assert leaderboard.main(["run", "--dry-run"]) == 0
    assert "selftest: 24 agent runs · no API cost" in capsys.readouterr().out
    assert not (isolated / "results").exists() or not any((isolated / "results").iterdir())


def test_unknown_entry(isolated: Path) -> None:
    assert leaderboard.main(["run", "--only", "nope"]) == 2


def fake_result(name: str, verdict: str, lift: float | None) -> object:
    base = json.loads((ROOT / "tests" / "fixtures" / "summary_template.json").read_text())
    base.update(
        verdict=verdict, lift=lift, lift_ci=None if lift is None else [lift - 0.2, lift + 0.2]
    )
    return leaderboard.Result.model_validate(
        {
            "entry": {"name": name, "evals": "x.yaml"},
            "ran_at": datetime(2026, 10, 17, tzinfo=timezone.utc).isoformat(),
            "summary": base,
        }
    )


def test_render_orders_by_verdict_then_lift() -> None:
    table = leaderboard.render(
        [
            fake_result("meh", "no clear effect", 0.05),
            fake_result("bad", "hurts", -0.4),
            fake_result("good", "helps", 0.3),
            fake_result("great", "helps", 0.6),
        ]
    )
    order = [line.split("|")[2].strip() for line in table.splitlines() if line.startswith("| ")][1:]
    assert order == ["great", "good", "meh", "bad"]
    assert "Runs: 2026-10-17." in table
