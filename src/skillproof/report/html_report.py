"""HTML report: one self-contained file (inline CSS, no scripts, no network).

Layout: headline lift + verdict, stat tiles, a with/without pass-rate chart per
case, the case table, then every trial behind a <details> toggle.
Colors: "with skill" = blue, "without" = orange (validated categorical pair,
light and dark); verdicts use status colors and always carry an icon + label.
"""

from __future__ import annotations

from html import escape

from skillproof.report.format import (
    VERDICT_TEXT,
    fraction,
    interval,
    pct,
    seconds,
    signed_pct,
    tokens,
    usd,
)
from skillproof.report.summary import CaseSummary, Summary, VariantSummary
from skillproof.results import CaseResult, SuiteResult, TrialResult

MAX_ANSWER_CHARS = 4000

CSS = """
:root {
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --with: #2a78d6; --without: #eb6834;
  --good: #006300; --bad: #d03b3b; --neutral: #52514e;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --with: #3987e5; --without: #d95926;
    --good: #0ca30c; --bad: #e66767; --neutral: #c3c2b7;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 40px 0 12px; }
.meta { color: var(--ink-2); font-size: 13px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.92em; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.hero { display: flex; flex-wrap: wrap; gap: 24px; align-items: center; padding: 24px;
  margin-top: 20px; }
.hero .value { font-size: 56px; font-weight: 600; line-height: 1; }
.hero .label { color: var(--ink-2); font-size: 13px; margin-bottom: 6px; }
.verdict { font-weight: 600; font-size: 18px; }
.verdict.helps { color: var(--good); } .verdict.hurts { color: var(--bad); }
.verdict.neutral { color: var(--neutral); }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px;
  margin-top: 12px; }
.tile { padding: 14px 16px; }
.tile .label { color: var(--ink-2); font-size: 13px; }
.tile .value { font-size: 22px; font-weight: 600; }
.tile .sub { color: var(--muted); font-size: 12px; }
.notes { margin: 16px 0 0; padding: 12px 16px 12px 32px; }
.notes li { margin: 4px 0; }
.legend { display: flex; gap: 16px; font-size: 13px; color: var(--ink-2); margin-bottom: 8px; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
  margin-right: 6px; vertical-align: -1px; }
.chart { padding: 16px; }
.chart-row { display: grid; grid-template-columns: minmax(120px, 220px) 1fr; gap: 12px;
  align-items: center; padding: 8px 0; border-top: 1px solid var(--grid); }
.chart-row:first-child { border-top: 0; }
.chart-name { font-size: 13px; overflow-wrap: anywhere; }
@media (max-width: 600px) { .chart-row { grid-template-columns: 1fr; gap: 4px; } }
.bars { display: grid; gap: 2px; }
.bar-line { display: grid; grid-template-columns: 1fr 56px; gap: 8px; align-items: center; }
.track { height: 12px; position: relative; }
.bar { height: 12px; border-radius: 0 4px 4px 0; min-width: 2px; }
.bar.with { background: var(--with); } .bar.without { background: var(--without); }
.bar-value { font-size: 12px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-top: 1px solid var(--grid);
  vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; border-top: 0; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.table-wrap { overflow-x: auto; padding: 4px 6px; }
.pass { color: var(--good); font-weight: 600; } .fail { color: var(--bad); font-weight: 600; }
.err { color: var(--muted); font-weight: 600; }
details { margin-top: 10px; padding: 10px 14px; }
summary { cursor: pointer; font-weight: 600; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--page); padding: 10px;
  border-radius: 6px; font-size: 12px; max-height: 320px; overflow-y: auto; margin: 6px 0 0; }
ul.asserts { margin: 4px 0 0; padding-left: 18px; }
footer { margin-top: 48px; color: var(--muted); font-size: 12px; }
a { color: var(--with); }
"""

VERDICT_ICON = {
    "helps": "✓",
    "hurts": "✗",
    "no clear effect": "–",
    "too few runs": "–",
    "not measured": "–",
}
VERDICT_CLASS = {"helps": "helps", "hurts": "hurts"}


