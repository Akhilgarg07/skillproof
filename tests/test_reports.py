from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest

from skillproof.assertions import AssertionResult
from skillproof.report import badge, build_summary, render_text, write_reports
from skillproof.report.format import interval, seconds, signed_pct, summary_line, tokens, usd
from skillproof.results import CaseResult, SuiteResult, TrialResult, find_latest_run, load_suite
from skillproof.runners import AgentRun, Usage


def trial(variant, passed=True, triggered=None, error=None, text="ok", warnings=()):
    return TrialResult(
        case="c",
        variant=variant,
        trial=0,
        run=AgentRun(
            final_text=text,
            usage=Usage(input_tokens=1000, output_tokens=100, cost_usd=0.01),
            duration_s=2.0,
            triggered=triggered,
            error=error,
            warnings=list(warnings),
        ),
        assertions=[AssertionResult(type="contains", passed=passed, message="checked")],
    )


def make_suite(
    with_passed: int, without_passed: int, runs: int = 10, triggered: int | None = None, **kw
) -> SuiteResult:
    triggered = runs if triggered is None else triggered
    trials = [trial("with", i < with_passed, triggered=i < triggered) for i in range(runs)]
    trials += [trial("without", i < without_passed) for i in range(runs)]
    defaults = dict(
        skill_name="pdf-tools",
        skill_path="/skills/pdf-tools",
        runner="claude-code",
        model="claude-sonnet-5-5",
        run_dir="/tmp/run",
        started_at=datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc),
    )
    defaults.update(kw)
    return SuiteResult(cases=[CaseResult(name="extract tables", trials=trials)], **defaults)


def test_formatting_helpers() -> None:
    assert signed_pct(0.234) == "+23%"
    assert signed_pct(-0.12) == "−12%"
    assert signed_pct(0.001) == "±0%"
    assert signed_pct(None) == "–"
    assert interval((-0.04, 0.61)) == "−4% to +61%"
    assert seconds(3.14) == "3.1s" and seconds(None) == "–"
    assert tokens(12345) == "12.3k" and tokens(512) == "512"
    assert usd(0.01234) == "$0.012" and usd(3.5) == "$3.50"


def test_summary_for_a_clear_win() -> None:
    s = build_summary(make_suite(9, 2))
    assert s.verdict == "helps"
    assert s.lift == pytest.approx(0.7)
    assert s.lift_ci[0] > 0
    assert (s.triggers, s.trigger_runs) == (10, 10)
    assert s.notes == []  # 10 runs per variant, all triggered, significant
    line = summary_line(s)
    assert line.startswith("skill lift: +70% (95% CI ")
    assert "triggers 10/10" in line and "cost ±0%" in line and "(2.0s vs 2.0s)" in line


@pytest.mark.parametrize(
    ("suite", "expected"),
    [
        (make_suite(3, 2, runs=5), "Small sample: as few as 5"),
        (make_suite(6, 5), "not statistically clear"),
        (make_suite(5, 5, triggered=0), "never triggered"),
        (make_suite(9, 2, triggered=7), "did not trigger in 3 of 10"),
        (make_suite(9, 2, approximate=True), "Approximate"),
    ],
)
def test_notes(suite: SuiteResult, expected: str) -> None:
    notes = build_summary(suite).notes
    assert any(expected in n for n in notes), notes


def test_errors_and_negative_case_notes() -> None:
    suite = make_suite(9, 2)
    suite.cases[0].trials.append(trial("with", error="API error 529"))
    neg = [trial("with", False, triggered=True) for _ in range(10)]
    neg += [trial("without", True) for _ in range(10)]
    suite.cases.append(CaseResult(name="unrelated", should_trigger=False, trials=neg))
    notes = build_summary(suite).notes
    assert any("1 run(s) errored" in n for n in notes)
    assert any("makes the unrelated case 'unrelated' worse" in n for n in notes)
    assert any("triggered in 10 of 10 runs where it should not" in n for n in notes)


def test_markdown_report() -> None:
    md = render_text("md", build_summary(make_suite(9, 2)), make_suite(9, 2))
    assert md.startswith("## skillproof: `pdf-tools`")
    assert "**✅ the skill helps**" in md
    assert "| extract tables | 10/10 | 9/10 | 2/10 | +70% (" in md
    assert "| cost / run | $0.010 | $0.010 |" in md


def test_json_report_is_the_summary() -> None:
    suite = make_suite(9, 2)
    data = json.loads(render_text("json", build_summary(suite), suite))
    assert data["schema_version"] == 1
    assert data["verdict"] == "helps"
    assert data["cases"][0]["with_skill"]["passed"] == 9
    assert len(data["lift_ci"]) == 2


def test_html_report_is_self_contained_and_escaped() -> None:
    suite = make_suite(9, 2, skill_name="<script>alert(1)</script>")
    suite.cases[0].trials[0].run.final_text = "<img src=x onerror=alert(1)>"
    html = render_text("html", build_summary(suite), suite)
    assert html.startswith("<!doctype html>")
    assert "<script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html and "&lt;img src=x" in html
    assert "http://" not in html.replace("http://www.w3.org", "")  # no external assets
    assert "the skill helps" in html and "Pass rate by case" in html


def test_badge() -> None:
    s = build_summary(make_suite(9, 2))
    assert badge.message(s) == "+70% lift · 10/10 triggered"
    url = badge.badge_url(s)
    assert url.endswith("-brightgreen")
    assert unquote(url.split("/badge/")[1]) == "skillproof-+70% lift · 10/10 triggered-brightgreen"
    assert badge.markdown(s).startswith("[![skillproof: +70% lift")
    assert json.loads(badge.endpoint_json(s)) == {
        "schemaVersion": 1,
        "label": "skillproof",
        "message": "+70% lift · 10/10 triggered",
        "color": "brightgreen",
    }


def test_badge_variants() -> None:
    assert badge.message(build_summary(make_suite(6, 5))).startswith("+10% lift (n.s.)")
    hurts = build_summary(make_suite(1, 9))
    assert badge.COLORS[hurts.verdict] == "red"
    assert "-80%25" in badge.badge_url(hurts).replace("--", "-")


def test_badge_escapes_dashes() -> None:
    s = build_summary(make_suite(1, 9))
    assert "--80%25" in badge.badge_url(s)  # shields needs '-' doubled


def test_write_and_reload_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / ".skillproof" / "runs" / "20261017-120000"
    run_dir.mkdir(parents=True)
    suite = make_suite(9, 2, run_dir=str(run_dir))
    (run_dir / "results.json").write_text(suite.model_dump_json())
    write_reports(suite)
    for name in ("summary.json", "report.md", "report.html"):
        assert (run_dir / name).is_file()
    assert find_latest_run(tmp_path / ".skillproof") == run_dir
    assert find_latest_run(tmp_path / ".skillproof", Path("/skills/pdf-tools")) == run_dir
    assert load_suite(run_dir).skill_name == "pdf-tools"
