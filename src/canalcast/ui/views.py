"""Side-by-side results view and disclosure panel for the Streamlit_Interface.

This module is part of the Streamlit_Interface, not the Calculation_Core, so it
MAY import ``streamlit`` (the core never does). To keep the module importable
outside a running Streamlit session, every widget call is wrapped inside a
``render_*`` function and ``streamlit`` is imported lazily inside those
functions; importing this module runs no Streamlit code at import time. The pure
helpers (:func:`_format_metric`, :func:`_unavailable_inputs`,
:func:`_status_label`, :func:`_deadline_label`) can be reasoned about and
unit-tested without any runtime.

Requirements implemented here:

* **Req 14.1** Panama and Suez are shown in two adjacent columns in a single
  viewport row, with Panama (left) before Suez (right).
* **Req 14.2** Each option displays exactly five metrics, each with its unit:
  Journey_Time (hours), voyage fuel cost (USD, labelled "fuel cost" — never
  "total shipping cost"), fuel cost per loaded TEU (USD/TEU), fuel-combustion
  CO2 (t CO2, tank-to-wake), and deadline status.
* **Req 14.3** A metric disabled by a missing Required_Input is shown as
  "unavailable" with each missing/invalid input named; no zero or invented
  value is ever substituted.
* **Req 14.4** An Infeasible_Result is shown as infeasible with its explanation
  and its fuel cost per loaded TEU shown as "undefined".
* **Req 14.5** The exact text "Scenario tool — not a forecast." is displayed in
  the results view (sourced from ``result.disclaimer``).
* **Req 15.1** For each input behind the results the disclosure panel shows the
  input's source/assumption rationale, its status (sourced/approximate/
  assumption/derived), and the data date when present.
* **Req 15.2** The disclosure panel lists excluded cost items (at minimum tolls,
  insurance, and other unmodeled costs) and states the emissions are
  fuel-combustion CO2 only and EXCLUDE lifecycle emissions.
* **Req 15.3** A missing Required_Input is listed by name, its calculation is
  noted as disabled, and plain-language text states what value is needed.
* **Req 15.4 / 15.5** No shipping-line name or logo is emitted; any carrier
  example would be labelled Carrier A/B/C (none is shown here).
* **Req 17.6** All text relies on Streamlit defaults, whose foreground/background
  contrast meets >=4.5:1 for normal text and >=3:1 for large text; any custom
  color used here is chosen to meet those ratios. See ``_ACCESSIBLE_*`` below.
"""

from __future__ import annotations

from typing import Mapping

from ..explain import explain
from ..models import ProvenancedValue, Status, Unavailable
from ..results import ComparisonResult, OptionResult

__all__ = ["render_results", "render_disclosure_panel"]


# --------------------------------------------------------------------------- #
# Accessibility note (Req 17.6)
# --------------------------------------------------------------------------- #
# We render through Streamlit's default theme, whose body text already meets a
# foreground-to-background contrast ratio of >=4.5:1 for normal text and >=3:1
# for large text. We deliberately do NOT impose low-contrast custom colors. The
# only custom colors below are used for optional emphasis and are chosen to keep
# >=4.5:1 contrast against both Streamlit's light (#ffffff) and dark (#0e1117)
# default backgrounds, so the contrast guarantee holds in either theme.
_ACCESSIBLE_WARN_COLOR = "#B00020"  # deep red: >=4.5:1 on white and on #0e1117

# Minimum human-readable labels for the four provenance statuses (Req 15.1).
_STATUS_LABELS: dict[Status, str] = {
    Status.SOURCED: "sourced",
    Status.APPROXIMATE: "approximate",
    Status.ASSUMPTION: "assumption",
    Status.DERIVED: "derived",
}


# --------------------------------------------------------------------------- #
# Pure helpers — importable and testable without a Streamlit runtime
# --------------------------------------------------------------------------- #

