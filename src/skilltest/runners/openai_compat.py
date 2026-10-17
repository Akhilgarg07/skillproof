"""OpenAI-compatible endpoint runner: a small tool-using agent loop over Chat Completions.

Works with OpenAI and anything that speaks the same API (vLLM, Ollama,
OpenRouter, LM Studio, ...).

APPROXIMATION: this is not a real skill-loading agent. With the skill, SKILL.md
is pasted into the system prompt and the skill folder is copied to
`.skills/<name>/` in the sandbox. Real agents only see the skill's description
and decide whether to load it, so trigger rates are not measured here and
results are labeled approximate in every report.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skilltest.errors import RunnerNotReady
from skilltest.runners.base import AgentRun, Runner, RunRequest, ToolCall, Usage
from skilltest.sandbox import scrubbed_env
from skilltest.skill import Skill, copy_skill

MAX_TOOL_OUTPUT = 20_000  # characters returned to the model per tool call
COMMAND_TIMEOUT = 120  # seconds per run_command call

BASE_PROMPT = """\
You are a capable assistant working in a project directory. Use the tools to
inspect files, write files and run shell commands when that helps. When you are
done, reply with your final answer as plain text.
"""

SKILL_PROMPT = """
A skill is installed. Its files are in `.skills/{name}/`. Follow its
instructions when they are relevant to the request.

<skill name="{name}">
{content}
</skill>
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command in the project directory.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file (path relative to the project directory).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file (path relative to the project).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files under a directory (relative to the project).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
]


def system_prompt(skill: Skill | None) -> str:
    if skill is None:
        return BASE_PROMPT
    return BASE_PROMPT + SKILL_PROMPT.format(name=skill.name, content=skill.skill_md.strip())


def _inside(workdir: Path, rel: str) -> Path:
    path = (workdir / rel).resolve()
    if not path.is_relative_to(workdir.resolve()):
        raise ValueError(f"{rel!r} is outside the project directory")
    return path


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    return text[:MAX_TOOL_OUTPUT] + f"\n... [truncated {len(text) - MAX_TOOL_OUTPUT} chars]"


async def run_tool(name: str, args: dict[str, Any], workdir: Path) -> str:
    """Execute one tool call inside the sandbox and return its text result."""
    try:
        if name == "run_command":
            proc = await asyncio.create_subprocess_shell(
                str(args["command"]),
                cwd=workdir,
                env=scrubbed_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=COMMAND_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"command timed out after {COMMAND_TIMEOUT}s"
            return _truncate(f"exit code {proc.returncode}\n{out.decode(errors='replace')}")
        if name == "read_file":
            return _truncate(_inside(workdir, args["path"]).read_text(errors="replace"))
        if name == "write_file":
            target = _inside(workdir, args["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(args["content"]))
            return f"wrote {args['path']}"
        if name == "list_files":
            root = _inside(workdir, args.get("path") or ".")
            files = sorted(str(p.relative_to(workdir)) for p in root.rglob("*") if p.is_file())
            return _truncate("\n".join(files) or "(no files)")
        return f"unknown tool {name!r}"
    except Exception as exc:  # tool errors go back to the model, like a real agent
        return f"error: {exc}"


class OpenAICompatibleRunner(Runner):
    name = "openai-compatible"
    vendor = "openai"
    approximate = True
    requires_model = True

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        base_url: str | None = None  # None = api.openai.com
        api_key_env: str = "OPENAI_API_KEY"
        tools: bool = True  # set false for endpoints without function calling
        max_turns: int = Field(default=20, ge=1)

    options: Options

    def check_ready(self) -> None:
        if self.options.base_url is None and not os.environ.get(self.options.api_key_env):
            raise RunnerNotReady(
                f"{self.options.api_key_env} is not set.",
                hint=f"export {self.options.api_key_env}=..., or set runner_options.base_url "
                "to a local endpoint (e.g. http://localhost:11434/v1 for Ollama).",
            )

    def client(self) -> Any:
        from openai import AsyncOpenAI

        # Local endpoints often need no key, but the client insists on one.
        api_key = os.environ.get(self.options.api_key_env) or "not-needed"
        return AsyncOpenAI(base_url=self.options.base_url, api_key=api_key)

    async def run(self, request: RunRequest) -> AgentRun:
        if request.skill is not None:
            copy_skill(
                request.skill,
                request.workdir / ".skills" / request.skill.name,
                exclude=request.skill_exclude,
            )
        client = self.client()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(request.skill)},
            {"role": "user", "content": request.prompt},
        ]
        usage = Usage()
        calls: list[ToolCall] = []
        warnings: list[str] = []
        final = ""
        turns = 0
        try:
            for turns in range(1, self.options.max_turns + 1):  # noqa: B007 - used after loop
                kwargs: dict[str, Any] = {"model": request.model, "messages": messages}
                if self.options.tools:
                    kwargs["tools"] = TOOLS
                response = await client.chat.completions.create(**kwargs)
                add_usage(usage, response.usage)
                message = response.choices[0].message
                messages.append(message.model_dump(exclude_none=True))
                if not message.tool_calls:
                    final = message.content or ""
                    break
                for tool_call in message.tool_calls:
                    args = parse_arguments(tool_call.function.arguments)
                    output = await run_tool(tool_call.function.name, args, request.workdir)
                    calls.append(ToolCall(name=tool_call.function.name, input=args, output=output))
                    messages.append(
                        {"role": "tool", "tool_call_id": tool_call.id, "content": output}
                    )
            else:
                warnings.append(f"stopped early: max_turns ({self.options.max_turns})")
        finally:
            await client.close()

        return AgentRun(
            final_text=final,
            transcript=messages,
            tool_calls=calls,
            usage=usage,
            num_turns=turns,
            model=request.model,
            triggered=None,  # can't be measured: the skill is always in the prompt
            warnings=warnings,
        )


def parse_arguments(raw: str | None) -> dict[str, Any]:
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_invalid_json": raw}
    return args if isinstance(args, dict) else {"_value": args}


def add_usage(total: Usage, usage: Any) -> None:
    if usage is None:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", None) or 0) if details else 0
    total.input_tokens += (usage.prompt_tokens or 0) - cached
    total.cache_read_tokens += cached
    total.output_tokens += usage.completion_tokens or 0
