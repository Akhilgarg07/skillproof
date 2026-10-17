"""An OpenAI model as a judge (Responses API, structured JSON output)."""

from __future__ import annotations

import os

from skillproof.errors import JudgeNotReady
from skillproof.judges.base import (
    VERDICT_SCHEMA,
    Judge,
    JudgeUnavailable,
    Verdict,
    judge_prompt,
    parse_verdict,
)

DEFAULT_MODEL = "gpt-6.1-sol"


class OpenAIJudge(Judge):
    name = "openai"
    vendor = "openai"

    def __init__(
        self, model: str | None = None, api_key_env: str | None = None, base_url: str | None = None
    ) -> None:
        import openai

        self.model = model or DEFAULT_MODEL
        key_env = api_key_env or "OPENAI_API_KEY"
        api_key = os.environ.get(key_env)
        if not api_key:
            raise JudgeNotReady(
                f"{key_env} is not set, and llm_judge needs it.",
                hint=f"export {key_env}=..., or set `judge: {{provider: anthropic}}`.",
            )
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def grade(self, rubric: str, response: str) -> Verdict:
        import openai

        try:
            result = await self.client.responses.create(
                model=self.model,
                input=judge_prompt(rubric, response),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "verdict",
                        "strict": True,
                        "schema": VERDICT_SCHEMA,
                    }
                },
                store=False,
            )
        except openai.APIError as exc:
            raise JudgeUnavailable(f"judge API error: {exc}") from exc
        return parse_verdict(result.output_text)
