"""Codex runner + parser. Uses a recorded event stream and a fake `codex` executable."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from skillproof.errors import RunnerNotReady
from skillproof.parsers.codex import parse_events, parse_jsonl
from skillproof.runners import RunRequest
from skillproof.runners.codex import CodexRunner
from skillproof.skill import load_skill

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIXTURES / "codex_with_skill.json").read_text())


def test_parse_recorded_run() -> None:
    run = parse_events(RECORDED, "haiku-writer")
    assert run.triggered is True
    assert run.final_text == "Done: hello from mock"
    assert run.error is None
    assert run.num_turns == 1
    assert [c.name for c in run.tool_calls] == ["command_execution"]
    assert "cat .agents/skills/haiku-writer/SKILL.md" in run.tool_calls[0].input["command"]
    assert run.tool_calls[0].output.startswith("---\nname: haiku-writer")
    assert "Model metadata" in run.warnings[0]  # non-fatal error item
    # 2 requests x (100 input, 40 cached, 20 output)
    assert (run.usage.input_tokens, run.usage.cache_read_tokens, run.usage.output_tokens) == (
        120,
        80,
        40,
    )


def test_not_triggered_for_another_skill() -> None:
    assert parse_events(RECORDED, "pdf").triggered is False
    assert parse_events(RECORDED, None).triggered is None


def test_turn_failed_is_an_error() -> None:
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "error", "message": "Connection failed: error sending request"},
        {"type": "turn.failed", "error": {"message": "Connection failed: error sending request"}},
    ]
    assert parse_events(events, None).error == "Connection failed: error sending request"


def test_no_completed_turn_is_an_error() -> None:
    assert parse_events([{"type": "thread.started"}], None).error == (
        "codex exited without completing a turn"
    )


def test_file_changes_and_last_message() -> None:
    events = [
        {"type": "item.completed", "item": {"id": "1", "type": "agent_message", "text": "first"}},
        {
            "type": "item.completed",
            "item": {
                "id": "2",
                "type": "file_change",
                "changes": [{"path": "/w/a.txt", "kind": "add"}],
            },
        },
        {"type": "item.completed", "item": {"id": "3", "type": "agent_message", "text": "final"}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}},
    ]
    run = parse_events(events, None)
    assert run.final_text == "final"
    assert run.tool_calls[0].name == "file_change"


def test_parse_jsonl_skips_junk() -> None:
    assert parse_jsonl('{"type": "a"}\nnot json\n\n[1]\n{"type": "b"}\n') == [
        {"type": "a"},
        {"type": "b"},
    ]


FAKE_CODEX = """\
#!{python}
import json, os, sys
from pathlib import Path
workdir = Path(sys.argv[sys.argv.index("-C") + 1])
codex_home = Path(os.environ["CODEX_HOME"])
Path({record!r}).write_text(json.dumps({{
    "argv": sys.argv[1:],
    "codex_home": str(codex_home),
    "home": os.environ["HOME"],
    "api_key": os.environ.get("CODEX_API_KEY"),
    "auth_json": (codex_home / "auth.json").read_text()
    if (codex_home / "auth.json").exists() else None,
    "skills": sorted(p.name for p in (workdir / ".agents" / "skills").glob("*")),
    "stdin_is_devnull": sys.stdin.read() == "",
}}))
(workdir / "poem.txt").write_text("sea")
for event in json.loads(Path({events!r}).read_text()):
    print(json.dumps(event))
"""


@pytest.fixture
def fake_codex(tmp_path: Path) -> tuple[Path, Path]:
    record = tmp_path / "record.json"
    script = tmp_path / "codex"
    script.write_text(
        FAKE_CODEX.format(
            python=sys.executable,
            record=str(record),
            events=str(FIXTURES / "codex_with_skill.json"),
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, record


def make_request(skill_dir: Path, tmp_path: Path, with_skill: bool) -> RunRequest:
    workdir = tmp_path / "work"
    workdir.mkdir()
    return RunRequest(
        prompt="Write a poem about the sea.",
        workdir=workdir,
        skill=load_skill(skill_dir) if with_skill else None,
        skill_exclude=[skill_dir / "fixtures"],
        model="gpt-6.1-sol",
        timeout_s=60,
        case_name="c",
        trial=0,
    )


def test_runner_end_to_end_with_fake_cli(fake_codex, skill_dir, tmp_path, monkeypatch) -> None:
    script, record = fake_codex
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-123")
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    runner = CodexRunner({"cli_path": str(script), "config": {"model_reasoning_effort": "low"}})
    request = make_request(skill_dir, tmp_path, with_skill=True)
    run = asyncio.run(runner.run(request))

    seen = json.loads(record.read_text())
    argv = seen["argv"]
    assert argv[:2] == ["exec", "--json"]
    for flag in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    assert "skills.bundled.enabled=false" in argv
    assert "model_reasoning_effort=low" in argv
    assert argv[argv.index("--disable") + 1] == "unbounded_connection_retries"
    assert argv[-1] == "Write a poem about the sea."

    assert seen["api_key"] == "sk-test-key-123"  # OPENAI_API_KEY forwarded as CODEX_API_KEY
    assert seen["skills"] == ["stack-trace-explainer"]
    assert seen["stdin_is_devnull"]
    assert Path(seen["home"]) != Path.home()
    assert not Path(seen["home"]).exists()  # temp home cleaned up

    assert run.final_text == "Done: hello from mock"
    assert run.model == "gpt-6.1-sol"
    assert (request.workdir / "poem.txt").read_text() == "sea"


def test_baseline_installs_nothing(fake_codex, skill_dir, tmp_path, monkeypatch) -> None:
    script, record = fake_codex
    monkeypatch.setenv("CODEX_API_KEY", "sk-test-key-123")
    request = make_request(skill_dir, tmp_path, with_skill=False)
    run = asyncio.run(CodexRunner({"cli_path": str(script)}).run(request))
    assert json.loads(record.read_text())["skills"] == []
    assert run.triggered is None


def test_login_auth_is_copied_when_no_key(fake_codex, skill_dir, tmp_path, monkeypatch) -> None:
    script, record = fake_codex
    user_home = tmp_path / "user_codex"
    user_home.mkdir()
    (user_home / "auth.json").write_text('{"token": "t"}')
    monkeypatch.setenv("CODEX_HOME", str(user_home))
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    asyncio.run(
        CodexRunner({"cli_path": str(script)}).run(make_request(skill_dir, tmp_path, False))
    )
    seen = json.loads(record.read_text())
    assert seen["auth_json"] == '{"token": "t"}'
    assert seen["codex_home"] != str(user_home)


def test_check_ready(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(RunnerNotReady, match="Codex CLI not found"):
        CodexRunner({"cli_path": str(tmp_path / "nope")}).check_ready()

    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty"))
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RunnerNotReady, match="No credentials"):
        CodexRunner({"cli_path": str(fake)}).check_ready()
    monkeypatch.setenv("CODEX_API_KEY", "sk-x")
    CodexRunner({"cli_path": str(fake)}).check_ready()
