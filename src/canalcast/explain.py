"""Deterministic plain-language explanation for the CanalCast Calculation_Core.

This module is part of the pure Calculation_Core. It performs NO file I/O and
makes NO network calls, and it imports no library that does either: it imports
only from :mod:`.results`, :mod:`.models`, and the standard library's ``typing``
facilities. ``explain.py`` lives in the core precisely because Requirement 17
requires the explanation be derived SOLELY from the current result with no
runtime network call; keeping it pure makes that guarantee testable, and a
boundary test (Task 8.1) scans this module for forbidden imports.

:func:`explain` composes a short (``<= max_words`` words, default 120) summary of
the CURRENT calculated results held in a
:class:`~canalcast.results.ComparisonResult` (Requirement 17.1). Every stated
value is derived solely from that one ``result`` object — no other data source,
no I/O, no network (Requirements 17.2, 17.3). The summary describes only the
current numbers and NEVER states or implies a forecast or prediction
(Requirement 17.4): no "will", "forecast", "predict", or "expected to"; the
framing is "this scenario computes ...". A value that is an
:class:`~canalcast.models.Unavailable` (or ``None``) is OMITTED as a number and
NAMED as unavailable rather than invented or zeroed (Requirement 17.5).

The function is deterministic: the same ``result`` always yields the same text,
with no randomness and no timestamps.
"""

from __future__ import annotations

from typing import Optional

from .models import Unavailable
from .results import ComparisonResult, OptionResult


def _fmt(value: object, unit: str) -> str:
    """Format a numeric metric with its unit, or name it unavailable.

    Returns a formatted ``"<number> <unit>"`` string when ``value`` is a real
    float/int (rounded sensibly per unit), otherwise returns ``"unavailable"``
    for an :class:`~canalcast.models.Unavailable` or ``None`` so the caller can
    name the metric without substituting an invented or zero value
    (Requirement 17.5). Booleans are treated as non-numeric.
    """
    if value is None or isinstance(value, Unavailable):
        return "unavailable"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unavailable"

    number = float(value)
    u = unit.strip()
    if u in ("hours", "hour", "h"):
        text = f"{number:.1f} hours"
    elif u in ("USD/TEU",):
        text = f"${round(number):,} per TEU"
    elif u in ("USD",):
        text = f"${round(number):,}"
    elif u in ("t CO2", "tonnes CO2", "t_CO2"):
        text = f"{round(number):,} tonnes CO2 (tank-to-wake)"
    elif u in ("TEU",):
        text = f"{round(number):,} TEU"
    else:
        # Generic fallback: a trimmed number followed by its unit.
        text = f"{number:.2f} {u}".rstrip()
    return text


def _is_num(value: object) -> bool:
    """True when ``value`` is a usable real number (not Unavailable/None/bool)."""
    return (
        value is not None
        and not isinstance(value, Unavailable)
        and not isinstance(value, bool)
        and isinstance(value, (int, float))
    )


def _describe_option(opt: OptionResult, label: str) -> str:
    """Compose one sentence of metrics for a single option.

    Every metric is drawn solely from ``opt``. A metric whose value is an
    :class:`~canalcast.models.Unavailable` is named as unavailable rather than
    given a number (Requirement 17.5). Labels respect the contract: "fuel cost"
    (never total shipping cost) and tank-to-wake CO2 (never lifecycle).
    """
    parts: list[str] = []

    journey_time = opt.journey.journey_time_h
    if _is_num(journey_time):
        parts.append(f"journey time {_fmt(journey_time, 'hours')}")
    else:
        parts.append("journey time is unavailable")

    cost_per_teu = opt.fuel_cost_per_teu_usd
    if _is_num(cost_per_teu):
        parts.append(f"fuel cost {_fmt(cost_per_teu, 'USD/TEU')}")
    else:
        parts.append("fuel cost per TEU is unavailable")

    voyage_cost = opt.voyage_fuel_cost_usd
    if _is_num(voyage_cost):
        parts.append(f"voyage fuel cost {_fmt(voyage_cost, 'USD')}")

    co2 = opt.co2_tank_to_wake_t
    if _is_num(co2):
        parts.append(f"{_fmt(co2, 't CO2')}")
    else:
        parts.append("tank-to-wake CO2 is unavailable")

    return f"For {label}, this scenario computes " + ", ".join(parts) + "."


def _cap_words(text: str, max_words: int) -> str:
    """Truncate ``text`` to at most ``max_words`` words at a word boundary.

    Composition aims to stay under the cap, so truncation is rare; when it is
    needed the text is cut at a whole-word boundary (Requirement 17.1).
    """
    if max_words <= 0:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def explain(result: ComparisonResult, max_words: int = 120) -> str:
    """Produce a deterministic plain-language summary of ``result``.

    The returned text describes the CURRENT calculated results only, derives
    every value solely from ``result`` (no other source, no I/O, no network),
    never implies a forecast or prediction, omits-and-names unavailable values,
    and contains at most ``max_words`` words (default 120). See the module
    docstring for the Requirement 17 mapping (17.1-17.5).

    Args:
        result: The comparison to summarize.
        max_words: Hard upper bound on the word count of the returned text.

    Returns:
        A plain-language summary string with ``<= max_words`` words.
    """
    sentences: list[str] = []

    # --- Comparison could not be made (Requirement 11.1 / 17.5) ---------
    if result.comparison_error is not None:
        reason = result.comparison_error.reason
        sentences.append(
            "This scenario could not compare the two routings because "
            f"{reason}."
        )
        return _cap_words(" ".join(sentences), max_words)

    selection = result.selection

    # --- Suez exclusion, if present (Requirement 11.3) ------------------
    if "suez" in result.excluded_options:
        suez_reason = result.exclusion_reasons.get("suez")
        if suez_reason:
            sentences.append(f"Suez is excluded because {suez_reason}.")
        else:
            sentences.append("Suez is excluded in this scenario.")

    # --- Which option, by which priority --------------------------------
    priority = selection.priority
    if selection.selected_option is not None:
        chosen_label = selection.selected_option.capitalize()
        sentences.append(
            f"Using the {priority} priority, this scenario selects "
            f"{chosen_label}."
        )
        described: Optional[OptionResult] = _option_by_name(
            result, selection.selected_option
        )
    elif selection.no_feasible_option:
        if selection.closest_option is not None:
            closest_label = selection.closest_option.capitalize()
            sentences.append(
                "No option meets the deadline in this scenario; the closest "
                f"by journey time is {closest_label} (priority {priority})."
            )
            described = _option_by_name(result, selection.closest_option)
        else:
            sentences.append(
                "No option meets the deadline in this scenario and no closest "
                f"option is available (priority {priority})."
            )
            described = None
    else:
        sentences.append(
            f"This scenario reports no selected option (priority {priority})."
        )
        described = None

    # --- Metrics for the selected/closest option ------------------------
    if described is not None:
        option_label = described.option.capitalize()
        sentences.append(_describe_option(described, option_label))

    # --- Panama tie-break convention, if used (Requirement 11.8) --------
    if selection.tie_resolution is not None:
        sentences.append(
            "The outcome was settled by a disclosed Panama tie-break "
            "convention, not a claim of route superiority."
        )

    return _cap_words(" ".join(sentences), max_words)


def _option_by_name(
    result: ComparisonResult, name: str
) -> Optional[OptionResult]:
    """Return the :class:`OptionResult` for ``name`` held on ``result``.

    Looks only at ``result``'s own ``panama``/``suez`` fields (no other source),
    returning ``None`` when that option is absent.
    """
    if name == "panama":
        return result.panama
    if name == "suez":
        return result.suez
    return None
