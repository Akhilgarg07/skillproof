"""Number formatting shared by all report renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from skilltest.report.summary import Summary

DASH = "–"


def pct(value: float | None) -> str:
    return DASH if value is None else f"{value * 100:.0f}%"


def signed_pct(value: float | None) -> str:
    """+23% / −12% (typographic minus) / – for unknown."""
    if value is None:
        return DASH
    text = f"{value * 100:+.0f}%"
    return "±0%" if text in ("+0%", "-0%") else text.replace("-", "−")


def interval(ci: tuple[float, float] | None) -> str:
    if ci is None:
        return DASH
    return f"{signed_pct(ci[0])} to {signed_pct(ci[1])}"


def fraction(num: int, den: int) -> str:
    return DASH if den == 0 else f"{num}/{den}"


def seconds(value: float | None) -> str:
    if value is None:
        return DASH
    return f"{value:.1f}s" if value < 100 else f"{value:.0f}s"


def tokens(value: float | None) -> str:
    if value is None:
        return DASH
    return f"{value / 1000:.1f}k" if value >= 1000 else f"{value:.0f}"


def usd(value: float | None) -> str:
    if value is None:
        return DASH
    return f"${value:.3f}" if value < 1 else f"${value:.2f}"


def summary_line(s: Summary) -> str:
    """skill lift: +23% (95% CI +5% to +41%)  |  triggers 9/10  |  tokens −12% ..."""
    parts = [f"skill lift: {signed_pct(s.lift)}"]
    if s.lift_ci is not None:
        parts[0] += f" (95% CI {interval(s.lift_ci)})"
    parts.append(f"triggers {fraction(s.triggers, s.trigger_runs)}")
    if s.false_trigger_runs:
        parts.append(f"false triggers {fraction(s.false_triggers, s.false_trigger_runs)}")
    parts.append(f"tokens {signed_pct(s.token_delta)}")
    if s.cost_delta is not None:
        parts.append(f"cost {signed_pct(s.cost_delta)}")
    w, wo = s.with_skill.mean_duration_s, s.without_skill.mean_duration_s
    parts.append(f"latency {signed_pct(s.latency_delta)} ({seconds(w)} vs {seconds(wo)})")
    return "  |  ".join(parts)


VERDICT_TEXT = {
    "helps": "the skill helps",
    "hurts": "the skill hurts",
    "no clear effect": "no clear effect",
    "not measured": "lift not measured",
}
