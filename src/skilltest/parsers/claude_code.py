"""Parse a Claude Agent SDK message stream (as dicts) into an AgentRun.

Each message is saved as a dict with a `_type` key naming the SDK class
(`SystemMessage`, `AssistantMessage`, `UserMessage`, `ResultMessage`, ...).
Content blocks get the same treatment (`TextBlock`, `ToolUseBlock`, ...).

A skill invocation shows up as a `Skill` tool call:
    {"_type": "ToolUseBlock", "name": "Skill", "input": {"skill": "my-skill"}}
"""

from __future__ import annotations

import dataclasses
from typing import Any

from skilltest.runners.base import AgentRun, ToolCall, Usage

SKILL_TOOL = "Skill"
DROPPED_FIELDS = {"signature"}  # opaque thinking signatures: large and useless for debugging


def to_dict(obj: Any) -> Any:
    """Convert SDK dataclasses (recursively) into JSON-friendly dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {"_type": type(obj).__name__}
        for field in dataclasses.fields(obj):
            if field.name not in DROPPED_FIELDS:
                out[field.name] = to_dict(getattr(obj, field.name))
        return out
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    return content if isinstance(content, list) else []


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text", "")) for c in content if isinstance(c, dict))
    return ""


def tool_calls(transcript: list[dict[str, Any]]) -> list[ToolCall]:
    calls: dict[str, ToolCall] = {}
    for message in transcript:
        for block in _blocks(message):
            if block.get("_type") == "ToolUseBlock":
                calls[block["id"]] = ToolCall(name=block["name"], input=block.get("input") or {})
            elif block.get("_type") == "ToolResultBlock" and block.get("tool_use_id") in calls:
                calls[block["tool_use_id"]].output = _result_text(block.get("content"))
    return list(calls.values())


def is_skill_call(call: ToolCall, skill_name: str) -> bool:
    """A Skill tool call naming this skill, or a direct read of its SKILL.md."""
    if call.name == SKILL_TOOL:
        invoked = str(call.input.get("skill", ""))
        return invoked == skill_name or invoked.endswith(f":{skill_name}")
    marker = f"skills/{skill_name}/SKILL.md"
    return any(isinstance(v, str) and marker in v for v in call.input.values())


def init_data(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    for message in transcript:
        if message.get("_type") == "SystemMessage" and message.get("subtype") == "init":
            return message.get("data") or {}
    return {}


def final_text(transcript: list[dict[str, Any]], result: dict[str, Any] | None) -> str:
    if result and result.get("result"):
        return str(result["result"])
    for message in reversed(transcript):  # fall back to the last assistant text
        if message.get("_type") == "AssistantMessage" and not message.get("parent_tool_use_id"):
            text = "".join(b.get("text", "") for b in _blocks(message) if b["_type"] == "TextBlock")
            if text:
                return text
    return ""


def parse_usage(result: dict[str, Any] | None) -> Usage:
    usage = (result or {}).get("usage") or {}
    return Usage(
        input_tokens=usage.get("input_tokens") or 0,
        output_tokens=usage.get("output_tokens") or 0,
        cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
        cache_write_tokens=usage.get("cache_creation_input_tokens") or 0,
        cost_usd=(result or {}).get("total_cost_usd"),
    )


def parse_error(result: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    """Split failures into infrastructure errors and agent-side warnings."""
    if result is None:
        return "Claude Code ended without a result message", []
    if not result.get("is_error"):
        return None, []
    subtype = result.get("subtype", "")
    details = "; ".join(result.get("errors") or []) or str(result.get("result") or "")
    if result.get("api_error_status"):
        return f"API error {result['api_error_status']}: {details}".strip(": "), []
    if subtype in ("error_max_turns", "error_max_budget_usd"):
        # The agent ran out of its allowance: a real outcome, not an infrastructure error.
        return None, [f"stopped early: {subtype}"]
    return f"Claude Code error ({subtype}): {details}".strip(": "), []


def parse_transcript(transcript: list[dict[str, Any]], skill_name: str | None) -> AgentRun:
    result = next((m for m in reversed(transcript) if m.get("_type") == "ResultMessage"), None)
    calls = tool_calls(transcript)
    error, warnings = parse_error(result)
    init = init_data(transcript)

    triggered: bool | None = None
    if skill_name is not None:
        triggered = any(is_skill_call(c, skill_name) for c in calls)
        listed = init.get("skills")
        if isinstance(listed, list) and skill_name not in listed:
            warnings.append(
                f"skill {skill_name!r} was not listed at startup; "
                "check SKILL.md frontmatter (or `user-invocable: false`)"
            )

    return AgentRun(
        final_text=final_text(transcript, result),
        transcript=transcript,
        tool_calls=calls,
        usage=parse_usage(result),
        duration_s=((result or {}).get("duration_ms") or 0) / 1000,
        num_turns=(result or {}).get("num_turns"),
        model=init.get("model"),
        triggered=triggered,
        error=error,
        warnings=warnings,
    )
