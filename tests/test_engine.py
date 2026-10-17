from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from skilltest.config import load_config
from skilltest.engine import Engine, RunOptions, run_suite
from skilltest.errors import ConfigError, RunAborted, RunnerNotReady
from skilltest.judges import MockJudge
from skilltest.results import load_suite
from skilltest.runners import AgentRun, Runner, RunRequest
from skilltest.runners.mock import MockRunner
from skilltest.stats import suite_stats

CASES = [
    {
        "name": "explain",
        "prompt": "What's wrong in error.log?",
        "fixtures": "./fixtures/case1",
        "assert": [
            {"type": "contains", "value": "NullPointerException"},
            {"type": "file_exists", "path": "fix.patch"},
        ],
    },
    {
        "name": "unrelated",
        "prompt": "Capital of France?",
        "should_trigger": False,
        "assert": [{"type": "contains", "value": "Paris"}],
    },
]

SCRIPT = {
    "cases": {
        "explain": {
            "with": {"text": "NullPointerException", "files": {"fix.patch": "x"}},
            "without": {"text": "No idea", "output_tokens": 600},
        },
        "unrelated": {"with": {"text": "Paris", "triggered": False}, "without": {"text": "Paris"}},
    }
}


@pytest.fixture
def config(write_evals):
    return load_config(write_evals({"trials": 3, "runner_options": SCRIPT, "cases": CASES}))


def options(tmp_path: Path, **kw) -> RunOptions:
    return RunOptions(out_dir=tmp_path / ".skilltest", **kw)


def test_runs_every_case_with_and_without(config, tmp_path: Path) -> None:
    runner = MockRunner(SCRIPT)
    suite = run_suite(config, options(tmp_path), runner=runner)

    assert len(runner.requests) == 2 * 2 * 3
    with_skill = [r for r in runner.requests if r.skill is not None]
    baseline = [r for r in runner.requests if r.skill is None]
    assert len(with_skill) == len(baseline) == 6
    assert {r.skill.name for r in with_skill} == {"stack-trace-explainer"}

    explain = suite.cases[0]
    assert [t.passed for t in explain.variant("with")] == [True] * 3
    assert [t.passed for t in explain.variant("without")] == [False] * 3

    stats = suite_stats(suite)
    assert stats.lift == pytest.approx(1.0)  # headline pools should_trigger cases only
    assert stats.triggers == 3 and stats.trigger_runs == 3
    assert stats.false_triggers == 0 and stats.false_trigger_runs == 3


def test_each_run_gets_a_fresh_sandbox(config, tmp_path: Path) -> None:
    seen: list[Path] = []

    class Inspecting(MockRunner):
        async def run(self, request: RunRequest) -> AgentRun:
            seen.append(request.workdir)
            if request.case_name == "explain":
                assert (request.workdir / "error.log").is_file()
                assert not (request.workdir / "fix.patch").exists()  # not leaked from another run
            assert request.workdir.resolve() != Path.cwd().resolve()
            return await super().run(request)

    run_suite(config, options(tmp_path, parallel=4), runner=Inspecting(SCRIPT))
    assert len(set(seen)) == len(seen) == 12
    assert not any(p.exists() for p in seen)  # cleaned up


def test_skill_exclude_hides_eval_files(config, skill_dir: Path, tmp_path: Path) -> None:
    runner = MockRunner(SCRIPT)
    run_suite(config, options(tmp_path), runner=runner)
    exclude = runner.requests[0].skill_exclude
    assert (skill_dir / "evals.yaml").resolve() in exclude
    assert (skill_dir / "fixtures" / "case1").resolve() in exclude


def test_trials_are_interleaved(config, tmp_path: Path) -> None:
    runner = MockRunner(SCRIPT)
    run_suite(config, options(tmp_path), runner=runner)
    order = [(r.trial, r.case_name, r.skill is not None) for r in runner.requests[:4]]
    assert order == [
        (0, "explain", True),
        (0, "explain", False),
        (0, "unrelated", True),
        (0, "unrelated", False),
    ]


