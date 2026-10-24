"""Streamlit presets and scenario input controls for CanalCast.

This module is part of the Streamlit_Interface and MAY import ``streamlit``. The
pure Calculation_Core never imports this module (design "Streamlit Interface
Design"). Every Streamlit widget call lives inside a function so the module
imports cleanly even when it is not executed under ``streamlit run`` — the pure
helpers (:func:`days_to_hours`, :func:`comparable_od_pairs`,
:func:`find_canal_state`, :func:`build_custom_canal_state`) can be imported and
unit-tested without a running server.

Responsibilities:

* Preset selection — Normal reference, October 2026 snapshot, Custom
  (Requirements 12.1-12.6).
* Scenario input controls with range enforcement (Requirements 13.1-13.7).

The interface uses DAYS for Waiting_Duration and the deadline (Requirement 13.1)
while :class:`~canalcast.models.Scenario` carries HOURS
(``waiting_duration_h``, ``deadline_h``). Day inputs are converted to hours with
:func:`days_to_hours` when the :class:`Scenario` is assembled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from ..models import (
    CanalState,
    LoadResult,
    ODPair,
    ProvenancedValue,
    Scenario,
    Status,
)

# Streamlit is imported lazily/at module load but all *widget* calls are kept
# inside functions. Importing the module does not require a running server.
import streamlit as st

# --------------------------------------------------------------------------- #
# Constants: presets and selection-priority labels
# --------------------------------------------------------------------------- #

#: Canal-state name for the normal-reference preset (Requirement 12.1).
PRESET_NORMAL = "Normal reference"
#: Canal-state name for the October 2026 snapshot preset (Requirement 12.3).
PRESET_OCT2026 = "October 2026 snapshot"
#: Custom scenario option (Requirement 12.5).
PRESET_CUSTOM = "Custom"

#: Ordered preset options offered by :func:`render_preset_selector`.
PRESET_OPTIONS: tuple[str, ...] = (PRESET_NORMAL, PRESET_OCT2026, PRESET_CUSTOM)

#: Maps each non-custom preset to the ``CanalState.state`` name it draws from
#: (Requirements 12.1-12.4).
PRESET_TO_STATE_NAME: dict[str, str] = {
    PRESET_NORMAL: "normal_reference",
    PRESET_OCT2026: "current_oct2026",
}

SelectionPriority = Literal["fastest", "lowest_cost_per_teu", "lowest_co2"]

#: Friendly labels mapped to the exactly-three Selection_Priority metric values
#: accepted by :class:`Scenario` (Requirements 13.3, 11.4).
PRIORITY_LABEL_TO_VALUE: dict[str, SelectionPriority] = {
    "Fastest journey time": "fastest",
    "Lowest fuel cost per TEU": "lowest_cost_per_teu",
    "Lowest CO\u2082": "lowest_co2",
}
#: Reverse of :data:`PRIORITY_LABEL_TO_VALUE` for pre-selecting a stored value.
PRIORITY_VALUE_TO_LABEL: dict[SelectionPriority, str] = {
    value: label for label, value in PRIORITY_LABEL_TO_VALUE.items()
}

# Range bounds for the numeric controls (Requirement 13.2). Speed and bunker
# price must be strictly positive, so the minimum is a small epsilon above zero.
SPEED_MIN_KN: float = 0.1
LOAD_FACTOR_MIN: float = 0.0
LOAD_FACTOR_MAX: float = 1.0
BUNKER_PRICE_MIN: float = 0.01
WAITING_DAYS_MIN: float = 0.0
DEADLINE_DAYS_MIN: float = 0.01
CANAL_HOURS_MIN: float = 0.0
DRAFT_FT_MIN: float = 0.0
SLOTS_MIN: int = 0

HOURS_PER_DAY: float = 24.0

# Draft-loss control bounds and defaults (Requirement 20.11). The slider is
# seeded from the loaded ``containers_lost_per_10cm_draft_cut`` constant when
# available, falling back to this analyst-estimate default.
CONTAINERS_LOST_PER_10CM_DEFAULT: float = 100.0
CONTAINERS_LOST_PER_10CM_MIN: float = 0.0
CONTAINERS_LOST_PER_10CM_MAX: float = 500.0
CONTAINERS_LOST_PER_10CM_STEP: float = 10.0
AVG_TEU_PER_CONTAINER_DEFAULT: float = 1.7
AVG_TEU_PER_CONTAINER_MIN: float = 0.5
AVG_TEU_PER_CONTAINER_STEP: float = 0.1

#: Context key under which the Data_Loader stores the analyst-estimate
#: containers-lost-per-10cm figure (``data/constants.csv``).
CONTAINERS_LOST_CONSTANT_KEY = "containers_lost_per_10cm_draft_cut"

#: Session-state key under which the last fully valid assembled scenario is kept
#: so an out-of-range entry can fall back to it (Requirement 13.7).
LAST_VALID_SCENARIO_KEY = "canalcast_last_valid_scenario"


# --------------------------------------------------------------------------- #
# Pure helpers — importable and testable without a Streamlit runtime
# --------------------------------------------------------------------------- #

def days_to_hours(days: float) -> float:
    """Convert a duration in days to hours.

    The interface collects Waiting_Duration and the deadline in DAYS
    (Requirement 13.1) while :class:`Scenario` stores them in HOURS. This is the
    single conversion used when assembling the scenario.

    Args:
        days: A duration in days.

    Returns:
        The equivalent duration in hours (``days * 24``).
    """
    return days * HOURS_PER_DAY


def comparable_od_pairs(load_result: LoadResult) -> tuple[ODPair, ...]:
    """Return OD pairs that have BOTH a Panama and a Suez distance.

    Route selection is restricted to OD_Pairs that have both a Panama
    Route_Option distance and a Suez Route_Option distance (Requirement 13.4);
    a comparison is only valid when both distances are present and positive
    (Requirement 11.1). An option whose ``distance_nm`` is ``None`` is treated
    as not having a distance and disqualifies the pair.

    Args:
        load_result: The loaded required/optional data.

    Returns:
        The qualifying OD pairs, in their loaded order.
    """
    qualifying: list[ODPair] = []
    for pair in load_result.required.od_pairs:
        panama = pair.panama
        suez = pair.suez
        if panama is None or suez is None:
            continue
        if panama.distance_nm is None or suez.distance_nm is None:
            continue
        qualifying.append(pair)
    return tuple(qualifying)


def od_pair_label(pair: ODPair) -> str:
    """Return a human-readable label for an OD pair selectbox entry.

    Args:
        pair: The OD pair to label.

    Returns:
        A label such as ``"Shanghai \u2192 New York"``.
    """
    return f"{pair.origin} \u2192 {pair.destination}"


def find_canal_state(
    load_result: LoadResult, state_name: str
) -> CanalState | None:
    """Find a loaded :class:`CanalState` by its ``state`` name.

    Preset canal states are pulled from
    ``load_result.required.canal_states`` by name (Requirements 12.1-12.4). When
    the requested state is not present the caller surfaces a clear message
    rather than substituting a value.

    Args:
        load_result: The loaded required/optional data.
        state_name: The ``CanalState.state`` identifier to look up.

    Returns:
        The matching :class:`CanalState`, or ``None`` when absent.
    """
    for state in load_result.required.canal_states:
        if state.state == state_name:
            return state
    return None


def build_custom_canal_state(
    max_draft_ft: float,
    daily_slots: int,
    *,
    retrieved_on: date | None = None,
) -> CanalState:
    """Build a synthetic :class:`CanalState` from custom user inputs.

    For the Custom preset the user sets the draft limit (ft) and whole
    booking-slot count (slots/day) directly (Requirement 12.5). The resulting
    values carry ``Status.ASSUMPTION`` provenance because they originate from
    user input rather than a sourced record. The draft remains CONTEXT only and
    never reduces TEU, cost, fuel, or CO2 (Requirement 10).

    Args:
        max_draft_ft: User-entered maximum draft in feet.
        daily_slots: User-entered whole booking-slot count per day.
        retrieved_on: Optional date to stamp on the synthetic values.

    Returns:
        A :class:`CanalState` named ``"custom"`` built from the inputs.
    """
    draft = ProvenancedValue(
        value=float(max_draft_ft),
        unit="ft",
        rationale="User-entered custom draft limit",
        status=Status.ASSUMPTION,
        retrieved_on=retrieved_on,
    )
    slots = ProvenancedValue(
        value=float(int(daily_slots)),
        unit="slots/day",
        rationale="User-entered custom booking-slot count",
        status=Status.ASSUMPTION,
        retrieved_on=retrieved_on,
    )
    provenance = ProvenancedValue(
        value="custom",
        unit="-",
        rationale="User-defined custom Canal_State",
        status=Status.ASSUMPTION,
        retrieved_on=retrieved_on,
    )
    return CanalState(
        state="custom",
        max_draft_ft=draft,
        daily_slots=slots,
        period="Custom scenario",
        provenance=provenance,
    )


def _in_range(
    value: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> bool:
    """Return whether ``value`` lies within the inclusive bounds given.

    Args:
        value: The value to test.
        minimum: Inclusive lower bound, or ``None`` for no lower bound.
        maximum: Inclusive upper bound, or ``None`` for no upper bound.

    Returns:
        ``True`` when the value respects both supplied bounds.
    """
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def containers_lost_seed(load_result: LoadResult) -> float:
    """Return the seed for the containers-lost-per-10cm slider (Req 20.11).

    Reads the analyst-estimate ``containers_lost_per_10cm_draft_cut`` figure from
    the loaded constants' ``context`` map and parses it to a float. When the
    value is absent or cannot be parsed, falls back to
    :data:`CONTAINERS_LOST_PER_10CM_DEFAULT` (100) so the slider always has a
    sensible starting point. Pure: no Streamlit.

    Args:
        load_result: The loaded required/optional data.

    Returns:
        The seed value in containers per 10 cm, clamped to the slider's
        ``[CONTAINERS_LOST_PER_10CM_MIN, CONTAINERS_LOST_PER_10CM_MAX]`` range.
    """
    seed = CONTAINERS_LOST_PER_10CM_DEFAULT
    context = load_result.required.constants.context
    pv = context.get(CONTAINERS_LOST_CONSTANT_KEY)
    if pv is not None:
        try:
            seed = float(pv.value)
        except (TypeError, ValueError):
            seed = CONTAINERS_LOST_PER_10CM_DEFAULT
    # Keep the seed inside the slider bounds so Streamlit does not reject it.
    if seed < CONTAINERS_LOST_PER_10CM_MIN:
        seed = CONTAINERS_LOST_PER_10CM_MIN
    if seed > CONTAINERS_LOST_PER_10CM_MAX:
        seed = CONTAINERS_LOST_PER_10CM_MAX
    return seed


# --------------------------------------------------------------------------- #
# Intermediate container for the raw control readings
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ControlReadings:
    """Raw values read from the controls before assembly into a Scenario.

    Day-based durations are kept in DAYS here (as the user entered them) and are
    converted to hours only when the final :class:`Scenario` is built
    (Requirement 13.1). ``None`` on a required field marks a missing input that
    disables the dependent calculation (Requirements 12.6, 13).

    Attributes:
        od_pair: The selected comparable OD pair, or ``None`` if none exist.
        canal_state: The resolved canal state (preset or custom), or ``None``.
        speed_kn: Sailing speed in knots.
        load_factor: Fraction of capacity loaded.
        bunker_price_usd_per_t: Bunker price in USD/tonne.
        canal_duration_h: Canal transit duration in hours.
        waiting_days: Waiting duration in DAYS.
        deadline_days: Deadline in DAYS.
        suez_available: Whether Suez is assumed available.
        selection_priority: The active selection metric.
        fuel_type: Selected fuel type.
        missing: Plain-language messages naming missing required inputs.
        out_of_range: Plain-language messages naming out-of-range inputs.
        draft_loss_enabled: Whether the optional draft-based cargo-loss
            adjustment is active (Requirement 20.11). Defaults to ``False`` so a
            ``ControlReadings`` built without draft-loss inputs assembles a
            scenario identical to v1.
        containers_lost_per_10cm: Explicit override for the containers-lost-per-
            10cm estimate, or ``None`` to use the loaded constant. ``None`` by
            default (Requirement 20.5/20.11).
        avg_teu_per_container: Average TEU per lost container assumption
            (Requirement 20.6). Defaults to ``1.7`` to match the
            :class:`~canalcast.models.Scenario` default.
    """

    od_pair: ODPair | None
    canal_state: CanalState | None
    speed_kn: float | None
    load_factor: float | None
    bunker_price_usd_per_t: float | None
    canal_duration_h: float | None
    waiting_days: float | None
    deadline_days: float | None
    suez_available: bool
    selection_priority: SelectionPriority
    fuel_type: str
    missing: tuple[str, ...] = field(default_factory=tuple)
    out_of_range: tuple[str, ...] = field(default_factory=tuple)
    draft_loss_enabled: bool = False
    containers_lost_per_10cm: float | None = None
    avg_teu_per_container: float = 1.7


def assemble_scenario(
    readings: ControlReadings,
) -> tuple[Scenario | None, list[str]]:
    """Assemble a :class:`Scenario` from raw control readings.

    Pure (no Streamlit): converts the day-based durations to hours
    (Requirement 13.1) and validates that every required input is present and in
    range. When any required input is missing or out of range, returns
    ``(None, messages)`` so the caller can disable the dependent calculation and
    state in plain language what is needed (Requirements 12.6, 13.7); otherwise
    returns the assembled scenario and an empty message list.

    Args:
        readings: The raw values read from the controls.

    Returns:
        A ``(scenario, messages)`` tuple. ``scenario`` is ``None`` when the
        scenario cannot be assembled; ``messages`` names every missing or
        out-of-range input in plain language.
    """
    messages: list[str] = list(readings.missing) + list(readings.out_of_range)

    required_present = (
        readings.od_pair is not None
        and readings.canal_state is not None
        and readings.speed_kn is not None
        and readings.load_factor is not None
        and readings.bunker_price_usd_per_t is not None
        and readings.canal_duration_h is not None
        and readings.waiting_days is not None
        and readings.deadline_days is not None
    )

    if not required_present or messages:
        return None, messages

    # mypy/readers: all Optionals narrowed to present by required_present.
    assert readings.od_pair is not None
    assert readings.canal_state is not None
    assert readings.speed_kn is not None
    assert readings.load_factor is not None
    assert readings.bunker_price_usd_per_t is not None
    assert readings.canal_duration_h is not None
    assert readings.waiting_days is not None
    assert readings.deadline_days is not None

    scenario = Scenario(
        od_pair_id=readings.od_pair.route_id,
        speed_kn=readings.speed_kn,
        load_factor=readings.load_factor,
        bunker_price_usd_per_t=readings.bunker_price_usd_per_t,
        canal_duration_h=readings.canal_duration_h,
        waiting_duration_h=days_to_hours(readings.waiting_days),
        deadline_h=days_to_hours(readings.deadline_days),
        suez_available=readings.suez_available,
        selection_priority=readings.selection_priority,
        fuel_type=readings.fuel_type,
        canal_state=readings.canal_state,
        # Optional draft-based cargo-loss adjustment (Requirement 20.11). When
        # the toggle is OFF, ``ControlReadings`` carries the no-loss defaults
        # (draft_loss_enabled=False, containers_lost_per_10cm=None,
        # avg_teu_per_container=1.7), so the assembled Scenario is identical to
        # v1 and existing behavior is preserved.
        draft_loss_enabled=readings.draft_loss_enabled,
        containers_lost_per_10cm=readings.containers_lost_per_10cm,
        avg_teu_per_container=readings.avg_teu_per_container,
    )
    return scenario, []


# --------------------------------------------------------------------------- #
# Streamlit widget functions (Task 10.1 — presets; Task 10.2 — controls)
# --------------------------------------------------------------------------- #

def render_preset_selector() -> str:
    """Render the preset selector and return the chosen preset label.

    Offers Normal reference, October 2026 snapshot, and Custom
    (Requirements 12.1, 12.3, 12.5).

    Returns:
        The selected preset label (one of :data:`PRESET_OPTIONS`).
    """
    return st.radio(
        "Scenario preset",
        options=PRESET_OPTIONS,
        index=0,
        help=(
            "Normal reference and October 2026 use sourced canal states; "
            "Custom lets you set the draft and booking slots directly."
        ),
    )


def resolve_preset_canal_state(
    load_result: LoadResult, preset: str
) -> tuple[CanalState | None, list[str]]:
    """Resolve the canal state for a non-custom preset.

    Pulls the canal state by name from ``load_result.required.canal_states``
    (Requirements 12.1-12.4). When the expected state is absent a clear message
    is returned instead of substituting a value.

    Args:
        load_result: The loaded required/optional data.
        preset: The selected preset label.

    Returns:
        A ``(canal_state, messages)`` tuple. ``canal_state`` is ``None`` when the
        expected state is not present; ``messages`` explains what is missing.
    """
    state_name = PRESET_TO_STATE_NAME.get(preset)
    if state_name is None:
        return None, [f"Preset '{preset}' has no associated canal state."]
    state = find_canal_state(load_result, state_name)
    if state is None:
        return None, [
            f"Canal state '{state_name}' for the {preset} preset was not "
            f"found in the loaded data."
        ]
    return state, []


def render_custom_canal_state() -> tuple[CanalState | None, list[str]]:
    """Render the custom draft and booking-slot controls.

    The user sets the draft limit (ft) and whole booking-slot count (slots/day)
    directly (Requirement 12.5). A missing required custom input disables the
    dependent calculation and states in plain language what is needed
    (Requirement 12.6).

    Returns:
        A ``(canal_state, messages)`` tuple. ``canal_state`` is ``None`` when a
        required custom input is missing; ``messages`` names what is needed.
    """
    messages: list[str] = []

    draft_val = st.number_input(
        "Custom maximum draft (ft) — context only",
        min_value=DRAFT_FT_MIN,
        value=50.0,
        step=0.5,
        help="Shown as scenario context; it does not reduce TEU, cost, or CO\u2082.",
    )
    slots_val = st.number_input(
        "Custom booking slots (slots/day)",
        min_value=SLOTS_MIN,
        value=36,
        step=1,
        help="Whole booking-slot limit per day — a booking limit, not a transit count.",
    )

    if draft_val is None:
        messages.append("Enter a custom maximum draft in feet to continue.")
    if slots_val is None:
        messages.append("Enter a custom booking-slot count (whole slots per day).")
    if messages:
        return None, messages

    return build_custom_canal_state(float(draft_val), int(slots_val)), []


def _available_fuel_types(load_result: LoadResult) -> tuple[str, ...]:
    """Return the fuel types for which an emission factor was loaded.

    Args:
        load_result: The loaded required/optional data.

    Returns:
        The available fuel-type identifiers, in loaded order.
    """
    return tuple(
        factor.fuel_type for factor in load_result.required.emission_factors
    )


def render_draft_loss_controls(
    load_result: LoadResult,
) -> tuple[bool, float | None, float]:
    """Render the optional draft-based cargo-loss controls (Requirement 20.11).

    Renders a toggle defaulting to OFF. When OFF, returns the no-loss defaults
    so the assembled :class:`~canalcast.models.Scenario` is identical to v1:
    ``(False, None, 1.7)``. When ON, exposes:

    * a slider "Containers lost per 10 cm of draft cut" seeded from the loaded
      ``containers_lost_per_10cm_draft_cut`` estimate (via
      :func:`containers_lost_seed`), and
    * an "Average TEU per lost container" number input (default ``1.7``),

    along with a short caption disclosing that the adjustment rests on an
    analyst-estimate and an assumption so the provenance is visible up front.

    All Streamlit widget calls live inside this function, so importing the
    module runs no Streamlit code.

    Args:
        load_result: The loaded required/optional data (source of the seed).

    Returns:
        A ``(draft_loss_enabled, containers_lost_per_10cm, avg_teu_per_container)``
        tuple ready to place on a :class:`ControlReadings`. When the toggle is
        off, ``(False, None, 1.7)`` so v1 behavior is preserved exactly.
    """
    enabled = st.toggle(
        "Model draft-based cargo loss (v2)",
        value=False,
        help=(
            "Optional, off by default. When on, a tighter Panama draft reduces "
            "loaded TEU and raises the per-TEU figures for the Panama option."
        ),
    )

    if not enabled:
        # OFF: no-loss defaults matching the Scenario model so nothing changes
        # for existing users (Requirement 20.11).
        return False, None, AVG_TEU_PER_CONTAINER_DEFAULT

    seed = containers_lost_seed(load_result)
    containers_lost_per_10cm = st.slider(
        "Containers lost per 10 cm of draft cut",
        min_value=CONTAINERS_LOST_PER_10CM_MIN,
        max_value=CONTAINERS_LOST_PER_10CM_MAX,
        value=float(seed),
        step=CONTAINERS_LOST_PER_10CM_STEP,
        help=(
            "Seeded from the loaded analyst estimate. Number of containers lost "
            "per 10 cm of draft shortfall on the Panama route."
        ),
    )
    avg_teu_per_container = st.number_input(
        "Average TEU per lost container",
        min_value=AVG_TEU_PER_CONTAINER_MIN,
        value=AVG_TEU_PER_CONTAINER_DEFAULT,
        step=AVG_TEU_PER_CONTAINER_STEP,
        help="Assumption factor converting containers lost into TEU lost.",
    )
    st.caption(
        "This adjustment rests on an analyst-estimate containers-lost figure and "
        "an assumption average-TEU-per-container factor; it affects only loaded "
        "TEU and the per-TEU figures for the Panama option."
    )

    return (
        True,
        None if containers_lost_per_10cm is None else float(containers_lost_per_10cm),
        AVG_TEU_PER_CONTAINER_DEFAULT
        if avg_teu_per_container is None
        else float(avg_teu_per_container),
    )


def render_scenario_controls(
    load_result: LoadResult, canal_state: CanalState | None
) -> ControlReadings:
    """Render the scenario input controls and read their values.

    Implements Task 10.2 / Requirements 13.1-13.7:

    * Route selectbox restricted to comparable OD pairs (Requirement 13.4).
    * speed (> 0), load factor ([0,1]), bunker price (> 0), waiting (>= 0 days),
      deadline (> 0 days) with range enforcement via ``min_value``/``max_value``
      (Requirement 13.2).
    * Selection_Priority restricted to exactly the three values
      (Requirement 13.3).
    * Suez availability as available/unavailable (Requirement 13.5).
    * A canal-duration control (hours) feeding ``canal_duration_h``.

    Range enforcement relies on Streamlit's ``min_value``/``max_value`` clamping;
    the defensive :func:`_in_range` check records any value that still falls
    outside its bounds so the caller can reject it and retain the last valid
    scenario (Requirement 13.7).

    Args:
        load_result: The loaded required/optional data.
        canal_state: The resolved canal state (preset or custom), or ``None``.

    Returns:
        A :class:`ControlReadings` capturing the raw values plus any missing or
        out-of-range messages.
    """
    missing: list[str] = []
    out_of_range: list[str] = []

    pairs = comparable_od_pairs(load_result)
    selected_pair: ODPair | None
    if not pairs:
        selected_pair = None
        missing.append(
            "No route has both a Panama and a Suez distance, so no comparison "
            "can be run. Add a route with both distances to continue."
        )
    else:
        labels = [od_pair_label(p) for p in pairs]
        chosen_label = st.selectbox("Route (origin \u2192 destination)", labels)
        selected_pair = pairs[labels.index(chosen_label)]

    speed_kn = st.number_input(
        "Speed (knots)",
        min_value=SPEED_MIN_KN,
        value=18.0,
        step=0.5,
        help="Sailing speed; must be greater than zero.",
    )
    load_factor = st.number_input(
        "Load factor (fraction of capacity)",
        min_value=LOAD_FACTOR_MIN,
        max_value=LOAD_FACTOR_MAX,
        value=0.85,
        step=0.01,
        help="Fraction of capacity loaded, from 0 to 1 inclusive.",
    )
    bunker_price = st.number_input(
        "Bunker price (USD/tonne)",
        min_value=BUNKER_PRICE_MIN,
        value=876.5,
        step=1.0,
        help="Fuel price; must be greater than zero.",
    )
    canal_duration_h = st.number_input(
        "Canal duration (hours)",
        min_value=CANAL_HOURS_MIN,
        value=12.0,
        step=1.0,
        help="Time attributed to transiting the canal, in hours.",
    )
    waiting_days = st.number_input(
        "Waiting duration (days)",
        min_value=WAITING_DAYS_MIN,
        value=0.0,
        step=0.5,
        help="Explicit waiting time in days; defaults to 0. Never inferred from slots.",
    )
    deadline_days = st.number_input(
        "Deadline (days)",
        min_value=DEADLINE_DAYS_MIN,
        value=30.0,
        step=1.0,
        help="Delivery deadline in days; must be greater than zero.",
    )

    priority_label = st.selectbox(
        "Selection priority",
        options=list(PRIORITY_LABEL_TO_VALUE.keys()),
    )
    selection_priority = PRIORITY_LABEL_TO_VALUE[priority_label]

    suez_choice = st.radio(
        "Suez availability",
        options=("Available", "Unavailable"),
        index=0,
        help="Explicit scenario assumption about whether Suez is available.",
    )
    suez_available = suez_choice == "Available"

    fuel_types = _available_fuel_types(load_result)
    if fuel_types:
        fuel_type = st.selectbox("Fuel type", list(fuel_types))
    else:
        fuel_type = ""
        missing.append(
            "No emission factors were loaded, so no fuel type can be selected."
        )

    # Defensive range re-check (Requirement 13.7). Streamlit clamps to the
    # configured bounds, but if a value still arrives out of range we flag it so
    # the caller can reject it and retain the last valid scenario.
    if speed_kn is not None and not _in_range(speed_kn, minimum=SPEED_MIN_KN):
        out_of_range.append("Speed must be greater than zero knots.")
    if load_factor is not None and not _in_range(
        load_factor, minimum=LOAD_FACTOR_MIN, maximum=LOAD_FACTOR_MAX
    ):
        out_of_range.append("Load factor must be between 0 and 1 inclusive.")
    if bunker_price is not None and not _in_range(
        bunker_price, minimum=BUNKER_PRICE_MIN
    ):
        out_of_range.append("Bunker price must be greater than zero.")
    if waiting_days is not None and not _in_range(
        waiting_days, minimum=WAITING_DAYS_MIN
    ):
        out_of_range.append("Waiting duration must be zero or more days.")
    if deadline_days is not None and not _in_range(
        deadline_days, minimum=DEADLINE_DAYS_MIN
    ):
        out_of_range.append("Deadline must be greater than zero days.")
    if canal_duration_h is not None and not _in_range(
        canal_duration_h, minimum=CANAL_HOURS_MIN
    ):
        out_of_range.append("Canal duration must be zero or more hours.")

    if canal_state is None:
        missing.append(
            "A canal state is required. Choose a preset or complete the custom "
            "draft and booking-slot inputs."
        )

    # Optional draft-based cargo-loss controls (Requirement 20.11). When the
    # toggle is off these are the no-loss defaults, so the Scenario matches v1.
    (
        draft_loss_enabled,
        containers_lost_per_10cm,
        avg_teu_per_container,
    ) = render_draft_loss_controls(load_result)

    return ControlReadings(
        od_pair=selected_pair,
        canal_state=canal_state,
        speed_kn=None if speed_kn is None else float(speed_kn),
        load_factor=None if load_factor is None else float(load_factor),
        bunker_price_usd_per_t=(
            None if bunker_price is None else float(bunker_price)
        ),
        canal_duration_h=(
            None if canal_duration_h is None else float(canal_duration_h)
        ),
        waiting_days=None if waiting_days is None else float(waiting_days),
        deadline_days=None if deadline_days is None else float(deadline_days),
        suez_available=suez_available,
        selection_priority=selection_priority,
        fuel_type=fuel_type,
        missing=tuple(missing),
        out_of_range=tuple(out_of_range),
        draft_loss_enabled=draft_loss_enabled,
        containers_lost_per_10cm=containers_lost_per_10cm,
        avg_teu_per_container=avg_teu_per_container,
    )


def build_scenario_from_controls(
    load_result: LoadResult,
) -> tuple[Scenario | None, list[str], ODPair | None]:
    """Render preset + controls and assemble a :class:`Scenario`.

    Single entry point for ``app.py`` (Task 12). Renders the preset selector,
    resolves the canal state (preset or custom), renders the scenario controls,
    and assembles the scenario. When required inputs are missing or an input is
    out of range, returns ``None`` for the scenario, surfaces plain-language
    messages via :func:`streamlit.warning`, and retains the last fully valid
    scenario in ``st.session_state`` so the UI can keep showing prior results
    (Requirements 12.6, 13.6, 13.7).

    Args:
        load_result: The loaded required/optional data.

    Returns:
        A ``(scenario, messages, selected_od_pair)`` tuple. ``scenario`` is the
        freshly assembled scenario, or the retained last-valid scenario, or
        ``None`` when none is available; ``messages`` names any missing or
        out-of-range inputs; ``selected_od_pair`` is the chosen OD pair (or
        ``None``).
    """
    preset = render_preset_selector()

    if preset == PRESET_CUSTOM:
        canal_state, state_messages = render_custom_canal_state()
    else:
        canal_state, state_messages = resolve_preset_canal_state(
            load_result, preset
        )

    for message in state_messages:
        st.warning(message)

    readings = render_scenario_controls(load_result, canal_state)
    scenario, assemble_messages = assemble_scenario(readings)

    messages = list(state_messages) + list(assemble_messages)

    if scenario is not None:
        # Record the last fully valid scenario so an out-of-range change can
        # fall back to it (Requirement 13.7).
        st.session_state[LAST_VALID_SCENARIO_KEY] = scenario
        return scenario, messages, readings.od_pair

    # No valid scenario this run: surface messages and retain the last valid
    # scenario if one exists.
    for message in messages:
        st.warning(message)

    retained = st.session_state.get(LAST_VALID_SCENARIO_KEY)
    return retained, messages, readings.od_pair


def render_sidebar(
    load_result: LoadResult,
) -> tuple[Scenario | None, list[str], ODPair | None]:
    """Render the preset and scenario controls inside the Streamlit sidebar.

    Thin wrapper over :func:`build_scenario_from_controls` so ``app.py`` can
    place all controls in the sidebar with one call.

    Args:
        load_result: The loaded required/optional data.

    Returns:
        The same ``(scenario, messages, selected_od_pair)`` tuple as
        :func:`build_scenario_from_controls`.
    """
    with st.sidebar:
        st.header("Scenario")
        return build_scenario_from_controls(load_result)
