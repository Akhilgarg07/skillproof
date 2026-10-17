"""The `skilltest` command line."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from skilltest import __version__
from skilltest.config import EvalConfig, load_config
from skilltest.engine import Engine, RunOptions
from skilltest.errors import RunAborted, SkilltestError
from skilltest.estimate import CONFIRM_ABOVE_USD, Estimate, estimate
from skilltest.report import FORMATS, Summary, build_summary, render_text, terminal, write_reports
from skilltest.report import badge as badges
from skilltest.results import SuiteResult, find_latest_run, load_suite
from skilltest.scaffold import init_skill

app = typer.Typer(
    name="skilltest",
    help="pytest for agent skills: prove your skill actually works.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
console = Console()
err_console = Console(stderr=True)


def fail(exc: SkilltestError) -> typer.Exit:
    err_console.print(f"[bold red]error:[/] {exc.message}", highlight=False)
    if exc.hint:
        err_console.print(f"[bold]fix:[/] {exc.hint}", highlight=False)
    return typer.Exit(code=2)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"skilltest {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    pass


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Skill folder (contains SKILL.md).")] = Path("."),
    runner: Annotated[str, typer.Option(help="Agent to test with.")] = "claude-code",
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing evals.yaml.")
    ] = False,
) -> None:
    """Scaffold an evals.yaml with example cases."""
    try:
        result = init_skill(path, runner=runner, force=force)
    except SkilltestError as exc:
        raise fail(exc) from exc
    for created in result.created:
        console.print(f"[green]created[/] {created}")
    for warning in result.warnings:
        console.print(f"[yellow]warning:[/] {warning}")
    console.print(f"\nNext: edit {path / 'evals.yaml'}, then run [bold]skilltest run {path}[/]")


@app.command()
def run(
    path: Annotated[Path, typer.Argument(help="Skill folder or evals.yaml file.")] = Path("."),
    trials: Annotated[
        int | None, typer.Option("--trials", "-n", min=1, help="Override trials per case.")
    ] = None,
    case: Annotated[
        list[str] | None, typer.Option("--case", "-k", help="Only run this case (repeatable).")
    ] = None,
    parallel: Annotated[int, typer.Option("--parallel", "-p", min=1, help="Concurrent runs.")] = 4,
    report_format: Annotated[
        str, typer.Option("--format", "-f", help="terminal, md, html or json.")
    ] = "terminal",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the md/html/json report here.")
    ] = None,
    out: Annotated[Path, typer.Option(help="Where transcripts and results are saved.")] = Path(
        ".skilltest"
    ),
    keep_sandboxes: Annotated[
        bool, typer.Option("--keep-sandboxes", help="Save each run's final working dir.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Don't ask before an expensive run.")
    ] = False,
    confirm_above: Annotated[
        float, typer.Option(help="Ask for confirmation above this estimated cost (USD).")
    ] = CONFIRM_ABOVE_USD,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show the plan and cost estimate, run nothing.")
    ] = False,
    min_lift: Annotated[
        float | None,
        typer.Option(help="Exit 1 if the lift is below this many percentage points (CI gate)."),
    ] = None,
    min_trigger_rate: Annotated[
        float | None,
        typer.Option(help="Exit 1 if the trigger rate is below this percentage (CI gate)."),
    ] = None,
) -> None:
    """Run the evals with and without the skill, and print a report."""
    check_format(report_format)
    options = RunOptions(
        parallel=parallel,
        out_dir=out,
        keep_sandboxes=keep_sandboxes,
        trials=trials,
        only_cases=case,
    )
    # Machine-readable output goes to stdout, so everything else goes to stderr.
    info = console if report_format == "terminal" else err_console
    try:
        config = load_config(path)
        check_placeholders(config)
        engine = Engine(config, options)
        plan = estimate(engine, out)
        info.print(f"[bold]plan:[/] {plan.describe()}", highlight=False)
        if dry_run:
            return
        confirm_cost(plan, confirm_above, yes)
        with Progress(
            TextColumn("[bold]running[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=info,
            transient=True,
        ) as progress:
            task = progress.add_task("runs", total=len(engine.jobs()))
            engine.on_trial = lambda _trial: progress.advance(task)
            suite = asyncio.run(engine.run())
        summary = write_reports(suite)
    except KeyboardInterrupt:
        saved = save_partial_reports(out)
        err_console.print(f"\n[yellow]interrupted.[/] Partial results: {saved}", highlight=False)
        raise typer.Exit(code=130) from None
    except RunAborted as exc:
        save_partial_reports(out)
        raise fail(exc) from exc
    except SkilltestError as exc:
        raise fail(exc) from exc
    emit(report_format, summary, suite, output)
    gate(summary, min_lift, min_trigger_rate)


def check_placeholders(config: EvalConfig) -> None:
    """Refuse to pay for running the TODO examples that `skilltest init` writes."""
    for case in config.cases:
        texts = [case.prompt, *(str(a.model_dump()) for a in case.assertions)]
        if any("TODO" in text for text in texts):
            raise SkilltestError(
                f"Case {case.name!r} still has TODO placeholders from `skilltest init`.",
                hint=f"Write a real prompt and assertions in {config.path}, then run again.",
            )


def confirm_cost(plan: Estimate, confirm_above: float, yes: bool) -> None:
    total = plan.total_usd
    if yes or total is None or total <= confirm_above:
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        if typer.confirm(f"This may cost about ${total:.2f}. Continue?", default=False):
            return
        raise typer.Exit(code=1)
    raise fail(
        SkilltestError(
            f"Estimated cost ~${total:.2f} is above ${confirm_above:.2f}.",
            hint="Pass --yes to run anyway, lower --trials, or raise --confirm-above.",
        )
    )


def save_partial_reports(out: Path) -> str:
    """After an interruption, render reports for whatever finished."""
    try:
        suite = load_suite(find_latest_run(out))
        write_reports(suite)
        return f"{suite.run_dir}/report.html"
    except (SkilltestError, OSError, ValueError):
        return str(out / "runs")


def gate(summary: Summary, min_lift: float | None, min_trigger_rate: float | None) -> None:
    """CI gates: exit 1 when the skill doesn't meet the bar."""
    failures = []
    if min_lift is not None:
        if summary.lift is None:
            failures.append("lift could not be measured (no graded runs)")
        elif summary.lift * 100 < min_lift:
            failures.append(f"lift {summary.lift * 100:+.0f}% is below --min-lift {min_lift:+g}%")
    if min_trigger_rate is not None:
        rate = summary.trigger_rate
        if rate is None:
            failures.append("trigger rate could not be measured with this runner")
        elif rate * 100 < min_trigger_rate:
            failures.append(
                f"trigger rate {rate * 100:.0f}% is below --min-trigger-rate {min_trigger_rate:g}%"
            )
    for failure in failures:
        err_console.print(f"[bold red]gate failed:[/] {failure}", highlight=False)
    if failures:
        raise typer.Exit(code=1)


