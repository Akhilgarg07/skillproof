"""shields.io badges for a skill's README.

Static badge (markdown):  [![skilltest](https://img.shields.io/badge/...)](link)
Endpoint JSON (--json):   {"schemaVersion": 1, "label": ..., "message": ..., "color": ...}
Host the JSON (e.g. a gist, updated by CI) and point shields.io/endpoint at it
to get a badge that updates itself.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from skilltest.report.summary import Summary

LABEL = "skilltest"
HOMEPAGE = "https://github.com/akhilgarg07/skilltest"
COLORS = {
    "helps": "brightgreen",
    "hurts": "red",
    "no clear effect": "lightgrey",
    "too few runs": "lightgrey",
    "not measured": "lightgrey",
}


def message(s: Summary) -> str:
    if s.lift is None:
        text = "lift not measured"
    else:
        text = f"{s.lift * 100:+.0f}% lift"
        if s.verdict == "no clear effect":
            text += " (n.s.)"  # not significant: the 95% interval includes zero
        elif s.verdict == "too few runs":
            text += " (too few runs)"
    if s.trigger_runs:
        text += f" · {s.triggers}/{s.trigger_runs} triggered"
    if s.approximate:
        text += " · approx"
    return text


def _escape(text: str) -> str:
    """shields.io path escaping: '-' -> '--', '_' -> '__', then URL-encode."""
    return quote(text.replace("-", "--").replace("_", "__"), safe="")


def badge_url(s: Summary) -> str:
    return (
        f"https://img.shields.io/badge/{_escape(LABEL)}-{_escape(message(s))}-{COLORS[s.verdict]}"
    )


def markdown(s: Summary, link: str = HOMEPAGE) -> str:
    return f"[![{LABEL}: {message(s)}]({badge_url(s)})]({link})"


def endpoint_json(s: Summary) -> str:
    data = {"schemaVersion": 1, "label": LABEL, "message": message(s), "color": COLORS[s.verdict]}
    return json.dumps(data, ensure_ascii=False)
