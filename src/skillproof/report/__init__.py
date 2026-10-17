"""Report renderers. Every format reads the same `Summary` (see summary.py)."""

from __future__ import annotations

from pathlib import Path

from skillproof.report import html_report, json_report, markdown
from skillproof.report.summary import Summary, build_summary
from skillproof.results import SuiteResult

FORMATS = ("terminal", "md", "html", "json")


def render_text(fmt: str, summary: Summary, suite: SuiteResult) -> str:
    """Render a file-style format (md, html, json) to a string."""
    if fmt == "md":
        return markdown.render(summary)
    if fmt == "html":
        return html_report.render(summary, suite)
    if fmt == "json":
        return json_report.render(summary)
    raise ValueError(f"not a file format: {fmt}")


def write_reports(suite: SuiteResult) -> Summary:
    """Save summary.json, report.md and report.html next to the transcripts."""
    summary = build_summary(suite)
    run_dir = Path(suite.run_dir)
    for name, fmt in (("summary.json", "json"), ("report.md", "md"), ("report.html", "html")):
        (run_dir / name).write_text(render_text(fmt, summary, suite), encoding="utf-8")
    return summary


__all__ = ["FORMATS", "Summary", "build_summary", "render_text", "write_reports"]