@app.command()
def report(
    path: Annotated[
        Path | None,
        typer.Argument(help="A run directory or results.json. Default: the latest run."),
    ] = None,
    report_format: Annotated[
        str, typer.Option("--format", "-f", help="terminal, md, html or json.")
    ] = "terminal",
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the md/html/json report here.")
    ] = None,
    out: Annotated[Path, typer.Option(help="Where runs are saved.")] = Path(".skilltest"),
) -> None:
    """Re-render the report for a saved run, without running anything."""
    check_format(report_format)
    try:
        suite = load_suite(path if path is not None else find_latest_run(out))
    except SkilltestError as exc:
        raise fail(exc) from exc
    summary = write_reports(suite)  # refresh the saved reports with this version
    emit(report_format, summary, suite, output)


@app.command()
def badge(
    path: Annotated[Path, typer.Argument(help="Skill folder (or its evals.yaml).")] = Path("."),
    endpoint: Annotated[
        bool, typer.Option("--json", help="Print shields.io endpoint JSON instead of markdown.")
    ] = False,
    out: Annotated[Path, typer.Option(help="Where runs are saved.")] = Path(".skilltest"),
) -> None:
    """Print a shields.io badge for the skill's latest run."""
    try:
        skill_path = load_config(path).skill
    except SkilltestError:
        skill_path = path.resolve()
    try:
        summary = build_summary(load_suite(find_latest_run(out, skill_path)))
    except SkilltestError as exc:
        raise fail(exc) from exc
    print(badges.endpoint_json(summary) if endpoint else badges.markdown(summary))


def check_format(report_format: str) -> None:
    if report_format not in FORMATS:
        raise fail(
            SkilltestError(
                f"Unknown report format {report_format!r}.",
                hint=f"Use one of: {', '.join(FORMATS)}.",
            )
        )


def emit(report_format: str, summary: Summary, suite: SuiteResult, output: Path | None) -> None:
    """Show or write the report in the requested format."""
    if report_format == "terminal":
        terminal.render(summary, console)
        return
    text = render_text(report_format, summary, suite)
    if output is None and report_format == "html":
        output = Path(suite.run_dir) / "report.html"
    if output is None:
        sys.stdout.write(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    err_console.print(f"wrote {output}", highlight=False)


ISSUES_URL = "https://github.com/akhilgarg07/skilltest/issues"


def main() -> None:
    """Console entry point: user errors get a fix-it message, bugs get a bug report link."""
    try:
        app()
    except Exception as exc:
        if os.environ.get("SKILLTEST_DEBUG"):
            raise
        err_console.print(
            f"[bold red]skilltest crashed:[/] {type(exc).__name__}: {exc}\n"
            f"This is a bug in skilltest, not in your skill. Re-run with SKILLTEST_DEBUG=1 for "
            f"the traceback and please report it at {ISSUES_URL}",
            highlight=False,
        )
        sys.exit(70)


if __name__ == "__main__":
    main()
