"""The rich terminal report: a per-case table plus a one-line summary."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from skilltest.results import SuiteResult
from skilltest.stats import CaseStats, SuiteStats, suite_stats


def pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def signed_pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:+.0f}%".replace("-", "−")


def fraction(num: int, den: int) -> str:
    return "–" if den == 0 else f"{num}/{den}"


def lift_style(value: float | None) -> str:
    if value is None or abs(value) < 0.005:
        return "dim"
    return "green" if value > 0 else "red"


def summary_line(stats: SuiteStats) -> str:
    parts = [f"skill lift: {signed_pct(stats.lift)}"]
    parts.append(f"triggers {fraction(stats.triggers, stats.trigger_runs)}")
    if stats.false_trigger_runs:
        parts.append(f"false triggers {fraction(stats.false_triggers, stats.false_trigger_runs)}")
    parts.append(f"tokens {signed_pct(stats.token_delta)}")
    parts.append(f"latency {signed_pct(stats.latency_delta)}")
    return "  |  ".join(parts)


def trigger_cell(case: CaseStats) -> str:
    v = case.with_skill
    cell = fraction(v.triggered, v.trigger_known)
    if not case.should_trigger:
        style = "green" if v.triggered == 0 else "yellow"
        return f"[{style}]{cell}[/] [dim](should not)[/]"
    return cell


def case_table(stats: SuiteStats) -> Table:
    table = Table(show_edge=False, header_style="bold")
    table.add_column("case")
    table.add_column("triggered", justify="right")
    table.add_column("pass with", justify="right")
    table.add_column("pass without", justify="right")
    table.add_column("lift", justify="right")
    table.add_column("tokens Δ", justify="right")
    table.add_column("latency Δ", justify="right")
    for case in stats.cases:
        w, wo = case.with_skill, case.without_skill
        pass_with = fraction(w.passed, w.runs) if case.has_assertions else "–"
        pass_without = fraction(wo.passed, wo.runs) if case.has_assertions else "–"
        errors = w.errors + wo.errors
        name = case.name + (f" [yellow]({errors} errored)[/]" if errors else "")
        table.add_row(
            name,
            trigger_cell(case),
            pass_with,
            pass_without,
            f"[{lift_style(case.lift)}]{signed_pct(case.lift)}[/]",
            signed_pct(case.token_delta),
            signed_pct(case.latency_delta),
        )
    return table


def render(suite: SuiteResult, console: Console | None = None) -> None:
    console = console or Console()
    stats = suite_stats(suite)
    title = f"[bold]{suite.skill_name}[/] · runner [bold]{suite.runner}[/]"
    models = sorted({t.run.model for c in suite.cases for t in c.trials if t.run.model})
    model = suite.model or ", ".join(models)
    if model:
        title += f" · model {model}"
    console.print()
    console.print(title)
    if suite.approximate:
        console.print(
            "[yellow]approximate:[/] this runner injects SKILL.md into the system prompt "
            "instead of loading it like a real agent. Trigger rates are not measured."
        )
    console.print()
    console.print(case_table(stats))
    console.print()
    console.print(f"[bold]{summary_line(stats)}[/]")
    if stats.errors:
        console.print(
            f"[yellow]{stats.errors} run(s) errored and were excluded. "
            "See the saved transcripts for details.[/]"
        )
    warnings = sorted({w for c in suite.cases for t in c.trials for w in t.run.warnings})
    for warning in warnings[:5]:
        console.print(f"[yellow]warning:[/] {warning}")
    console.print(f"[dim]transcripts: {suite.run_dir}[/]")
