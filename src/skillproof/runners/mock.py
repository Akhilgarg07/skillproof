"""A runner that returns scripted results. Used by our tests; never calls an API.

runner: mock
runner_options:
  default:                  # used for cases without their own script
    with: {text: "...", triggered: true, output_tokens: 300}
    without: {text: "..."}
  cases:
    "summarizes stack trace":
      with:                 # a list cycles through trials
        - {text: "NullPointerException at line 3", files: {fix.patch: "..."}}
        - {text: "not sure"}
      without: {text: "not sure"}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skillproof.runners.base import AgentRun, Runner, RunRequest, ToolCall, Usage


class MockResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = ""
    triggered: bool | None = None  # default: True with the skill, False without
    files: dict[str, str] = Field(default_factory=dict)  # written into the sandbox
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 1000
    output_tokens: int = 200
    duration_s: float = 1.0
    timed_out: bool = False
    error: str | None = None


class MockScript(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    with_: MockResponse | list[MockResponse] = Field(default_factory=MockResponse, alias="with")
    without: MockResponse | list[MockResponse] = Field(default_factory=MockResponse)


class MockRunner(Runner):
    name = "mock"
    vendor = "mock"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        default: MockScript = Field(default_factory=MockScript)
        cases: dict[str, MockScript] = Field(default_factory=dict)

    options: Options

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.requests: list[RunRequest] = []  # for tests to inspect

    async def run(self, request: RunRequest) -> AgentRun:
        self.requests.append(request)
        script = self.options.cases.get(request.case_name, self.options.default)
        scripted = script.with_ if request.skill is not None else script.without
        if isinstance(scripted, list):
            scripted = scripted[request.trial % len(scripted)]

        for rel_path, content in scripted.files.items():
            target = request.workdir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        triggered = scripted.triggered
        if triggered is None:
            triggered = request.skill is not None

        return AgentRun(
            final_text=scripted.text,
            transcript=[
                {"role": "user", "content": request.prompt},
                {"role": "assistant", "content": scripted.text},
            ],
            tool_calls=scripted.tool_calls,
            usage=Usage(input_tokens=scripted.input_tokens, output_tokens=scripted.output_tokens),
            duration_s=scripted.duration_s,
            num_turns=1,
            triggered=triggered,
            timed_out=scripted.timed_out,
            error=scripted.error,
        )
