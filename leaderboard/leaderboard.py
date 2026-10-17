"""Run skilltest against a list of skills and render a markdown leaderboard.

    python leaderboard/leaderboard.py run              # every entry in skills.yaml
    python leaderboard/leaderboard.py run --only pdf   # one entry
    python leaderboard/leaderboard.py render           # results/*.json -> LEADERBOARD.md

Each entry in skills.yaml points at a skill (a git repo + folder, or a local
folder) and at an evals file in leaderboard/evals/. The evals always come from
this folder, never from the repo being tested, so a third-party repo can't run
`command` assertions on your machine. The skill's own files are still read by
the agent, so run the leaderboard in a disposable machine or container.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from skilltest.config import parse_config
from skilltest.engine import Engine, RunOptions
from skilltest.errors import SkilltestError
from skilltest.estimate import CONFIRM_ABOVE_USD, estimate
from skilltest.report import Summary, write_reports
from skilltest.report.format import fraction, interval, signed_pct

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CACHE = HERE / ".cache"  # clones and run transcripts (git-ignored)
RESULTS = HERE / "results"  # one JSON per entry (commit these)
OUTPUT = HERE / "LEADERBOARD.md"

VERDICT_RANK = {"helps": 0, "no clear effect": 1, "too few runs": 2, "not measured": 3, "hurts": 4}
VERDICT_LABEL = {
    "helps": "✅ helps",
    "no clear effect": "➖ no clear effect",
    "too few runs": "➖ too few runs",
    "not measured": "➖ not measured",
    "hurts": "❌ hurts",
}


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    evals: str  # relative to leaderboard/
    path: str = "."  # skill folder inside the repo (or relative to the repo root if local)
    repo: str | None = None  # git URL; omit for a skill in this repository
    ref: str | None = None  # branch or tag; default branch if omitted
    url: str | None = None  # link shown in the table

    @property
    def link(self) -> str | None:
        if self.url:
            return self.url
        if self.repo and self.repo.startswith("https://github.com/"):
            return f"{self.repo.removesuffix('.git')}/tree/{self.ref or 'HEAD'}/{self.path}"
        return None


class Result(BaseModel):
    entry: Entry
    ran_at: datetime
    summary: Summary


def load_entries(path: Path = HERE / "skills.yaml") -> list[Entry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Entry.model_validate(item) for item in data.get("skills", [])]


def fetch(entry: Entry) -> Path:
    """Return the skill folder, cloning the repo (shallow) when needed."""
    if entry.repo is None:
        return (REPO_ROOT / entry.path).resolve()
    dest = CACHE / "repos" / entry.name
    if not dest.exists():
        cmd = ["git", "clone", "--quiet", "--depth", "1"]
        if entry.ref:
            cmd += ["--branch", entry.ref]
        subprocess.run([*cmd, entry.repo, str(dest)], check=True)
    return (dest / entry.path).resolve()


def build_engine(entry: Entry, args: argparse.Namespace) -> Engine:
    evals_path = (HERE / entry.evals).resolve()
    data = yaml.safe_load(evals_path.read_text(encoding="utf-8"))
    data["skill"] = str(fetch(entry))  # our evals, their skill
    config = parse_config(data, evals_path.parent, source=entry.evals)
    config._path = evals_path
    options = RunOptions(parallel=args.parallel, trials=args.trials, out_dir=CACHE / ".skilltest")
    return Engine(config, options)


def run_entry(entry: Entry, args: argparse.Namespace) -> Result | None:
    """Run one entry; returns None for --dry-run."""
    engine = build_engine(entry, args)
    plan = estimate(engine, engine.options.out_dir)
    print(f"{entry.name}: {plan.describe()}")
    if args.dry_run:
        return None
    total = plan.total_usd or 0
    if total > args.confirm_above and not args.yes:
        raise SkilltestError(
            f"{entry.name}: estimated ~${total:.2f} is above ${args.confirm_above:.2f}.",
            hint="Pass --yes to run anyway, or lower --trials.",
        )
    suite = asyncio.run(engine.run())
    return Result(entry=entry, ran_at=datetime.now(timezone.utc), summary=write_reports(suite))


def render(results: list[Result]) -> str:
    rows = sorted(
        results,
        key=lambda r: (VERDICT_RANK[r.summary.verdict], -(r.summary.lift or 0), r.entry.name),
    )
    lines = [
        "# Skill leaderboard",
        "",
        "Each skill was run with and without the skill installed, on the same tasks, by",
        "[skilltest](https://github.com/akhilgarg07/skilltest). **Lift** is pass rate with",
        "the skill minus pass rate without it, with a 95% confidence interval.",
        "",
        "| # | skill | verdict | lift (95% CI) | triggered | tokens Δ | cost Δ | runs | agent |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rank, result in enumerate(rows, start=1):
        s, e = result.summary, result.entry
        name = f"[{e.name}]({e.link})" if e.link else e.name
        agent = s.runner + (f" · {s.model}" if s.model else "")
        if s.approximate:
            agent += " (approx.)"
        runs = min(s.with_skill.runs, s.without_skill.runs)
        lines.append(
            f"| {rank} | {name} | {VERDICT_LABEL[s.verdict]} | "
            f"{signed_pct(s.lift)} ({interval(s.lift_ci)}) | "
            f"{fraction(s.triggers, s.trigger_runs)} | {signed_pct(s.token_delta)} | "
            f"{signed_pct(s.cost_delta)} | {runs}/variant | {agent} |"
        )
    dates = sorted(r.ran_at.date().isoformat() for r in results)
    span = f"{dates[0]} to {dates[-1]}" if dates and dates[0] != dates[-1] else "".join(dates[:1])
    lines += [
        "",
        f"Runs: {span}. The tasks for each skill are in [`leaderboard/evals/`](evals/); "
        "results with few runs per variant are noisy. Numbers measure these tasks with this "
        "agent, not the skill in general.",
        "",
    ]
    return "\n".join(lines)


def load_results(directory: Path | None = None) -> list[Result]:
    directory = directory or RESULTS
    return [
        Result.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run skilltest for entries in skills.yaml.")
    run.add_argument("--only", action="append", help="Entry name (repeatable).")
    run.add_argument("--trials", type=int, help="Override trials per case.")
    run.add_argument("--parallel", type=int, default=4)
    run.add_argument("--confirm-above", type=float, default=CONFIRM_ABOVE_USD)
    run.add_argument("--yes", action="store_true", help="Don't stop at the cost threshold.")
    run.add_argument("--dry-run", action="store_true", help="Print each plan, run nothing.")
    sub.add_parser("render", help="Render LEADERBOARD.md from results/.")
    args = parser.parse_args(argv)

    if args.command == "run":
        entries = [e for e in load_entries() if not args.only or e.name in args.only]
        if not entries:
            print("No matching entries in leaderboard/skills.yaml.", file=sys.stderr)
            return 2
        RESULTS.mkdir(exist_ok=True)
        for entry in entries:
            try:
                result = run_entry(entry, args)
            except SkilltestError as exc:
                print(f"error: {exc.message}\nfix: {exc.hint or ''}", file=sys.stderr)
                return 2
            if result is None:
                continue
            (RESULTS / f"{entry.name}.json").write_text(result.model_dump_json(indent=2))
            print(f"{entry.name}: {result.summary.verdict}, lift {signed_pct(result.summary.lift)}")

        if args.dry_run:
            return 0

    OUTPUT.write_text(render(load_results()), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
