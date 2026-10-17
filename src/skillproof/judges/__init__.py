"""Building the judge for `llm_judge` assertions.

By default the judge comes from a different vendor than the agent under test,
so a model never grades its own family's homework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from skillproof.errors import JudgeNotReady
from skillproof.judges.base import Judge, Verdict
from skillproof.judges.mock import MockJudge

if TYPE_CHECKING:
    from skillproof.config import JudgeConfig

# agent vendor -> judge provider used when `judge.provider: auto`
CROSS_VENDOR = {"anthropic": "openai", "openai": "anthropic"}


def resolve_provider(config: JudgeConfig, agent_vendor: str) -> str:
    if config.provider != "auto":
        return config.provider
    return CROSS_VENDOR.get(agent_vendor, "anthropic")


def make_judge(config: JudgeConfig, agent_vendor: str) -> Judge:
    provider = resolve_provider(config, agent_vendor)
    if provider == "mock":
        return MockJudge()
    if provider == "anthropic":
        from skillproof.judges.anthropic_judge import AnthropicJudge

        return AnthropicJudge(config.model, config.api_key_env, config.base_url)
    if provider == "openai":
        from skillproof.judges.openai_judge import OpenAIJudge

        return OpenAIJudge(config.model, config.api_key_env, config.base_url)
    raise JudgeNotReady(f"Unknown judge provider {provider!r}.", hint="Use anthropic or openai.")


__all__ = ["Judge", "MockJudge", "Verdict", "make_judge", "resolve_provider"]
