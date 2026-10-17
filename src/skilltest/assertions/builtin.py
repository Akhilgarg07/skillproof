"""Deterministic assertions. These are cheap and reproducible: prefer them."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator

from skilltest.assertions.base import AssertionResult, BaseAssertion, CheckContext
from skilltest.sandbox import run_shell

MAX_OUTPUT_IN_MESSAGE = 500


def _sandbox_relative(path: str) -> str:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("must be a relative path inside the sandbox (no '/' prefix, no '..')")
    return path


def _snippet(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Contains(BaseAssertion):
    """The agent's final answer contains `value`."""

    type: Literal["contains"]
    value: str
    case_sensitive: bool = False

    def describe(self) -> str:
        return f'contains "{self.value}"'

    async def check(self, ctx: CheckContext) -> AssertionResult:
        haystack, needle = ctx.run.final_text, self.value
        if not self.case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        if needle in haystack:
            return self.result(True, f'answer contains "{self.value}"')
        return self.result(False, f'"{self.value}" not in answer: "{_snippet(ctx.run.final_text)}"')


class NotContains(BaseAssertion):
    """The agent's final answer does NOT contain `value`."""

    type: Literal["not_contains"]
    value: str
    case_sensitive: bool = False

    def describe(self) -> str:
        return f'not_contains "{self.value}"'

    async def check(self, ctx: CheckContext) -> AssertionResult:
        haystack, needle = ctx.run.final_text, self.value
        if not self.case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        if needle in haystack:
            return self.result(False, f'answer contains forbidden "{self.value}"')
        return self.result(True, f'answer does not contain "{self.value}"')


class Regex(BaseAssertion):
    """The agent's final answer matches a Python regular expression."""

    type: Literal["regex"]
    pattern: str

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        return pattern

    def describe(self) -> str:
        return f"regex /{self.pattern}/"

    async def check(self, ctx: CheckContext) -> AssertionResult:
        if re.search(self.pattern, ctx.run.final_text, flags=re.MULTILINE):
            return self.result(True, f"answer matches /{self.pattern}/")
        return self.result(False, f"answer does not match /{self.pattern}/")


class FileExists(BaseAssertion):
    """A file exists in the sandbox after the run."""

    type: Literal["file_exists"]
    path: str

    @field_validator("path")
    @classmethod
    def _inside_sandbox(cls, path: str) -> str:
        return _sandbox_relative(path)

    def describe(self) -> str:
        return f"file_exists {self.path}"

    async def check(self, ctx: CheckContext) -> AssertionResult:
        if (ctx.workdir / self.path).exists():
            return self.result(True, f"{self.path} exists")
        return self.result(False, f"{self.path} was not created")


class FileContains(BaseAssertion):
    """A file in the sandbox contains `value`."""

    type: Literal["file_contains"]
    path: str
    value: str
    case_sensitive: bool = False

    @field_validator("path")
    @classmethod
    def _inside_sandbox(cls, path: str) -> str:
        return _sandbox_relative(path)

    def describe(self) -> str:
        return f'file_contains {self.path} "{self.value}"'

    async def check(self, ctx: CheckContext) -> AssertionResult:
        target: Path = ctx.workdir / self.path
        if not target.is_file():
            return self.result(False, f"{self.path} was not created")
        content = target.read_text(encoding="utf-8", errors="replace")
        needle = self.value
        if not self.case_sensitive:
            content, needle = content.lower(), needle.lower()
        if needle in content:
            return self.result(True, f'{self.path} contains "{self.value}"')
        return self.result(False, f'{self.path} does not contain "{self.value}"')


class Command(BaseAssertion):
    """Run a shell command in the sandbox; passes if it exits 0.

    API keys and tokens are removed from the command's environment.
    """

    type: Literal["command"]
    run: str
    timeout: float = Field(default=120, gt=0)

    def describe(self) -> str:
        return f"command `{self.run}`"

    async def check(self, ctx: CheckContext) -> AssertionResult:
        code, out = await run_shell(self.run, ctx.workdir, self.timeout)
        if code is None:
            return self.result(False, f"`{self.run}` timed out after {self.timeout:g}s")
        if code == 0:
            return self.result(True, f"`{self.run}` exited 0")
        output = out.strip()[-MAX_OUTPUT_IN_MESSAGE:]
        return self.result(False, f"`{self.run}` exited {code}: {output}")


class MaxTokens(BaseAssertion):
    """The run used at most `value` tokens (input + output + cache)."""

    type: Literal["max_tokens"]
    value: int = Field(gt=0)

    def describe(self) -> str:
        return f"max_tokens {self.value}"

    async def check(self, ctx: CheckContext) -> AssertionResult:
        used = ctx.run.usage.total_tokens
        if used <= self.value:
            return self.result(True, f"used {used} tokens (limit {self.value})")
        return self.result(False, f"used {used} tokens, over the limit of {self.value}")
