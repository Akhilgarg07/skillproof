from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from skillproof.assertions import Assertion, BaseAssertion, CheckContext, check_all
from skillproof.judges import MockJudge
from skillproof.runners import AgentRun, Usage

adapter = TypeAdapter(Assertion)


def check(spec: dict, run: AgentRun, workdir: Path, judge=None):
    assertion = adapter.validate_python(spec)
    return asyncio.run(assertion.check(CheckContext(run=run, workdir=workdir, judge=judge)))


@pytest.fixture
def run() -> AgentRun:
    return AgentRun(
        final_text="The root cause is a NullPointerException on line 42.",
        usage=Usage(input_tokens=900, output_tokens=100, cache_read_tokens=500),
    )


@pytest.mark.parametrize(
    ("spec", "passed"),
    [
        ({"type": "contains", "value": "nullpointerexception"}, True),
        ({"type": "contains", "value": "nullpointerexception", "case_sensitive": True}, False),
        ({"type": "contains", "value": "IndexError"}, False),
        ({"type": "not_contains", "value": "IndexError"}, True),
        ({"type": "not_contains", "value": "root cause"}, False),
        ({"type": "regex", "pattern": r"line \d+"}, True),
        ({"type": "regex", "pattern": r"^Error"}, False),
        ({"type": "max_tokens", "value": 1500}, True),
        ({"type": "max_tokens", "value": 1499}, False),
    ],
)
def test_text_and_budget_assertions(
    spec: dict, passed: bool, run: AgentRun, tmp_path: Path
) -> None:
    result = check(spec, run, tmp_path)
    assert result.passed is passed
    assert result.type == spec["type"]
    assert result.message


def test_file_assertions(run: AgentRun, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "fix.patch").write_text("--- a/Foo.java\n+++ b/Foo.java")
    assert check({"type": "file_exists", "path": "sub/fix.patch"}, run, tmp_path).passed
    assert not check({"type": "file_exists", "path": "nope.txt"}, run, tmp_path).passed
    assert check(
        {"type": "file_contains", "path": "sub/fix.patch", "value": "foo.java"}, run, tmp_path
    ).passed
    assert not check(
        {"type": "file_contains", "path": "sub/fix.patch", "value": "Bar"}, run, tmp_path
    ).passed
    missing = check({"type": "file_contains", "path": "x.txt", "value": "a"}, run, tmp_path)
    assert not missing.passed
    assert "not created" in missing.message


def test_command_runs_in_sandbox(run: AgentRun, tmp_path: Path) -> None:
    (tmp_path / "marker").write_text("")
    assert check({"type": "command", "run": "test -f marker"}, run, tmp_path).passed
    failed = check({"type": "command", "run": "echo boom; exit 3"}, run, tmp_path)
    assert not failed.passed
    assert "exited 3" in failed.message
    assert "boom" in failed.message


def test_command_does_not_see_api_keys(
    run: AgentRun, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value-123")
    monkeypatch.setenv("PLAIN_SETTING", "visible")
    assert check(
        {"type": "command", "run": 'test -z "$ANTHROPIC_API_KEY" && test -n "$PLAIN_SETTING"'},
        run,
        tmp_path,
    ).passed


def test_command_timeout(run: AgentRun, tmp_path: Path) -> None:
    result = check({"type": "command", "run": "sleep 5", "timeout": 0.2}, run, tmp_path)
    assert not result.passed
    assert "timed out" in result.message


def test_llm_judge(run: AgentRun, tmp_path: Path) -> None:
    judge = MockJudge(pass_if=["root cause"])
    spec = {"type": "llm_judge", "rubric": "States the root cause."}
    assert check(spec, run, tmp_path, judge=judge).passed
    assert judge.calls == [("States the root cause.", run.final_text)]
    assert not check(spec, run.model_copy(update={"final_text": "dunno"}), tmp_path, judge).passed


def test_llm_judge_without_judge_fails(run: AgentRun, tmp_path: Path) -> None:
    result = check({"type": "llm_judge", "rubric": "x"}, run, tmp_path)
    assert not result.passed
    assert "no judge" in result.message


def test_crashing_assertion_is_a_failure(run: AgentRun, tmp_path: Path) -> None:
    class Broken(BaseAssertion):
        type: str = "broken"

        async def check(self, ctx: CheckContext):
            raise RuntimeError("kaboom")

    results = asyncio.run(check_all([Broken()], CheckContext(run=run, workdir=tmp_path)))
    assert not results[0].passed
    assert "kaboom" in results[0].message
