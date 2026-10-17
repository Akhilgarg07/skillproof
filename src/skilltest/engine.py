"""Runs an eval suite: every case, N trials, with and without the skill.

Each run gets a fresh sandbox (fixtures copied in), the runner does its thing,
assertions are checked against the sandbox, and the transcript is saved under
`<out_dir>/runs/<timestamp>/` with secrets redacted.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from skilltest.assertions import CheckContext, check_all
from skilltest.config import Case, EvalConfig
from skilltest.errors import ConfigError
from skilltest.judges import Judge, make_judge
from skilltest.judges.base import JudgeUnavailable
from skilltest.results import CaseResult, SuiteResult, TrialResult, Variant
from skilltest.runners import AgentRun, Runner, RunRequest, get_runner
from skilltest.sandbox import create_sandbox, redact, remove_sandbox
from skilltest.skill import Skill, load_skill

VARIANTS: tuple[Variant, ...] = ("with", "without")


@dataclass
class RunOptions:
    parallel: int = 1
    out_dir: Path = Path(".skilltest")
    keep_sandboxes: bool = False
    trials: int | None = None  # overrides evals.yaml for every case
    only_cases: list[str] | None = None  # run just these case names


@dataclass
class Job:
    case: Case
    variant: Variant
    trial: int


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "case"


def new_run_dir(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = out_dir / "runs" / stamp
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = out_dir / "runs" / f"{stamp}-{suffix}"
    run_dir.mkdir(parents=True)
    return run_dir


def selected_cases(config: EvalConfig, only: list[str] | None) -> list[Case]:
    if not only:
        return list(config.cases)
    names = {c.name for c in config.cases}
    unknown = [n for n in only if n not in names]
    if unknown:
        raise ConfigError(
            f"No case named {unknown[0]!r}",
            hint="Available cases: " + ", ".join(repr(n) for n in names),
        )
    return [c for c in config.cases if c.name in only]


class Engine:
    def __init__(
        self,
        config: EvalConfig,
        options: RunOptions | None = None,
        runner: Runner | None = None,
        judge: Judge | None = None,
        on_trial: Callable[[TrialResult], None] | None = None,
    ) -> None:
        self.config = config
        self.options = options or RunOptions()
        self.runner = runner or get_runner(config.runner, config.runner_options)
        self.judge = judge
        self.on_trial = on_trial
        self.cases = selected_cases(config, self.options.only_cases)

    def jobs(self) -> list[Job]:
        """Trials are interleaved (with/without, case by case) so drift over time
        in API latency or model behaviour hits both variants equally."""
        jobs = []
        max_trials = max(self.trials_for(c) for c in self.cases)
        for trial in range(max_trials):
            for case in self.cases:
                if trial < self.trials_for(case):
                    jobs.extend(Job(case, variant, trial) for variant in VARIANTS)
        return jobs

    def trials_for(self, case: Case) -> int:
        return self.options.trials or self.config.trials_for(case)

    def skill_exclude(self, skill: Skill) -> list[Path]:
        """Eval files inside the skill folder that the agent must never see."""
        paths = [c.fixtures for c in self.config.cases if c.fixtures is not None]
        if self.config.path is not None:
            paths.append(self.config.path)
        return [p for p in paths if p.is_relative_to(skill.path)]

    async def run(self) -> SuiteResult:
        skill = load_skill(self.config.skill)
        self.runner.check_ready()
        if self.judge is None and self.config.uses_judge():
            self.judge = make_judge(self.config.judge, self.runner.vendor)

        run_dir = new_run_dir(self.options.out_dir)
        suite = SuiteResult(
            skill_name=skill.name,
            skill_path=str(skill.path),
            runner=self.runner.name,
            approximate=self.runner.approximate,
            model=self.config.model,
            judge=self.judge.label if self.judge else None,
            started_at=datetime.now(timezone.utc),
            run_dir=str(run_dir),
        )
        exclude = self.skill_exclude(skill)
        semaphore = asyncio.Semaphore(max(1, self.options.parallel))

        async def limited(job: Job) -> TrialResult:
            async with semaphore:
                return await self.run_trial(job, skill, exclude, run_dir)

        trials = await asyncio.gather(*(limited(job) for job in self.jobs()))

        for case in self.cases:
            case_trials = sorted(
                (t for t in trials if t.case == case.name), key=lambda t: (t.variant, t.trial)
            )
            suite.cases.append(
                CaseResult(
                    name=case.name,
                    should_trigger=case.should_trigger,
                    has_assertions=bool(case.assertions),
                    trials=case_trials,
                )
            )
        suite.finished_at = datetime.now(timezone.utc)
        (run_dir / "results.json").write_text(
            redact(suite.model_dump_json(indent=2)), encoding="utf-8"
        )
        return suite

    async def run_trial(
        self, job: Job, skill: Skill, exclude: list[Path], run_dir: Path
    ) -> TrialResult:
        case = job.case
        timeout = self.config.timeout_for(case)
        workdir = create_sandbox(case.fixtures)
        try:
            request = RunRequest(
                prompt=case.prompt,
                workdir=workdir,
                skill=skill if job.variant == "with" else None,
                skill_exclude=exclude,
                model=self.config.model,
                timeout_s=timeout,
                case_name=case.name,
                trial=job.trial,
            )
            agent_run = await self.call_runner(request, timeout)
            assertions = []
            if agent_run.error is None:  # don't grade (or pay a judge for) a broken run
                ctx = CheckContext(run=agent_run, workdir=workdir, judge=self.judge)
                try:
                    assertions = await check_all(case.assertions, ctx)
                except JudgeUnavailable as exc:
                    agent_run.error = f"llm_judge failed: {exc}"
            result = TrialResult(
                case=case.name,
                variant=job.variant,
                trial=job.trial,
                run=agent_run,
                assertions=assertions,
            )
            self.save_trial(result, workdir, run_dir)
        finally:
            remove_sandbox(workdir)
        if self.on_trial is not None:
            self.on_trial(result)
        return result

    async def call_runner(self, request: RunRequest, timeout: float) -> AgentRun:
        """Call the runner, enforcing the timeout and turning crashes into errors."""
        start = time.monotonic()
        try:
            agent_run = await asyncio.wait_for(self.runner.run(request), timeout=timeout)
        except asyncio.TimeoutError:
            agent_run = AgentRun(timed_out=True)
        except Exception as exc:
            agent_run = AgentRun(error=f"{type(exc).__name__}: {exc}")
        if not agent_run.duration_s:
            agent_run.duration_s = time.monotonic() - start
        return agent_run

    def save_trial(self, result: TrialResult, workdir: Path, run_dir: Path) -> None:
        case_dir = run_dir / slugify(result.case)
        case_dir.mkdir(parents=True, exist_ok=True)
        name = f"{result.variant}-{result.trial + 1}"
        result.artifact = f"{case_dir.name}/{name}.json"
        (case_dir / f"{name}.json").write_text(
            redact(result.model_dump_json(indent=2)), encoding="utf-8"
        )
        if self.options.keep_sandboxes:
            shutil.copytree(workdir, case_dir / f"{name}.workdir", symlinks=True)


def run_suite(
    config: EvalConfig,
    options: RunOptions | None = None,
    runner: Runner | None = None,
    judge: Judge | None = None,
    on_trial: Callable[[TrialResult], None] | None = None,
) -> SuiteResult:
    """Synchronous entry point used by the CLI and tests."""
    engine = Engine(config, options, runner=runner, judge=judge, on_trial=on_trial)
    return asyncio.run(engine.run())