def _tile(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    return (
        f'<div class="card tile"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div>{sub_html}</div>'
    )


def _bar(kind: str, label: str, v: VariantSummary) -> str:
    width = 0.0 if v.pass_rate is None else v.pass_rate * 100
    ci = f", 95% CI {pct(v.pass_ci[0])}–{pct(v.pass_ci[1])}" if v.pass_ci else ""
    tip = f"{label}: {fraction(v.passed, v.runs)} passed{ci}"
    return (
        f'<div class="bar-line" title="{escape(tip)}">'
        f'<div class="track"><div class="bar {kind}" style="width:{width:.1f}%"></div></div>'
        f'<div class="bar-value">{pct(v.pass_rate)}</div></div>'
    )


def chart(summary: Summary) -> str:
    rows = []
    for case in summary.cases:
        if not case.has_assertions:
            continue
        rows.append(
            f'<div class="chart-row"><div class="chart-name">{escape(case.name)}</div>'
            f'<div class="bars">{_bar("with", "with skill", case.with_skill)}'
            f"{_bar('without', 'without skill', case.without_skill)}</div></div>"
        )
    if not rows:
        return ""
    legend = (
        '<div class="legend"><span><span class="swatch" style="background:var(--with)"></span>'
        'with skill</span><span><span class="swatch" style="background:var(--without)"></span>'
        "without skill</span></div>"
    )
    return f'<h2>Pass rate by case</h2>{legend}<div class="card chart">{"".join(rows)}</div>'


def _trigger(case: CaseSummary) -> str:
    cell = fraction(case.with_skill.triggered, case.with_skill.trigger_known)
    return cell + (" (should not)" if not case.should_trigger else "")


def case_table(summary: Summary) -> str:
    head = (
        "<tr><th>case</th><th class=num>triggered</th><th class=num>pass with</th>"
        "<th class=num>pass without</th><th class=num>lift</th><th class=num>95% CI</th>"
        "<th class=num>tokens Δ</th><th class=num>latency Δ</th></tr>"
    )
    rows = []
    for c in summary.cases:
        w, wo = c.with_skill, c.without_skill
        graded = c.has_assertions
        rows.append(
            f"<tr><td>{escape(c.name)}</td><td class=num>{escape(_trigger(c))}</td>"
            f"<td class=num>{fraction(w.passed, w.runs) if graded else '–'}</td>"
            f"<td class=num>{fraction(wo.passed, wo.runs) if graded else '–'}</td>"
            f"<td class=num>{signed_pct(c.lift)}</td><td class=num>{interval(c.lift_ci)}</td>"
            f"<td class=num>{signed_pct(c.token_delta)}</td>"
            f"<td class=num>{signed_pct(c.latency_delta)}</td></tr>"
        )
    return f'<h2>Cases</h2><div class="card table-wrap"><table>{head}{"".join(rows)}</table></div>'


def _result_cell(t: TrialResult) -> str:
    if t.errored:
        return '<span class="err">error</span>'
    if t.run.timed_out:
        return '<span class="fail">timeout</span>'
    return '<span class="pass">pass</span>' if t.passed else '<span class="fail">fail</span>'


def trial_details(case: CaseResult) -> str:
    rows = []
    for t in sorted(case.trials, key=lambda t: (t.trial, t.variant)):
        checks = "".join(
            f'<li><span class="{"pass" if a.passed else "fail"}">'
            f"{'✓' if a.passed else '✗'}</span> {escape(a.message)}</li>"
            for a in t.assertions
        )
        extra = f"<div class=err>{escape(t.run.error)}</div>" if t.run.error else ""
        answer = t.run.final_text[:MAX_ANSWER_CHARS]
        if len(t.run.final_text) > MAX_ANSWER_CHARS:
            answer += "\n… (truncated; see the transcript)"
        triggered = {True: "yes", False: "no", None: "–"}[t.run.triggered]
        rows.append(
            f"<tr><td>{t.variant} #{t.trial + 1}</td><td>{_result_cell(t)}</td>"
            f"<td class=num>{triggered}</td><td class=num>{tokens(t.run.usage.total_tokens)}</td>"
            f"<td class=num>{seconds(t.run.duration_s)}</td>"
            f'<td>{extra}<ul class="asserts">{checks}</ul>'
            f"<details><summary>answer</summary><pre>{escape(answer)}</pre></details>"
            f"<div class=meta><code>{escape(t.artifact or '')}</code></div></td></tr>"
        )
    head = (
        "<tr><th>run</th><th>result</th><th class=num>triggered</th><th class=num>tokens</th>"
        "<th class=num>time</th><th>checks</th></tr>"
    )
    return (
        f'<details class="card"><summary>{escape(case.name)} '
        f'<span class="meta">({len(case.trials)} runs)</span></summary>'
        f'<div class="table-wrap"><table>{head}{"".join(rows)}</table></div></details>'
    )


def render(summary: Summary, suite: SuiteResult) -> str:
    s = summary
    verdict_class = VERDICT_CLASS.get(s.verdict, "neutral")
    ci = f"95% CI {interval(s.lift_ci)}" if s.lift_ci else "no graded runs"
    meta = [f"runner <code>{escape(s.runner)}</code>"]
    if s.model:
        meta.append(f"model <code>{escape(s.model)}</code>")
    if s.judge:
        meta.append(f"judge <code>{escape(s.judge)}</code>")
    meta.append(escape(s.started_at.strftime("%Y-%m-%d %H:%M UTC")))
    if s.approximate:
        meta.append("<strong>approximate</strong>")

    w, wo = s.with_skill, s.without_skill
    tiles = [
        _tile(
            "Triggered",
            fraction(s.triggers, s.trigger_runs),
            f"false triggers {fraction(s.false_triggers, s.false_trigger_runs)}"
            if s.false_trigger_runs
            else "runs where the skill loaded",
        ),
        _tile("Pass rate with skill", pct(w.pass_rate), f"{w.passed}/{w.runs} runs"),
        _tile("Pass rate without", pct(wo.pass_rate), f"{wo.passed}/{wo.runs} runs"),
        _tile(
            "Tokens per run",
            signed_pct(s.token_delta),
            f"{tokens(w.mean_tokens)} vs {tokens(wo.mean_tokens)}",
        ),
        _tile(
            "Time per run",
            signed_pct(s.latency_delta),
            f"{seconds(w.mean_duration_s)} vs {seconds(wo.mean_duration_s)}",
        ),
    ]
    if s.cost_delta is not None:
        tiles.insert(
            4,
            _tile(
                "Cost per run",
                signed_pct(s.cost_delta),
                f"{usd(w.mean_cost_usd)} vs {usd(wo.mean_cost_usd)}",
            ),
        )
    notes = "".join(f"<li>{escape(n)}</li>" for n in [*s.notes, *s.warnings[:5]])
    notes_html = f'<ul class="card notes">{notes}</ul>' if notes else ""
    details = "".join(trial_details(c) for c in suite.cases)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>skillproof: {escape(s.skill_name)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>skillproof: {escape(s.skill_name)}</h1>
<div class="meta">{" · ".join(meta)}</div>

<div class="card hero">
  <div>
    <div class="label">Skill lift (pass rate with − without)</div>
    <div class="value">{signed_pct(s.lift)}</div>
  </div>
  <div>
    <div class="verdict {verdict_class}">{VERDICT_ICON[s.verdict]} {VERDICT_TEXT[s.verdict]}</div>
    <div class="meta">{ci}</div>
  </div>
</div>
<div class="tiles">{"".join(tiles)}</div>
{notes_html}
{chart(s)}
{case_table(s)}
<h2>Runs</h2>
{details}
<footer>Generated by <a href="https://github.com/akhilgarg07/skillproof">skillproof</a>
{escape(s.skillproof_version)} · transcripts in <code>{escape(s.run_dir)}</code></footer>
</main>
</body>
</html>
"""
