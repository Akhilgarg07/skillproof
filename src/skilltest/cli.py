"""The `skilltest` command line."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn

from skilltest import __version__
from skilltest.config import load_config
from skilltest.engine import Engine, RunOptions
from skilltest.errors import SkilltestError
from skilltest.report import terminal
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

REPORT_FORMATS = ("terminal",)


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
def main(
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
    parallel: Annotated[int, typer.Option("--parallel", "-p", min=1, help="Concurrent runs.")] = 1,
    report_format: Annotated[
        str, typer.Option("--format", "-f", help="Report format: terminal.")
    ] = "terminal",
    out: Annotated[Path, typer.Option(help="Where transcripts and results are saved.")] = Path(
        ".skilltest"
    ),
    keep_sandboxes: Annotated[
        bool, typer.Option("--keep-sandboxes", help="Save each run's final working dir.")
    ] = False,
) -> None:
    """Run the evals with and without the skill, and print a report."""
    if report_format not in REPORT_FORMATS:
        raise fail(
            SkilltestError(
                f"Unknown report format {report_format!r}.",
                hint=f"Use one of: {', '.join(REPORT_FORMATS)}.",
            )
        )
    options = RunOptions(
        parallel=parallel,
        out_dir=out,
        keep_sandboxes=keep_sandboxes,
        trials=trials,
        only_cases=case,
    )
    try:
        config = load_config(path)
        engine = Engine(config, options)
        total = len(engine.jobs())
        with Progress(
            TextColumn("[bold]running[/]"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("runs", total=total)
            engine.on_trial = lambda _trial: progress.advance(task)
            suite = asyncio.run(engine.run())
    except SkilltestError as exc:
        raise fail(exc) from exc
    terminal.render(suite, console)


@app.command()
def badge(
    path: Annotated[Path, typer.Argument(help="Skill folder.")] = Path("."),
) -> None:
    """Print a shields.io badge (markdown) from the latest run."""
    raise fail(
        SkilltestError(
            "`skilltest badge` is not implemented yet.",
            hint="It lands with the reports in phase 3.",
        )
    )


if __name__ == "__main__":
    app()
