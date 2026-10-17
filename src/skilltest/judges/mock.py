"""A judge for tests: passes when every `pass_if` phrase appears in the answer."""

from __future__ import annotations

from skilltest.judges.base import Judge, Verdict


class MockJudge(Judge):
    name = "mock"
    vendor = "mock"

    def __init__(self, pass_if: list[str] | None = None) -> None:
        self.pass_if = pass_if or []
        self.calls: list[tuple[str, str]] = []

    async def grade(self, rubric: str, response: str) -> Verdict:
        self.calls.append((rubric, response))
        missing = [p for p in self.pass_if if p.lower() not in response.lower()]
        if missing:
            return Verdict(passed=False, reason=f"missing: {', '.join(missing)}")
        return Verdict(passed=True, reason="mock judge: all phrases present")