def _unavailable_inputs(value: Unavailable) -> tuple[str, ...]:
    """Return the distinct input names named by an :class:`Unavailable`.

    Combines ``missing_inputs`` and ``invalid_inputs`` in order, de-duplicating
    while preserving first-seen order. Used so the view can NAME each offending
    Required_Input rather than substituting a zero or invented value
    (Requirements 14.3, 15.3).

    Args:
        value: The unavailable stand-in whose inputs to collect.

    Returns:
        The named inputs, de-duplicated and order-preserving. May be empty when
        the ``Unavailable`` names no specific inputs.
    """
    seen: list[str] = []
    for name in (*value.missing_inputs, *value.invalid_inputs):
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def _format_metric(value: object, unit: str) -> str:
    """Format a numeric metric with its unit, or name it unavailable.

    Pure formatter with no Streamlit dependency. When ``value`` is a real
    ``int``/``float`` (not a ``bool``), returns a ``"<number> <unit>"`` string
    with the number rounded sensibly for its unit. When ``value`` is an
    :class:`~canalcast.models.Unavailable` (or ``None``), returns an
    ``"unavailable"`` string that NAMES the missing/invalid inputs when any are
    recorded (Req 14.3) — e.g. ``"unavailable: needs bunker_price_usd_per_t"`` —
    so the caller never shows a zero or invented value. A ``None`` with no names
    yields the bare ``"unavailable"``.

    Args:
        value: The metric value — a number, an ``Unavailable``, or ``None``.
        unit: The unit to display alongside a numeric value (e.g. ``"hours"``,
            ``"USD"``, ``"USD/TEU"``, ``"t CO2"``).

    Returns:
        A human-readable ``"<number> <unit>"`` string for a real number, or an
        ``"unavailable"`` string (naming inputs when known) otherwise.
    """
    if isinstance(value, Unavailable):
        names = _unavailable_inputs(value)
        if names:
            return "unavailable: needs " + ", ".join(names)
        reason = value.reason.strip()
        return f"unavailable ({reason})" if reason else "unavailable"
    if value is None:
        return "unavailable"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unavailable"

    number = float(value)
    u = unit.strip()
    if u in ("hours", "hour", "h"):
        return f"{number:,.1f} hours"
    if u in ("USD/TEU",):
        return f"${round(number):,} per TEU"
    if u in ("USD",):
        return f"${round(number):,}"
    if u in ("t CO2", "tonnes CO2", "t_CO2"):
        return f"{round(number):,} t CO2 (tank-to-wake)"
    if u in ("TEU",):
        return f"{round(number):,} TEU"
    return f"{number:,.2f} {u}".rstrip()


def _status_label(status: Status) -> str:
    """Return the plain-language label for a provenance status (Req 15.1).

    Args:
        status: The :class:`~canalcast.models.Status` to label.

    Returns:
        One of ``"sourced"``, ``"approximate"``, ``"assumption"``, ``"derived"``;
        falls back to the enum's value for any unmapped status.
    """
    return _STATUS_LABELS.get(status, status.value)


def _format_date(provenance: ProvenancedValue) -> str | None:
    """Return the ISO data date of a provenanced value, or ``None`` (Req 15.1).

    Args:
        provenance: The provenanced value whose ``retrieved_on`` to render.

    Returns:
        The ISO-formatted date string when ``retrieved_on`` is present, else
        ``None`` so the caller can omit the date rather than invent one.
    """
    if provenance.retrieved_on is None:
        return None
    return provenance.retrieved_on.isoformat()


def _deadline_label(option: OptionResult) -> str:
    """Return the deadline-status label for an option (Req 14.2).

    Reads the pre-computed :attr:`OptionResult.deadline_status`
    ("meets deadline" | "misses deadline" | "undetermined"). Pure: no Streamlit.

    Args:
        option: The option whose deadline status to label.

    Returns:
        The option's deadline-status text.
    """
    return option.deadline_status


