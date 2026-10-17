"""Claude Code runner + parser. Uses recorded transcripts and a fake `query`; no API calls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import claude_agent_sdk
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from skillproof.parsers.claude_code import (
    is_skill_call,
    parse_error,
    parse_transcript,
    to_dict,
)
from skillproof.runners import RunRequest, ToolCall
from skillproof.runners.claude_code import ClaudeCodeRunner
from skillproof.skill import load_skill

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def test_parse_recorded_run_with_skill() -> None:
    run = parse_transcript(load("claude_code_with_skill.json"), "haiku-writer")
    assert run.triggered is True
    assert run.final_text.endswith("-- the skillproof bot")
    assert run.model == "claude-opus-5-5"
    assert run.num_turns == 3
    assert run.error is None and run.warnings == []
    assert [c.name for c in run.tool_calls] == ["Skill"]
    assert run.tool_calls[0].input["skill"] == "haiku-writer"
    assert run.tool_calls[0].output == "Launching skill: haiku-writer"
    assert run.usage.output_tokens == 132
    assert run.usage.cache_read_tokens == 39412
    assert run.usage.cost_usd == pytest.approx(0.0248664)
    assert run.duration_s == pytest.approx(3.077)


def test_parse_recorded_baseline() -> None:
    run = parse_transcript(load("claude_code_without_skill.json"), None)
    assert run.triggered is None  # no skill to trigger
    assert "Tidewords" in run.final_text
    assert run.tool_calls == []


def test_warns_when_skill_not_listed_at_startup() -> None:
    run = parse_transcript(load("claude_code_without_skill.json"), "haiku-writer")
    assert run.triggered is False
    assert "was not listed at startup" in run.warnings[0]


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (ToolCall(name="Skill", input={"skill": "pdf"}), True),
        (ToolCall(name="Skill", input={"skill": "my-plugin:pdf"}), True),
        (ToolCall(name="Skill", input={"skill": "pdf-extra"}), False),
        (ToolCall(name="Read", input={"file_path": "/x/.claude/skills/pdf/SKILL.md"}), True),
        (ToolCall(name="Bash", input={"command": "cat .claude/skills/pdf/SKILL.md"}), True),
        (ToolCall(name="Read", input={"file_path": "/x/notes.md"}), False),
    ],
)
def test_is_skill_call(call: ToolCall, expected: bool) -> None:
    assert is_skill_call(call, "pdf") is expected


@pytest.mark.parametrize(
    ("result", "error", "warnings"),
    [
        (None, "Claude Code ended without a result message", []),
        ({"is_error": False}, None, []),
        (
            {"is_error": True, "subtype": "error_max_turns"},
            None,
            ["stopped early: error_max_turns"],
        ),
        (
            {
                "is_error": True,
                "subtype": "success",
                "api_error_status": 529,
                "errors": ["overloaded"],
            },
            "API error 529: overloaded",
            [],
        ),
        (
            {"is_error": True, "subtype": "error_during_execution", "errors": ["boom"]},
            "Claude Code error (error_during_execution): boom",
            [],
        ),
    ],
)
def test_parse_error(result, error, warnings) -> None:
    assert parse_error(result) == (error, warnings)


def test_to_dict_tags_types_and_drops_signatures() -> None:
    message = AssistantMessage(
        content=[ThinkingBlock(thinking="hmm", signature="x" * 500), TextBlock(text="hi")],
        model="claude-opus-5-5",
    )
    data = to_dict(message)
    assert data["_type"] == "AssistantMessage"
    assert data["content"][0] == {"_type": "ThinkingBlock", "thinking": "hmm"}
    assert data["content"][1] == {"_type": "TextBlock", "text": "hi"}
    json.dumps(data)  # serializable


def result_message(text: str) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1500,
        duration_api_ms=1400,
        is_error=False,
        num_turns=2,
        session_id="s",
        total_cost_usd=0.01,
        usage={"input_tokens": 10, "output_tokens": 5},
        result=text,
    )


class FakeQuery:
    """Stands in for claude_agent_sdk.query and records the options it got."""

    def __init__(self, messages, raise_after: Exception | None = None) -> None:
        self.messages = messages
        self.raise_after = raise_after
        self.calls: list = []

    def __call__(self, *, prompt, options):
        self.calls.append((prompt, options))

        async def stream():
            for message in self.messages:
                yield message
            if self.raise_after:
                raise self.raise_after

        return stream()


@pytest.fixture
def request_for(skill_dir: Path, tmp_path: Path):
    (skill_dir / "evals.yaml").write_text("secret assertions")

    def make(with_skill: bool) -> RunRequest:
        workdir = tmp_path / ("with" if with_skill else "without")
        workdir.mkdir()
        return RunRequest(
            prompt="explain error.log",
            workdir=workdir,
            skill=load_skill(skill_dir) if with_skill else None,
            skill_exclude=[skill_dir / "evals.yaml", skill_dir / "fixtures"],
            model="claude-sonnet-5-5",
            timeout_s=60,
            case_name="c",
            trial=0,
        )

    return make


def test_runner_installs_skill_in_isolated_project(request_for, monkeypatch) -> None:
    init = SystemMessage(
        subtype="init", data={"model": "claude-sonnet-5-5", "skills": ["stack-trace-explainer"]}
    )
    tool = AssistantMessage(
        content=[ToolUseBlock(id="t1", name="Skill", input={"skill": "stack-trace-explainer"})],
        model="claude-sonnet-5-5",
    )
    fake = FakeQuery([init, tool, result_message("NullPointerException")])
    monkeypatch.setattr(claude_agent_sdk, "query", fake)

    request = request_for(with_skill=True)
    run = asyncio.run(ClaudeCodeRunner().run(request))

    installed = request.workdir / ".claude" / "skills" / "stack-trace-explainer"
    assert (installed / "SKILL.md").is_file()
    assert not (installed / "evals.yaml").exists()
    assert not (installed / "fixtures").exists()

    prompt, options = fake.calls[0]
    assert prompt == "explain error.log"
    assert options.cwd == request.workdir
    assert options.setting_sources == ["project"]
    assert options.skills == ["stack-trace-explainer"]
    assert options.model == "claude-sonnet-5-5"
    assert options.permission_mode == "bypassPermissions"
    assert "no-session-persistence" in options.extra_args

    assert run.triggered is True
    assert run.final_text == "NullPointerException"
    assert run.model == "claude-sonnet-5-5"


def test_baseline_has_no_skill(request_for, monkeypatch) -> None:
    fake = FakeQuery([result_message("dunno")])
    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    request = request_for(with_skill=False)
    run = asyncio.run(ClaudeCodeRunner().run(request))
    assert not (request.workdir / ".claude").exists()
    assert fake.calls[0][1].skills == []
    assert run.triggered is None


def test_runner_options_are_passed(request_for, monkeypatch) -> None:
    fake = FakeQuery([result_message("ok")])
    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    runner = ClaudeCodeRunner(
        {"max_turns": 5, "max_budget_usd": 0.5, "effort": "low", "permission_mode": "acceptEdits"}
    )
    asyncio.run(runner.run(request_for(with_skill=False)))
    options = fake.calls[0][1]
    assert (options.max_turns, options.max_budget_usd, options.effort) == (5, 0.5, "low")
    assert options.permission_mode == "acceptEdits"


def test_error_after_result_is_swallowed(request_for, monkeypatch) -> None:
    error_result = result_message("partial")
    error_result.is_error, error_result.subtype = True, "error_max_turns"
    fake = FakeQuery([error_result], raise_after=RuntimeError("exit code 1"))
    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    run = asyncio.run(ClaudeCodeRunner().run(request_for(with_skill=False)))
    assert run.error is None
    assert run.warnings == ["stopped early: error_max_turns"]


def test_error_before_result_raises(request_for, monkeypatch) -> None:
    fake = FakeQuery([], raise_after=RuntimeError("CLI crashed"))
    monkeypatch.setattr(claude_agent_sdk, "query", fake)
    with pytest.raises(RuntimeError, match="CLI crashed"):
        asyncio.run(ClaudeCodeRunner().run(request_for(with_skill=False)))


def test_unknown_option_is_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClaudeCodeRunner({"max_turn": 3})


def test_reaped_child_warning_is_hidden() -> None:
    import logging

    from skillproof.runners import claude_code

    def record(msg: str) -> logging.LogRecord:
        return logging.LogRecord("asyncio", logging.WARNING, __file__, 1, msg, (), None)

    noise = record("Unknown child process pid 10252, will report returncode 255")
    assert not claude_code._hide_reaped_child_warning(noise)
    assert claude_code._hide_reaped_child_warning(record("Task was destroyed but it is pending!"))
