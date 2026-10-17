"""Building the judge for `llm_judge` assertions.

By default the judge comes from a different vendor than the agent under test,
so a model never grades its own family's homework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from skilltest.errors import JudgeNotReady
from skilltest.judges.base import Judge, Verdict
from skilltest.judges.mock import MockJudge

if TYPE_CHECKING:
    from skilltest.config import JudgeConfig

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
    raise JudgeNotReady(
        f"The {provider!r} judge is not implemented yet.",
        hint="Remove llm_judge assertions or set `judge: {provider: mock}` for now.",
    )


__all__ = ["Judge", "MockJudge", "Verdict", "make_judge", "resolve_provider"]
