"""Assertion types usable under `assert:` in evals.yaml.

To add an assertion type: write a `BaseAssertion` subclass with a unique
`type: Literal["..."]` field and an async `check()`, then add it to
`Assertion` below. Validation and error messages come from pydantic.
"""

from __future__ import annotations

from typing import Annotated, get_args

from pydantic import Field

from skillproof.assertions.base import AssertionResult, BaseAssertion, CheckContext
from skillproof.assertions.builtin import (
    Command,
    Contains,
    FileContains,
    FileExists,
    MaxTokens,
    NotContains,
    Regex,
)
from skillproof.assertions.llm_judge import LLMJudge
from skillproof.judges.base import JudgeUnavailable

Assertion = Annotated[
    Contains | NotContains | Regex | FileExists | FileContains | Command | MaxTokens | LLMJudge,
    Field(discriminator="type"),
]

# ["contains", "not_contains", ...], read from each class's `type` Literal.
ASSERTION_TYPES: list[str] = [
    get_args(cls.model_fields["type"].annotation)[0] for cls in get_args(get_args(Assertion)[0])
]


async def check_all(assertions: list[BaseAssertion], ctx: CheckContext) -> list[AssertionResult]:
    """Run assertions in order. A crashing assertion counts as a failure, not a crash.

    JudgeUnavailable is re-raised: the judge broke, not the agent, so the
    engine marks the whole run as errored instead.
    """
    results = []
    for assertion in assertions:
        try:
            results.append(await assertion.check(ctx))
        except JudgeUnavailable:
            raise
        except Exception as exc:
            results.append(assertion.result(False, f"assertion error: {exc}"))
    return results


__all__ = [
    "ASSERTION_TYPES",
    "Assertion",
    "AssertionResult",
    "BaseAssertion",
    "CheckContext",
    "check_all",
]