def test_saves_transcripts_and_results(config, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-be-saved")
    script = {"default": {"with": {"text": "key is sk-should-never-be-saved"}}}
    suite = run_suite(config, options(tmp_path, trials=1), runner=MockRunner(script))

    run_dir = Path(suite.run_dir)
    assert run_dir.parent == tmp_path / ".skilltest" / "runs"
    files = sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*.json"))
    assert files == [
        "explain/with-1.json",
        "explain/without-1.json",
        "results.json",
        "unrelated/with-1.json",
        "unrelated/without-1.json",
    ]
    saved = json.loads((run_dir / "explain" / "with-1.json").read_text())
    assert saved["run"]["final_text"] == "key is ***"
    assert "sk-should-never-be-saved" not in (run_dir / "results.json").read_text()
    assert suite.cases[0].trials[0].artifact == "explain/with-1.json"


def test_keep_sandboxes(config, tmp_path: Path) -> None:
    suite = run_suite(
        config, options(tmp_path, trials=1, keep_sandboxes=True), runner=MockRunner(SCRIPT)
    )
    kept = Path(suite.run_dir) / "explain" / "with-1.workdir"
    assert (kept / "fix.patch").is_file()
    assert (kept / "error.log").is_file()


def test_timeout_counts_as_failure(write_evals, tmp_path: Path) -> None:
    config = load_config(write_evals({"trials": 1, "timeout": 0.1, "cases": CASES[:1]}))

    class Slow(Runner):
        name, vendor = "slow", "mock"

        async def run(self, request: RunRequest) -> AgentRun:
            await asyncio.sleep(5)
            return AgentRun()

    suite = run_suite(config, options(tmp_path), runner=Slow())
    trial = suite.cases[0].trials[0]
    assert trial.run.timed_out and not trial.errored and not trial.passed
    assert suite_stats(suite).with_skill.runs == 1


def test_runner_crash_is_an_error_excluded_from_rates(write_evals, tmp_path: Path) -> None:
    config = load_config(write_evals({"trials": 2, "cases": CASES[:1]}))

    class Flaky(MockRunner):
        async def run(self, request: RunRequest) -> AgentRun:
            if request.skill is None and request.trial == 0:
                raise ConnectionError("API unreachable")
            return await super().run(request)

    suite = run_suite(config, options(tmp_path), runner=Flaky(SCRIPT))
    errored = [t for t in suite.cases[0].trials if t.errored]
    assert len(errored) == 1
    assert errored[0].run.error == "ConnectionError: API unreachable"
    stats = suite_stats(suite)
    assert stats.errors == 1
    assert stats.without_skill.runs == 1


def test_runner_not_ready_stops_before_running(config, tmp_path: Path) -> None:
    class NotReady(MockRunner):
        def check_ready(self) -> None:
            raise RunnerNotReady("no CLI", hint="install it")

    runner = NotReady(SCRIPT)
    with pytest.raises(RunnerNotReady):
        run_suite(config, options(tmp_path), runner=runner)
    assert runner.requests == []
    assert not (tmp_path / ".skilltest").exists()


def test_case_filter_and_trials_override(config, tmp_path: Path) -> None:
    runner = MockRunner(SCRIPT)
    suite = run_suite(config, options(tmp_path, trials=2, only_cases=["unrelated"]), runner=runner)
    assert [c.name for c in suite.cases] == ["unrelated"]
    assert len(runner.requests) == 4


def test_unknown_case_filter(config, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No case named 'nope'"):
        run_suite(config, options(tmp_path, only_cases=["nope"]))


def test_judge_built_from_config(write_evals, tmp_path: Path) -> None:
    case = {"name": "j", "prompt": "p", "assert": [{"type": "llm_judge", "rubric": "ok"}]}
    config = load_config(write_evals({"trials": 1, "judge": {"provider": "mock"}, "cases": [case]}))
    suite = run_suite(config, options(tmp_path))
    assert suite.judge == "mock"
    assert all(t.passed for t in suite.cases[0].trials)


def test_injected_judge_is_used(write_evals, tmp_path: Path) -> None:
    case = {"name": "j", "prompt": "p", "assert": [{"type": "llm_judge", "rubric": "ok"}]}
    config = load_config(write_evals({"trials": 1, "cases": [case]}))
    script = {"default": {"with": {"text": "great answer"}, "without": {"text": "meh"}}}
    suite = run_suite(
        config, options(tmp_path), runner=MockRunner(script), judge=MockJudge(["great"])
    )
    assert [t.passed for t in suite.cases[0].trials] == [True, False]


class AlwaysFails(MockRunner):
    async def run(self, request: RunRequest) -> AgentRun:
        self.requests.append(request)
        raise PermissionError("401 Unauthorized: invalid x-api-key")


def test_stops_early_when_every_run_fails(config, tmp_path: Path) -> None:
    runner = AlwaysFails(SCRIPT)
    with pytest.raises(RunAborted) as exc:
        run_suite(config, options(tmp_path, parallel=1), runner=runner)
    assert "first 3 runs all failed" in exc.value.message
    assert "401 Unauthorized" in exc.value.message
    assert "API key" in exc.value.hint
    assert len(runner.requests) == 3  # not all 12
    saved = load_suite(next((tmp_path / ".skilltest" / "runs").iterdir()))
    assert saved.complete is False
    assert sum(len(c.trials) for c in saved.cases) == 3


def test_no_early_stop_when_some_runs_succeed(config, tmp_path: Path) -> None:
    class FirstSucceeds(AlwaysFails):
        async def run(self, request: RunRequest) -> AgentRun:
            if not self.requests:
                self.requests.append(request)
                return AgentRun(final_text="ok")
            return await super().run(request)

    suite = run_suite(config, options(tmp_path, parallel=1), runner=FirstSucceeds(SCRIPT))
    assert suite.complete
    assert sum(t.errored for c in suite.cases for t in c.trials) == 11


def test_cancellation_saves_partial_results(config, tmp_path: Path) -> None:
    class SlowAfterFirst(MockRunner):
        async def run(self, request: RunRequest) -> AgentRun:
            if self.requests:
                await asyncio.sleep(30)
            return await super().run(request)

    async def interrupt() -> None:
        engine = Engine(config, options(tmp_path, parallel=1), runner=SlowAfterFirst(SCRIPT))
        task = asyncio.create_task(engine.run())
        await asyncio.sleep(0.3)  # first run finishes, second is stuck
        task.cancel()  # what Ctrl-C does under asyncio.run
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(interrupt())
    saved = load_suite(next((tmp_path / ".skilltest" / "runs").iterdir()))
    assert saved.complete is False
    assert sum(len(c.trials) for c in saved.cases) == 1
