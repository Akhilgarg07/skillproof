"""OpenAI-compatible runner with a scripted fake client; no network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from openai.types.chat import ChatCompletion

from skillproof.config import parse_config
from skillproof.errors import ConfigError, RunnerNotReady
from skillproof.runners import RunRequest
from skillproof.runners.openai_compat import OpenAICompatibleRunner, run_tool, system_prompt
from skillproof.skill import load_skill


def completion(content: str | None = None, tool_calls: list[dict] | None = None, cached: int = 0):
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for i, (name, args) in enumerate(tc for tc in tool_calls)
        ]
    return ChatCompletion.model_validate(
        {
            "id": "c",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": cached},
            },
        }
    )


class FakeClient:
    def __init__(self, responses: list[ChatCompletion]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.chat = self
        self.completions = self
        self.closed = False

    async def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def make_runner(responses, **options) -> tuple[OpenAICompatibleRunner, FakeClient]:
    runner = OpenAICompatibleRunner(options)
    fake = FakeClient(responses)
    runner.client = lambda: fake  # type: ignore[method-assign]
    return runner, fake


@pytest.fixture
def request_for(skill_dir: Path, tmp_path: Path):
    def make(with_skill: bool) -> RunRequest:
        workdir = tmp_path / "work"
        workdir.mkdir()
        (workdir / "error.log").write_text("NullPointerException at Foo.java:3")
        return RunRequest(
            prompt="What's wrong?",
            workdir=workdir,
            skill=load_skill(skill_dir) if with_skill else None,
            skill_exclude=[skill_dir / "fixtures"],
            model="test-model",
            timeout_s=60,
            case_name="c",
            trial=0,
        )

    return make


def test_tool_loop_with_skill(request_for) -> None:
    runner, fake = make_runner(
        [
            completion(tool_calls=[("read_file", {"path": "error.log"})]),
            completion(
                tool_calls=[("write_file", {"path": "fix.patch", "content": "diff"})], cached=80
            ),
            completion("Root cause: NullPointerException."),
        ]
    )
    request = request_for(with_skill=True)
    run = asyncio.run(runner.run(request))

    assert run.final_text == "Root cause: NullPointerException."
    assert [c.name for c in run.tool_calls] == ["read_file", "write_file"]
    assert run.tool_calls[0].output == "NullPointerException at Foo.java:3"
    assert (request.workdir / "fix.patch").read_text() == "diff"
    assert (request.workdir / ".skills" / "stack-trace-explainer" / "SKILL.md").is_file()
    assert run.triggered is None  # approximate runner: not measured
    assert run.num_turns == 3
    assert run.usage.output_tokens == 60
    assert run.usage.cache_read_tokens == 80
    assert run.usage.input_tokens == 300 - 80
    assert fake.closed

    system = fake.requests[0]["messages"][0]["content"]
    assert '<skill name="stack-trace-explainer">' in system
    assert fake.requests[0]["model"] == "test-model"
    assert {t["function"]["name"] for t in fake.requests[0]["tools"]} == {
        "run_command",
        "read_file",
        "write_file",
        "list_files",
    }
    # tool results are sent back with their call ids
    tool_msg = fake.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_0"


def test_baseline_has_no_skill(request_for) -> None:
    runner, fake = make_runner([completion("no idea")])
    request = request_for(with_skill=False)
    asyncio.run(runner.run(request))
    assert "<skill" not in fake.requests[0]["messages"][0]["content"]
    assert not (request.workdir / ".skills").exists()


def test_tools_can_be_disabled(request_for) -> None:
    runner, fake = make_runner([completion("hi")], tools=False)
    asyncio.run(runner.run(request_for(with_skill=False)))
    assert "tools" not in fake.requests[0]


def test_max_turns(request_for) -> None:
    looping = [completion(tool_calls=[("list_files", {})]) for _ in range(2)]
    runner, _ = make_runner(looping, max_turns=2)
    run = asyncio.run(runner.run(request_for(with_skill=False)))
    assert run.warnings == ["stopped early: max_turns (2)"]
    assert run.final_text == ""


def test_tools_stay_inside_sandbox(tmp_path: Path) -> None:
    async def go():
        assert "outside the project" in await run_tool("read_file", {"path": "../x"}, tmp_path)
        assert (
            await run_tool("write_file", {"path": "a/b.txt", "content": "x"}, tmp_path)
            == "wrote a/b.txt"
        )
        assert await run_tool("list_files", {}, tmp_path) == "a/b.txt"
        out = await run_tool("run_command", {"command": "cat a/b.txt; exit 4"}, tmp_path)
        assert out.startswith("exit code 4") and out.endswith("x")
        assert "unknown tool" in await run_tool("rm_rf", {}, tmp_path)

    asyncio.run(go())


def test_run_command_hides_api_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123456")
    out = asyncio.run(run_tool("run_command", {"command": 'echo "[$OPENAI_API_KEY]"'}, tmp_path))
    assert "[]" in out


def test_system_prompt_without_skill() -> None:
    assert "<skill" not in system_prompt(None)


def test_check_ready_needs_key_for_openai(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RunnerNotReady, match="OPENAI_API_KEY"):
        OpenAICompatibleRunner().check_ready()
    OpenAICompatibleRunner({"base_url": "http://localhost:11434/v1"}).check_ready()  # local: ok


def test_config_requires_model() -> None:
    data = {"runner": "openai-compatible", "cases": [{"name": "c", "prompt": "p"}]}
    with pytest.raises(ConfigError, match="needs `model:`"):
        parse_config(data, Path("."))
    assert parse_config({**data, "model": "llama3"}, Path(".")).model == "llama3"
