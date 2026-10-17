"""JSON report: the Summary as-is, for CI and scripts."""

from __future__ import annotations

from skillproof.report.summary import Summary


def render(s: Summary) -> str:
    return s.model_dump_json(indent=2) + "\n"
