"""Errors that are shown to the user.

Every error carries a `hint`: one sentence telling the user exactly what to do
next. The CLI prints the message and the hint and exits non-zero, without a
traceback.
"""

from __future__ import annotations


class SkilltestError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(SkilltestError):
    """evals.yaml is missing, malformed, or points at things that don't exist."""


class SkillError(SkilltestError):
    """The skill folder or its SKILL.md is missing or malformed."""


class RunnerNotReady(SkilltestError):
    """A runner can't start: missing CLI, missing package, missing API key..."""


class JudgeNotReady(SkilltestError):
    """An llm_judge assertion is used but no judge can be built."""
