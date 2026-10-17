"""Errors that are shown to the user.

Every error carries a `hint`: one sentence telling the user exactly what to do
next. The CLI prints the message and the hint and exits non-zero, without a
traceback.
"""

from __future__ import annotations


class SkillproofError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class ConfigError(SkillproofError):
    """evals.yaml is missing, malformed, or points at things that don't exist."""


class SkillError(SkillproofError):
    """The skill folder or its SKILL.md is missing or malformed."""


class RunnerNotReady(SkillproofError):
    """A runner can't start: missing CLI, missing package, missing API key..."""


class JudgeNotReady(SkillproofError):
    """An llm_judge assertion is used but no judge can be built."""


class RunAborted(SkillproofError):
    """The run stopped early: the first runs all failed, or the user hit Ctrl-C.
    Partial results are saved before this is raised."""


# (pattern, what to do) for errors agents and APIs commonly report.
ERROR_HINTS = [
    (
        r"401|unauthori[sz]ed|authenticat|invalid.{0,20}api.?key|x-api-key|not logged in|"
        r"credentials",
        "Your API key or login is missing or invalid. Check ANTHROPIC_API_KEY, OPENAI_API_KEY "
        "or CODEX_API_KEY (or log in with `claude` / `codex login`).",
    ),
    (
        r"credit|billing|quota|insufficient",
        "Your API account is out of credits or quota. Check billing for the provider.",
    ),
    (
        r"429|rate.?limit|overloaded|529|too many requests",
        "The API is rate-limiting or overloaded. Lower --parallel (e.g. -p 1) and try again.",
    ),
    (
        r"model.{0,40}(not.?found|does not exist|invalid|unknown|not supported)|404",
        "The model name looks wrong. Check `model:` in evals.yaml.",
    ),
    (
        r"enotfound|connection|network|name resolution|getaddrinfo|ssl",
        "Network problem reaching the API. Check your connection, proxy and base_url.",
    ),
]


def hint_for_error(text: str) -> str:
    import re

    for pattern, hint in ERROR_HINTS:
        if re.search(pattern, text, re.IGNORECASE):
            return hint
    return "Open the saved transcripts for details."
