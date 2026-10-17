from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from skillproof.config import JudgeConfig, load_config
from skillproof.engine import RunOptions, run_suite
from skillproof.errors import JudgeNotReady
from skillproof.judges import make_judge, resolve_provider
from skillproof.judges.anthropic_judge import DEFAULT_MODEL, AnthropicJudge
from skillproof.judges.base import Judge, JudgeUnavailable, Verdict, judge_prompt, parse_verdict


@pytest.mark.parametrize(
    ("provider", "agent_vendor", "expected"),
    [
        ("auto", "anthropic", "openai"),
        ("auto", "openai", "anthropic"),
        ("auto", "mock", "anthropic"),
        ("anthropic", "anthropic", "anthropic"),  # explicit choice wins
    ],
)
def test_auto_picks_a_different_vendor(provider, agent_vendor, expected) -> None:
    assert resolve_provider(JudgeConfig(provider=provider), agent_vendor) == expected


def test_judge_prompt_contains_rubric_and_answer() -> None:
    prompt = judge_prompt("States the root cause.", "It is a NullPointerException.")
    assert "<rubric>\nStates the root cause.\n</rubric>" in prompt
    assert "It is a NullPointerException." in prompt
    assert "(empty)" in judge_prompt("x", "  ")


def test_parse_verdict() -> None:
    assert parse_verdict('{"passed": true, "reason": "ok"}') == Verdict(passed=True, reason="ok")
    with pytest.raises(JudgeUnavailable):
        parse_verdict("PASS: looks fine")


class FakeMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.kwargs: dict = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_anthropic(text: str, stop_reason: str = "end_turn") -> AnthropicJudge:
    judge = AnthropicJudge.__new__(AnthropicJudge)
    judge.model = DEFAULT_MODEL
    response = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )
    judge.client = SimpleNamespace(messages=FakeMessages(response))
    return judge


def test_anthropic_judge_requests_structured_verdict() -> None:
    judge = fake_anthropic('{"passed": false, "reason": "no root cause"}')
    verdict = asyncio.run(judge.grade("States the root cause.", "dunno"))
    assert verdict == Verdict(passed=False, reason="no root cause")
    kwargs = judge.client.messages.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "dunno" in kwargs["messages"][0]["content"]


def test_anthropic_judge_refusal_is_unavailable() -> None:
    with pytest.raises(JudgeUnavailable, match="refused"):
        asyncio.run(fake_anthropic("", stop_reason="refusal").grade("r", "a"))


def test_missing_api_key_env(monkeypatch) -> None:
    monkeypatch.delenv("MY_JUDGE_KEY", raising=False)
    with pytest.raises(JudgeNotReady, match="MY_JUDGE_KEY"):
        make_judge(JudgeConfig(provider="anthropic", api_key_env="MY_JUDGE_KEY"), "openai")


def test_make_anthropic_judge(monkeypatch) -> None:
    monkeypatch.setenv("MY_JUDGE_KEY", "sk-test")
    judge = make_judge(
        JudgeConfig(provider="anthropic", model="claude-sonnet-5-5", api_key_env="MY_JUDGE_KEY"),
        "openai",
    )
    assert isinstance(judge, AnthropicJudge)
    assert judge.label == "anthropic:claude-sonnet-5-5"


def test_judge_failure_marks_run_errored(write_evals, tmp_path: Path) -> None:
    class Broken(Judge):
        name = vendor = "broken"

        async def grade(self, rubric: str, response: str) -> Verdict:
            raise JudgeUnavailable("judge API error: 529")

    case = {"name": "j", "prompt": "p", "assert": [{"type": "llm_judge", "rubric": "ok"}]}
    config = load_config(write_evals({"trials": 1, "cases": [case]}))
    suite = run_suite(config, RunOptions(out_dir=tmp_path / "out"), judge=Broken())
    trials = suite.cases[0].trials
    assert all(t.errored for t in trials)
    assert trials[0].run.error == "llm_judge failed: judge API error: 529"


def test_openai_judge_uses_responses_api_with_schema(monkeypatch) -> None:
    from skillproof.judges.openai_judge import OpenAIJudge

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    judge = OpenAIJudge()
    assert judge.model == "gpt-6.1-sol"

    class FakeResponses:
        kwargs: ClassVar[dict] = {}

        async def create(self, **kwargs):
            FakeResponses.kwargs = kwargs
            return SimpleNamespace(output_text='{"passed": true, "reason": "states it"}')

    judge.client = SimpleNamespace(responses=FakeResponses())
    verdict = asyncio.run(judge.grade("States the root cause.", "NPE on line 3"))
    assert verdict.passed
    fmt = FakeResponses.kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert "NPE on line 3" in FakeResponses.kwargs["input"]


def test_openai_judge_needs_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeNotReady, match="OPENAI_API_KEY"):
        make_judge(JudgeConfig(provider="auto"), "anthropic")  # claude agent -> openai judge
