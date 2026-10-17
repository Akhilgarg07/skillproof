"""Claude as a judge (Anthropic Messages API, structured JSON output)."""

from __future__ import annotations

import os

from skilltest.errors import JudgeNotReady
from skilltest.judges.base import (
    VERDICT_SCHEMA,
    Judge,
    JudgeUnavailable,
    Verdict,
    judge_prompt,
    parse_verdict,
)

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicJudge(Judge):
    name = "anthropic"
    vendor = "anthropic"

    def __init__(
        self, model: str | None = None, api_key_env: str | None = None, base_url: str | None = None
    ) -> None:
        import anthropic

        self.model = model or DEFAULT_MODEL
        api_key = None
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise JudgeNotReady(
                    f"Judge API key env var {api_key_env} is not set.",
                    hint=f"export {api_key_env}=... or change `judge.api_key_env`.",
                )
        self.client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    async def grade(self, rubric: str, response: str) -> Verdict:
        import anthropic

        try:
            message = await self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                messages=[{"role": "user", "content": judge_prompt(rubric, response)}],
                output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            )
        except anthropic.APIError as exc:
            raise JudgeUnavailable(f"judge API error: {exc}") from exc
        except TypeError as exc:  # raised by the SDK when no credentials are found
            raise JudgeUnavailable(
                "no Anthropic credentials for the judge: export ANTHROPIC_API_KEY"
            ) from exc
        if message.stop_reason == "refusal":
            raise JudgeUnavailable("judge refused to grade this answer")
        text = next((b.text for b in message.content if b.type == "text"), "")
        return parse_verdict(text)
