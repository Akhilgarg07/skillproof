"""The rich terminal report: a per-case table, a summary line and the notes."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from skilltest.report.format import (
    VERDICT_TEXT,
    fraction,
    interval,
    signed_pct,
    summary_line,
)
from skilltest.report.summary import CaseSummary, Summary

VERDICT_STYLE = {
    "helps": "bold green",
    "hurts": "bold red",
    "no clear effect": "bold yellow",
    "not measured": "dim",
}


def lift_style(case: CaseSummary) -> str:
    return {"helps": "green", "hurts": "red"}.get(case.verdict, "")


def trigger_cell(case: CaseSummary) -> str:
    v = case.with_skill
    cell = fraction(v.triggered, v.trigger_known)
    if not case.should_trigger:
        style = "green" if v.triggered == 0 else "yellow"
        return f"[{style}]{cell}[/] [dim](should not)[/]"
    return cell


def case_table(summary: Summary) -> Table:
    table = Table(show_edge=False, header_style="bold")
    table.add_column("case")
    table.add_column("triggered", justify="right")
    table.add_column("pass with", justify="right")
    table.add_column("pass without", justify="right")
    table.add_column("lift", justify="right")
    table.add_column("tokens Δ", justify="right")
    table.add_column("latency Δ", justify="right")
    for case in summary.cases:
        w, wo = case.with_skill, case.without_skill
        graded = case.has_assertions
        errors = w.errors + wo.errors
        name = escape(case.name) + (f" [yellow]({errors} errored)[/]" if errors else "")
        lift = signed_pct(case.lift)
        if style := lift_style(case):
            lift = f"[{style}]{lift}[/]"
        table.add_row(
            name,
            trigger_cell(case),
            fraction(w.passed, w.runs) if graded else "–",
            fraction(wo.passed, wo.runs) if graded else "–",
            lift,
            signed_pct(case.token_delta),
            signed_pct(case.latency_delta),
        )
    return table


def render(summary: Summary, console: Console | None = None) -> None:
    console = console or Console()
    title = f"[bold]{escape(summary.skill_name)}[/] · runner [bold]{summary.runner}[/]"
    if summary.model:
        title += f" · model {escape(summary.model)}"
    console.print()
    console.print(title)
    console.print()
    console.print(case_table(summary))
    console.print()
    console.print(f"[bold]{summary_line(summary)}[/]", highlight=False)
    verdict = summary.verdict
    line = f"verdict: [{VERDICT_STYLE[verdict]}]{VERDICT_TEXT[verdict]}[/]"
    if summary.lift_ci is not None:
        line += f" [dim](95% CI for lift: {interval(summary.lift_ci)})[/]"
    console.print(line, highlight=False)
    for note in summary.notes:
        console.print(f"[yellow]•[/] {escape(note)}", highlight=False)
    for warning in summary.warnings[:5]:
        console.print(f"[yellow]warning:[/] {escape(warning)}", highlight=False)
    console.print(f"[dim]report: {summary.run_dir}/report.html[/]", highlight=False)