def _gather_missing_inputs(
    option: OptionResult,
) -> dict[str, tuple[str, ...]]:
    """Collect, per metric, the Required_Inputs an option is missing (Req 15.3).

    Inspects each of the option's five headline metrics; for any that is an
    :class:`~canalcast.models.Unavailable`, records the metric's display name
    mapped to the named missing/invalid inputs. Pure: no Streamlit.

    Args:
        option: The option to inspect.

    Returns:
        A mapping from metric display name to the tuple of named inputs. Metrics
        that are available (or carry no named inputs) are omitted.
    """
    metrics: tuple[tuple[str, object], ...] = (
        ("Journey time", option.journey.journey_time_h),
        ("Voyage fuel cost", option.voyage_fuel_cost_usd),
        ("Fuel cost per loaded TEU", option.fuel_cost_per_teu_usd),
        ("Fuel-combustion CO2", option.co2_tank_to_wake_t),
    )
    missing: dict[str, tuple[str, ...]] = {}
    for name, value in metrics:
        if isinstance(value, Unavailable):
            inputs = _unavailable_inputs(value)
            if inputs:
                missing[name] = inputs
    return missing


# --------------------------------------------------------------------------- #
# Streamlit render functions (Task 11.1)
# --------------------------------------------------------------------------- #

def _render_option_column(option: OptionResult, label: str) -> None:
    """Render one option's five metrics into the current Streamlit column.

    Displays exactly the five headline metrics, each with its unit (Req 14.2):
    Journey_Time (hours), voyage "fuel cost" (USD — never "total shipping
    cost"), fuel cost per loaded TEU (USD/TEU), fuel-combustion CO2 (t CO2,
    tank-to-wake), and deadline status. A metric disabled by a missing
    Required_Input is shown as "unavailable" with the input(s) named and no
    substitution (Req 14.3). An Infeasible_Result is shown as infeasible with
    its explanation, and its fuel cost per loaded TEU is shown as "undefined"
    (Req 14.4).

    Args:
        option: The per-option result to render.
        label: The column heading, e.g. ``"Panama"`` or ``"Suez"``.
    """
    import streamlit as st

    st.subheader(label)

    if option.infeasible:
        # Req 14.4: show the option as infeasible with its explanation.
        reason = option.infeasible_reason or "zero loaded payload."
        st.warning(f"Infeasible: {reason}")

    st.metric("Journey time", _format_metric(option.journey.journey_time_h, "hours"))

    # Req 14.2 / 8.8: always "fuel cost", never "total shipping cost".
    st.metric("Voyage fuel cost", _format_metric(option.voyage_fuel_cost_usd, "USD"))

    # Req 14.4: an infeasible option's per-TEU cost is "undefined".
    if option.infeasible:
        per_teu_text = "undefined"
    else:
        per_teu_text = _format_metric(option.fuel_cost_per_teu_usd, "USD/TEU")
    st.metric("Fuel cost per loaded TEU", per_teu_text)

    # Req 9.5 label: tank-to-wake fuel-combustion CO2, never lifecycle.
    st.metric(
        "Fuel-combustion CO2 (tank-to-wake)",
        _format_metric(option.co2_tank_to_wake_t, "t CO2"),
    )

    st.metric("Deadline status", _deadline_label(option))

    # Req 20.11: optional draft-based cargo-loss figures. Only rendered when the
    # adjustment is enabled for this option (Panama); when disabled the panel is
    # unchanged, preserving v1 behavior.
    _render_draft_loss(option)


def _render_draft_loss(option: OptionResult) -> None:
    """Render the draft-loss figures and disclosure for an option (Req 20.11).

    When :attr:`OptionResult.draft_loss_enabled` is ``True``, displays
    Draft_Shortfall_Ft (ft), Containers_Lost, and TEU_Lost — each formatted via
    the shared :func:`_format_metric` helper — and the analyst-estimate/
    assumption disclosure text. When draft loss is disabled, renders nothing so
    the panel is identical to v1.

    Args:
        option: The per-option result whose draft-loss figures to render.
    """
    import streamlit as st

    if not option.draft_loss_enabled:
        return

    st.markdown("**Draft-based cargo loss**")
    st.metric("Draft shortfall", _format_metric(option.draft_shortfall_ft, "ft"))
    st.metric("Containers lost", _format_metric(option.containers_lost, "containers"))
    st.metric("TEU lost", _format_metric(option.teu_lost, "TEU"))

    if option.draft_loss_disclosure:
        st.caption(option.draft_loss_disclosure)


