"""Parse `codex exec --json` events (JSONL, one dict per line) into an AgentRun.

Event types: thread.started, turn.started, turn.completed {usage},
turn.failed {error}, item.started/updated/completed {item}, error {message}.
Item types we use: agent_message {text}, command_execution {command,
aggregated_output, exit_code}, file_change {changes}, mcp_tool_call, error.

Codex has no dedicated skill tool: the model reads SKILL.md (or runs a script
from the skill folder) with a shell command, so a skill counts as triggered
when a command touches `skills/<name>/`.
"""

from __future__ import annotations

import json
from typing import Any

from skillproof.runners.base import AgentRun, ToolCall, Usage


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue  # not an event (stray log line)
        if isinstance(event, dict):
            events.append(event)
    return events


def completed_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["item"] for e in events if e.get("type") == "item.completed" and "item" in e]


def to_tool_call(item: dict[str, Any]) -> ToolCall | None:
    kind = item.get("type")
    if kind == "command_execution":
        return ToolCall(
            name="command_execution",
            input={"command": item.get("command", ""), "exit_code": item.get("exit_code")},
            output=item.get("aggregated_output"),
        )
    if kind == "file_change":
        return ToolCall(name="file_change", input={"changes": item.get("changes", [])})
    if kind == "mcp_tool_call":
        return ToolCall(
            name=f"mcp:{item.get('server')}/{item.get('tool')}",
            input={"arguments": item.get("arguments")},
            output=json.dumps(item.get("result")) if item.get("result") else None,
        )
    if kind == "web_search":
        return ToolCall(name="web_search", input={"query": item.get("query")})
    return None


def is_skill_call(call: ToolCall, skill_name: str) -> bool:
    return call.name == "command_execution" and f"skills/{skill_name}/" in str(
        call.input.get("command", "")
    )


def parse_usage(events: list[dict[str, Any]]) -> Usage:
    """Sum usage over all turns. Codex's input_tokens include cached tokens."""
    usage = Usage()
    for event in events:
        if event.get("type") != "turn.completed":
            continue
        u = event.get("usage") or {}
        cached = u.get("cached_input_tokens") or 0
        written = u.get("cache_write_input_tokens") or 0
        usage.input_tokens += max(0, (u.get("input_tokens") or 0) - cached - written)
        usage.cache_read_tokens += cached
        usage.cache_write_tokens += written
        usage.output_tokens += u.get("output_tokens") or 0
    return usage


def parse_events(events: list[dict[str, Any]], skill_name: str | None) -> AgentRun:
    items = completed_items(events)
    calls = [c for c in (to_tool_call(i) for i in items) if c is not None]
    messages = [i.get("text", "") for i in items if i.get("type") == "agent_message"]

    error = None
    failed = [e for e in events if e.get("type") == "turn.failed"]
    if failed:
        error = str((failed[-1].get("error") or {}).get("message") or "turn failed")
    elif not any(e.get("type") == "turn.completed" for e in events):
        top_errors = [e.get("message") for e in events if e.get("type") == "error"]
        error = str(top_errors[-1]) if top_errors else "codex exited without completing a turn"

    # Non-fatal problems Codex reports as error items (e.g. unknown model metadata).
    warnings = [str(i.get("message")) for i in items if i.get("type") == "error"]

    triggered = None
    if skill_name is not None:
        triggered = any(is_skill_call(c, skill_name) for c in calls)

    return AgentRun(
        final_text=messages[-1] if messages else "",
        transcript=events,
        tool_calls=calls,
        usage=parse_usage(events),
        num_turns=sum(1 for e in events if e.get("type") == "turn.completed") or None,
        triggered=triggered,
        error=error,
        warnings=warnings,
    )