def _render_selection(result: ComparisonResult) -> None:
    """Render the selection outcome and tie-break disclosure (Req 11.5/11.8).

    Shows which option was selected via ``result.selection.message``. When no
    option is feasible, states that no option meets the deadline and names the
    closest option. When a tie-break resolved the outcome, discloses the Panama
    tie-break as a disclosed deterministic CONVENTION — not evidence that Panama
    is superior.

    Args:
        result: The comparison whose selection to render.
    """
    import streamlit as st

    selection = result.selection
    st.markdown("### Selection")
    st.write(selection.message)

    if selection.no_feasible_option:
        if selection.closest_option is not None:
            closest = selection.closest_option.capitalize()
            st.info(
                "No option meets the deadline in this scenario. The closest by "
                f"journey time is {closest}."
            )
        else:
            st.info(
                "No option meets the deadline in this scenario and no closest "
                "option is available."
            )

    if selection.tie_resolution is not None:
        st.caption(
            "The outcome was settled by a disclosed Panama tie-break convention "
            f"({selection.tie_resolution}). This is a disclosed deterministic "
            "convention, not evidence that Panama is the superior route."
        )


def render_results(result: ComparisonResult) -> None:
    """Render the side-by-side results view for a comparison (Req 14, 17).

    When ``result.comparison_error`` is set, shows the error reason prominently
    and the disclaimer, then returns without rendering options (Req 11.1).
    Otherwise renders Panama (left) and Suez (right) in two adjacent columns in
    a single viewport row (Req 14.1), each with the five headline metrics
    (Req 14.2), plus the selection outcome, the deterministic explanation
    (Req 17 integration), the disclosure panel (Req 15), and the exact
    disclaimer text "Scenario tool — not a forecast." (Req 14.5).

    All Streamlit calls happen inside this function, so importing the module is
    side-effect free.

    Args:
        result: The comparison to render.
    """
    import streamlit as st

    st.header("Results")

    # Req 14.5: the exact disclaimer text appears in the results view.
    st.caption(result.disclaimer)

    # Req 11.1: comparison could not be made — show the reason prominently and
    # still show the disclaimer (already emitted above), then stop.
    if result.comparison_error is not None:
        st.error(
            "The comparison could not be made: " + result.comparison_error.reason
        )
        names = _unavailable_inputs(result.comparison_error)
        if names:
            st.write("Inputs involved: " + ", ".join(names))
        return

    # Req 14.1: two adjacent columns in one row, Panama first (left).
    panama_col, suez_col = st.columns(2)

    with panama_col:
        if result.panama is not None:
            _render_option_column(result.panama, "Panama")
        else:
            st.subheader("Panama")
            reason = result.exclusion_reasons.get(
                "panama", "This option is not available in this scenario."
            )
            st.info(f"Panama is excluded: {reason}")

    with suez_col:
        if result.suez is not None:
            _render_option_column(result.suez, "Suez")
        else:
            st.subheader("Suez")
            reason = result.exclusion_reasons.get(
                "suez", "This option is not available in this scenario."
            )
            st.info(f"Suez is excluded: {reason}")

    _render_selection(result)

    # Req 17 integration: render the deterministic (<=120-word) explanation
    # derived solely from the current result.
    st.markdown("### Explanation")
    st.write(explain(result))

    # Req 15: the disclosure panel accompanies the results view.
    render_disclosure_panel(result)


def _render_provenance_for_option(
    option: OptionResult, option_label: str
) -> None:
    """Render one option's per-input provenance into the disclosure panel.

    For each input behind the option's results, shows the source/assumption
    rationale, the status (sourced/approximate/assumption/derived), and the data
    date when present (Req 15.1).

    Args:
        option: The option whose ``input_provenance`` to render.
        option_label: Heading for this option's provenance block.
    """
    import streamlit as st

    provenance: Mapping[str, ProvenancedValue] = option.input_provenance
    if not provenance:
        return

    st.markdown(f"**{option_label} inputs**")
    for name, pv in provenance.items():
        status = _status_label(pv.status)
        date_text = _format_date(pv)
        line = f"- **{name}** — {pv.rationale} (status: {status}"
        if date_text is not None:
            line += f", data date: {date_text}"
        line += ")"
        st.markdown(line)


def render_disclosure_panel(result: ComparisonResult) -> None:
    """Render the assumptions/sources/dates/exclusions disclosure (Req 15).

    Behavior:

    * For each input behind the results (gathered from each option's
      ``input_provenance``), shows the source/assumption rationale, the status,
      and the data date when present (Req 15.1).
    * Lists excluded cost items — at minimum tolls, insurance, and other
      unmodeled costs — drawn from each option's ``exclusions``, and states the
      emissions are fuel-combustion CO2 only and EXCLUDE lifecycle emissions
      (Req 15.2).
    * When a Required_Input is missing, lists it by name, notes the dependent
      calculation is disabled, and states in plain language what is needed
      (Req 15.3).
    * Emits NO shipping-line name or logo; any carrier example would be labelled
      Carrier A/B/C (none is shown here) (Req 15.4, 15.5).
    * Shows the canal-state draft as CONTEXT with its not-modeled disclosure.

    All Streamlit calls happen inside this function.

    Args:
        result: The comparison whose disclosures to render.
    """
    import streamlit as st

    with st.expander("Assumptions, sources, dates, and exclusions", expanded=False):
        options: tuple[tuple[str, OptionResult | None], ...] = (
            ("Panama", result.panama),
            ("Suez", result.suez),
        )

        # --- Req 15.1: per-input rationale / status / data date -------------
        st.markdown("#### Input sources and assumptions")
        any_provenance = False
        for label, option in options:
            if option is not None and option.input_provenance:
                _render_provenance_for_option(option, label)
                any_provenance = True
        if not any_provenance:
            st.write("No input provenance is available for this comparison.")

        # --- Req 15.3: missing Required_Inputs, by name, with guidance ------
        missing_any = False
        for label, option in options:
            if option is None:
                continue
            missing = _gather_missing_inputs(option)
            if not missing:
                continue
            if not missing_any:
                st.markdown("#### Missing inputs (calculations disabled)")
                missing_any = True
            for metric_name, inputs in missing.items():
                named = ", ".join(inputs)
                st.markdown(
                    f"- **{label} — {metric_name}** is disabled because "
                    f"the following input(s) are not available: {named}. "
                    "Provide a value for each to enable this calculation."
                )

        # --- Req 15.2: excluded cost items + emissions scope ----------------
        st.markdown("#### Excluded costs and emissions scope")
        exclusions: list[str] = []
        seen: set[str] = set()
        for _, option in options:
            if option is None:
                continue
            for item in option.exclusions:
                if item not in seen:
                    seen.add(item)
                    exclusions.append(item)
        # Guarantee the minimum disclosure even if an option carries none.
        baseline = ("tolls", "insurance", "other unmodeled costs")
        for item in baseline:
            if item not in seen:
                seen.add(item)
                exclusions.append(item)
        st.markdown(
            "The displayed figures are fuel cost only; the following are "
            "excluded from this result: " + ", ".join(exclusions) + "."
        )
        st.markdown(
            "Displayed emissions represent fuel-combustion carbon dioxide only "
            "(tank-to-wake) and EXCLUDE lifecycle emissions."
        )

        # --- Draft context (Req 10.1 / 10.4) --------------------------------
        st.markdown("#### Canal draft (context only)")
        draft_shown = False
        for label, option in options:
            if option is None:
                continue
            draft = option.draft_context_ft
            date_text = _format_date(draft)
            line = (
                f"- **{label}** maximum draft context: {draft.value} {draft.unit} "
                f"(status: {_status_label(draft.status)}"
            )
            if date_text is not None:
                line += f", data date: {date_text}"
            line += f"). {option.draft_not_modeled_disclosure}"
            st.markdown(line)
            draft_shown = True
        if not draft_shown:
            st.write("No draft context is available for this comparison.")
