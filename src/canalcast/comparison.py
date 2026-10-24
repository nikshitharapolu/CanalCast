"""Route comparison for the CanalCast Calculation_Core.

This module is part of the pure Calculation_Core. It performs NO file I/O and
makes NO network calls, and it imports no library that does either. It imports
only from :mod:`.models`, :mod:`.results`, :mod:`.calculations`, and the
standard library's ``typing`` facilities. A boundary test (Task 8.1) scans this
module for forbidden imports.

Task 6.1 implements :func:`compute_option`, which assembles a complete
:class:`~canalcast.results.OptionResult` for a single routing option by calling
the pure calculation functions. Task 6.2 implements :func:`compare_od_pair`,
which compares the Panama and Suez options for one OD pair, applies the distance
precondition and Suez-availability exclusion, and selects the single
non-excluded Feasible_Option that minimizes the chosen Selection_Priority metric
with deterministic tie handling (Requirements 11.1-11.10).

Independent evaluation (Requirements 3.1, 3.4): every metric is computed
independently from its own inputs. One disabled calculation never suppresses
another whose inputs are present; a metric that cannot be produced is an
:class:`~canalcast.models.Unavailable`, while the others still compute.

Canal-state maximum draft is carried only as CONTEXT and never reduces TEU,
cost, fuel, or CO2 in v1 (Requirements 10.1, 10.3, 10.4). Zero loaded TEU yields
an Infeasible_Result with an undefined fuel cost per TEU (Requirement 11.9).
"""

from __future__ import annotations

import math
from typing import Mapping

from .calculations import (
    canal_fuel_t,
    co2_tank_to_wake_t,
    draft_cargo_loss,
    fuel_cost_per_teu_usd,
    fuel_rate_t_per_day,
    journey_time_hours,
    loaded_teu,
    sailing_fuel_t,
    sailing_time_hours,
    total_voyage_fuel_t,
    voyage_fuel_cost_usd,
    waiting_fuel_t,
)
from .models import (
    NotModeled,
    CanalState,
    Constants,
    DraftLoss,
    EmissionFactor,
    ODPair,
    ProvenancedValue,
    RouteOption,
    Scenario,
    Status,
    Unavailable,
)
from .results import (
    SAILING_ONLY_LABEL,
    ComparisonResult,
    FuelBreakdown,
    JourneyTimeBreakdown,
    OptionResult,
    Selection,
)

# Fixed disclosure that draft cargo-capacity effects are not modeled in v1
# (Requirement 10.4).
DRAFT_NOT_MODELED_DISCLOSURE = (
    "Draft cargo-capacity effects are not modeled in version 1."
)

# Fixed disclosure recorded whenever the optional draft-based cargo-loss
# adjustment is enabled: the adjustment rests on an ANALYST-ESTIMATE
# containers-lost figure and an ASSUMPTION average-TEU-per-container factor
# (Requirement 20.9).
def _draft_loss_disclosure(
    estimate: float | None,
    avg_teu: float | None,
    capacity_teu: float | None,
    load_factor: float | None,
) -> str:
    """Build the disclosure shown whenever draft-based cargo loss is enabled.

    States the slope and container-to-TEU factor actually in use, the
    applicability limit for the modeled ship, and that voyage fuel and CO2 are
    held fixed when payload falls (Requirements 20.9, 20.10).
    """
    slope = f"{estimate:g}" if estimate is not None else "an unresolved number of"
    conv = f"{avg_teu:g}" if avg_teu is not None else "an unresolved number of"
    if capacity_teu is not None and load_factor is not None:
        ship = f"the modeled {capacity_teu:,.0f}-TEU ship with a load factor of {load_factor:.0%}"
    else:
        ship = "the modeled ship"
    return (
        f"Assumed slope: {slope} containers lost per 10 cm of draft shortfall, "
        "applied linearly from the reference draft (the default of 100 is an "
        "analyst estimate for Asia-USEC carriers, Seatrade Maritime, Jul 2026, "
        "not a measurement). "
        f"Container-to-TEU conversion: each lost container is assumed to be {conv} "
        "TEU (an assumption; a 20 ft container is 1 TEU and a 40 ft container is "
        "2 TEU). "
        f"Applicability: the estimate is not specific to {ship}, and the model "
        "assumes that ship would otherwise load to the full reference draft, so a "
        "ship loaded below that draft could lose less or nothing. "
        "Voyage fuel and CO2 tonnes are held fixed when payload falls (no fuel "
        "saving from lighter loading), so only loaded TEU and the per-TEU figures "
        "change. These are estimates, not observed values."
    )


# Notes shown in place of the v1 "not modeled" text when draft loss is enabled.
DRAFT_MODELED_NOTE = (
    "Draft cargo loss is modeled as an optional estimate for this option; see "
    "the draft-based cargo loss disclosure."
)
DRAFT_NOT_APPLIED_SUEZ = (
    "Panama Canal draft limits are not applied to the Suez route, so no "
    "draft-based loss is modeled for this option."
)

#: Suez waiting is outside the v1 model (Requirements 6.5, 6.12, 6.13, 7.7).
SUEZ_WAITING_NOT_MODELED = NotModeled(
    reason="Suez waiting time is not modeled; the waiting input applies only to Panama"
)
SUEZ_WAITING_DISCLOSURE = (
    "Suez waiting time is not modeled: the waiting input applies only to the "
    "Panama route, so the Suez journey time and fuel exclude any queueing."
)
SUEZ_WAITING_EXCLUSION = "Suez waiting time (not modeled)"
# Cost/emission items excluded from every option result (Requirement 8.6).
EXCLUSIONS: tuple[str, ...] = (
    "tolls",
    "insurance",
    "carrier surcharges",
    "lifecycle emissions",
    "draft cargo-loss",
)

# Per-metric tie tolerances, each in that metric's OWN unit (Requirements 11.7,
# 11.8). A tie exists when two feasible candidates' metric values are within the
# tolerance of each other. The values are documented separately per metric
# because the units differ (hours vs USD/TEU vs tonnes).
TIE_TOLERANCE_HOURS: float = 0.001  # for the "fastest" metric (journey hours)
TIE_TOLERANCE_USD_PER_TEU: float = 0.001  # for "lowest_cost_per_teu"
TIE_TOLERANCE_CO2_T: float = 0.001  # for "lowest_co2" (tonnes)

# Tie tolerance keyed by selection priority (metric's own unit).
_METRIC_TOLERANCE: Mapping[str, float] = {
    "fastest": TIE_TOLERANCE_HOURS,
    "lowest_cost_per_teu": TIE_TOLERANCE_USD_PER_TEU,
    "lowest_co2": TIE_TOLERANCE_CO2_T,
}

# Reason recorded when Suez is excluded by the explicit scenario assumption
# (Requirements 11.2, 11.3).
_SUEZ_UNAVAILABLE_REASON = "marked unavailable by scenario assumption"

# Explicit unit per metric name (Requirement 11.10).
_UNITS: Mapping[str, str] = {
    "journey_time_h": "hours",
    "sailing_time_h": "hours",
    "canal_duration_h": "hours",
    "waiting_duration_h": "hours",
    "fuel_rate_t_per_day": "t/day",
    "sailing_fuel_t": "t",
    "waiting_fuel_t": "t",
    "canal_fuel_t": "t",
    "total_voyage_fuel_t": "t",
    "voyage_fuel_cost_usd": "USD",
    "fuel_cost_per_teu_usd": "USD/TEU",
    "co2_tank_to_wake_t": "t CO2",
    "loaded_teu": "TEU",
    "sailing_only_fuel_cost_usd": "USD",
    "sailing_only_co2_t": "t CO2",
}


def _pv_float(pv: ProvenancedValue | None) -> float | None:
    """Return a finite float from a :class:`ProvenancedValue`, else ``None``.

    Used only to feed numeric constants into the calculation functions. A
    missing record or a non-numeric/range value (kept as ``str``) yields
    ``None`` so the dependent calculation is cleanly disabled rather than
    crashing.
    """
    if pv is None:
        return None
    try:
        return float(pv.value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _merge_inputs(
    base: Unavailable, *extras: object
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``base`` missing/invalid input names plus any from ``extras``.

    Only input NAMES are merged; no numeric value is ever carried over.
    """
    missing = list(base.missing_inputs)
    invalid = list(base.invalid_inputs)
    for extra in extras:
        if isinstance(extra, Unavailable):
            missing += [m for m in extra.missing_inputs if m not in missing]
            invalid += [i for i in extra.invalid_inputs if i not in invalid]
    return tuple(missing), tuple(invalid)


def _total_fuel_gap(total_fuel: Unavailable, fuel: FuelBreakdown) -> Unavailable:
    """Explain why total voyage fuel is unresolved (Requirements 3.1, 7.5).

    Names each unresolved fuel line item and the inputs behind it, so dependent
    outputs can report exactly what is missing.
    """
    items = (
        ("sailing fuel", fuel.sailing_fuel_t),
        ("waiting fuel", fuel.waiting_fuel_t),
        ("canal fuel", fuel.canal_fuel_t),
    )
    unresolved = [name for name, item in items if isinstance(item, Unavailable)]
    missing, invalid = _merge_inputs(total_fuel, *(item for _, item in items))
    detail = ", ".join(unresolved) if unresolved else "a fuel component"
    return Unavailable(
        reason=f"total voyage fuel is unresolved ({detail})",
        missing_inputs=missing,
        invalid_inputs=invalid,
    )


def _requires_total_fuel(
    label: str, fuel_gap: Unavailable, *extras: object
) -> Unavailable:
    """Return ``Unavailable`` for an output that needs resolved total fuel.

    Voyage fuel cost, fuel cost per loaded TEU, and tank-to-wake CO2 depend on
    resolved total voyage fuel only (Requirements 8.1, 8.5, 9.1). Input names
    from ``extras`` (for example a missing bunker price) are merged so every
    missing input is reported (Requirement 3.1).
    """
    missing, invalid = _merge_inputs(fuel_gap, *extras)
    return Unavailable(
        reason=f"{label} requires resolved total voyage fuel; {fuel_gap.reason}",
        missing_inputs=missing,
        invalid_inputs=invalid,
    )


def compute_option(
    route_opt: RouteOption,
    scenario: Scenario,
    constants: Constants,
    emission_factor: EmissionFactor | None,
) -> OptionResult:
    """Assemble a complete :class:`OptionResult` for one routing option.

    Each metric is computed independently (Requirements 3.1, 3.4); a disabled
    calculation is recorded as an :class:`Unavailable` and never suppresses the
    others.

    Voyage-fuel dependency: ``voyage_fuel_cost_usd``, ``fuel_cost_per_teu_usd``
    and ``co2_tank_to_wake_t`` use RESOLVED ``total_voyage_fuel_t`` only
    (Requirements 8.1, 8.3, 9.1). There is no fallback to sailing fuel: when any
    fuel component is unresolved (e.g. a positive canal duration with no canal
    fuel rate), those three outputs are ``Unavailable`` and name the unresolved
    component(s) and inputs (Requirements 3.1-3.3, 7.5, 8.5). In that case, and
    only when sailing fuel itself is resolved, the separately named
    ``sailing_only_fuel_cost_usd`` / ``sailing_only_co2_t`` fields carry a
    partial estimate labeled with :data:`~canalcast.results.SAILING_ONLY_LABEL`;
    selection never reads them. A zero waiting or canal duration resolves its
    line item to ``0.0`` even without a rate, so the total still resolves.
    """
    # --- Journey time (independent) ------------------------------------
    distance_value = (
        route_opt.distance_nm.value if route_opt.distance_nm is not None else None
    )
    # distance_nm.value is numeric for route distances; guard anyway.
    distance_nm: float | None
    if isinstance(distance_value, (int, float)) and not isinstance(distance_value, bool):
        distance_nm = float(distance_value)
    else:
        distance_nm = None

    sailing_time = sailing_time_hours(distance_nm, scenario.speed_kn)

    # Echo the scenario-provided canal/waiting durations as the breakdown
    # components. A missing (None) or negative value is shown as Unavailable so
    # the component is explicit, but the provided value is preferred.
    canal_component = _echo_duration(scenario.canal_duration_h, "canal_duration_h")
    # Waiting applies only to Panama; Suez waiting is not modeled (Req 6.5-6.7).
    is_panama = route_opt.option == "panama"
    waiting_input: float | None | NotModeled = (
        scenario.waiting_duration_h if is_panama else SUEZ_WAITING_NOT_MODELED
    )
    waiting_component = (
        _echo_duration(scenario.waiting_duration_h, "waiting_duration_h")
        if is_panama
        else SUEZ_WAITING_NOT_MODELED
    )

    journey_time = journey_time_hours(
        sailing_time, scenario.canal_duration_h, waiting_input
    )

    journey = JourneyTimeBreakdown(
        sailing_time_h=sailing_time,
        canal_duration_h=canal_component,
        waiting_duration_h=waiting_component,
        journey_time_h=journey_time,
    )

    # --- Fuel (independent line items) ---------------------------------
    fuel_rate = fuel_rate_t_per_day(
        scenario.speed_kn,
        _pv_float(constants.base_fuel_t_per_day),
        _pv_float(constants.base_speed_kn),
        _pv_float(constants.speed_exponent),
    )
    sailing_fuel = sailing_fuel_t(fuel_rate, sailing_time)
    waiting_fuel = (
        waiting_fuel_t(scenario.waiting_duration_h, constants.waiting_fuel_t_per_day)
        if is_panama
        else SUEZ_WAITING_NOT_MODELED
    )
    canal_fuel = canal_fuel_t(
        scenario.canal_duration_h, constants.canal_fuel_t_per_day
    )
    total_fuel = total_voyage_fuel_t(sailing_fuel, waiting_fuel, canal_fuel)

    fuel = FuelBreakdown(
        fuel_rate_t_per_day=fuel_rate,
        sailing_fuel_t=sailing_fuel,
        waiting_fuel_t=waiting_fuel,
        canal_fuel_t=canal_fuel,
        total_voyage_fuel_t=total_fuel,
    )

    # Why the total is unresolved (None when it resolved). Voyage cost, cost per
    # TEU, and CO2 depend on the resolved total only; there is no sailing-fuel
    # fallback (Requirements 3.1-3.3, 7.5, 8.1, 8.5, 9.1).
    fuel_gap: Unavailable | None = (
        _total_fuel_gap(total_fuel, fuel)
        if isinstance(total_fuel, Unavailable)
        else None
    )

    # --- Loaded TEU (independent) --------------------------------------
    base_loaded = loaded_teu(
        _pv_float(constants.ship_capacity_teu), scenario.load_factor
    )

    # --- Optional draft-based cargo loss (Requirement 20) --------------
    # Default-off path (draft_loss_enabled is False) leaves loaded TEU at the
    # base value and all draft-loss fields at their no-loss defaults, so v1
    # behavior is byte-identical (Requirements 20.1, 20.9).
    loaded = base_loaded
    draft_shortfall_ft: float | None = None
    draft_containers_lost: float | None = None
    draft_teu_lost: float | None = None
    draft_loss_disclosure: str | None = None
    draft_loss_computed = False

    if scenario.draft_loss_enabled:
        # Containers-lost estimate: explicit scenario override, else the loaded
        # constant (Requirement 20.5).
        if scenario.containers_lost_per_10cm is not None:
            estimate = scenario.containers_lost_per_10cm
        else:
            estimate = _pv_float(
                constants.context.get("containers_lost_per_10cm_draft_cut")
            )
        reference_draft = _pv_float(constants.reference_draft_ft)
        canal_state_max_draft = _pv_float(scenario.canal_state.max_draft_ft)

        draft_loss = draft_cargo_loss(
            route_opt.option,
            canal_state_max_draft,
            reference_draft,
            estimate,
            scenario.avg_teu_per_container,
            enabled=scenario.draft_loss_enabled,
        )

        if route_opt.option == "panama":
            base_disclosure = _draft_loss_disclosure(
                estimate,
                scenario.avg_teu_per_container,
                _pv_float(constants.ship_capacity_teu),
                scenario.load_factor,
            )
        else:
            base_disclosure = DRAFT_NOT_APPLIED_SUEZ
        draft_loss_disclosure = base_disclosure
        if isinstance(draft_loss, DraftLoss):
            draft_loss_computed = True
            draft_shortfall_ft = draft_loss.shortfall_ft
            draft_containers_lost = draft_loss.containers_lost
            draft_teu_lost = draft_loss.teu_lost
            # Only adjust a resolved base loaded TEU; never invent one when the
            # base is Unavailable (Requirement 20.8).
            if not isinstance(base_loaded, Unavailable):
                # Clamp at zero; a draft adjustment never produces negative TEU
                # (Requirement 20.8).
                loaded = max(0.0, float(base_loaded) - draft_loss.teu_lost)
        else:
            # The loss could not be computed (a required input was missing or
            # invalid). Fail closed: loaded TEU (and so cost per TEU) becomes
            # Unavailable naming the inputs, never the unadjusted base payload
            # (Task 15.3, Requirement 20.8).
            loaded = Unavailable(
                reason="draft-adjusted loaded TEU requires the draft-loss inputs",
                missing_inputs=draft_loss.missing_inputs,
                invalid_inputs=draft_loss.invalid_inputs,
            )
            missing_bits = ", ".join(
                draft_loss.missing_inputs + draft_loss.invalid_inputs
            )
            draft_loss_disclosure = (
                base_disclosure
                + " The adjustment could not be computed because of unresolved "
                + f"inputs ({missing_bits})."
                if missing_bits
                else base_disclosure
                + " The adjustment could not be computed because of unresolved inputs."
            )

    # --- Voyage fuel cost and CO2 (resolved total voyage fuel only) ----
    sailing_only_cost: float | Unavailable | None = None
    sailing_only_co2: float | Unavailable | None = None
    sailing_only_label: str | None = None
    if fuel_gap is None:
        voyage_cost = voyage_fuel_cost_usd(
            total_fuel, scenario.bunker_price_usd_per_t
        )
        co2 = co2_tank_to_wake_t(total_fuel, emission_factor, scenario.fuel_type)
    else:
        # Separately named, labeled sailing-only estimates (never voyage totals,
        # never read by selection), only when sailing fuel itself resolved.
        if not isinstance(sailing_fuel, Unavailable):
            sailing_only_cost = voyage_fuel_cost_usd(
                sailing_fuel, scenario.bunker_price_usd_per_t
            )
            sailing_only_co2 = co2_tank_to_wake_t(
                sailing_fuel, emission_factor, scenario.fuel_type
            )
            sailing_only_label = SAILING_ONLY_LABEL
        # Headline outputs stay Unavailable. Only the input NAMES of an
        # unavailable sailing-only result (e.g. a missing bunker price) are
        # merged, so every missing input is reported (Req 3.1); no number is
        # ever carried over.
        voyage_cost = _requires_total_fuel(
            "voyage fuel cost", fuel_gap, sailing_only_cost
        )
        co2 = _requires_total_fuel("tank-to-wake CO2", fuel_gap, sailing_only_co2)

    # --- Feasibility / deadline status ---------------------------------
    # "undetermined" is never a miss; it names its cause (Task 15.2).
    deadline_h = scenario.deadline_h
    deadline_ok = (
        deadline_h is not None and math.isfinite(deadline_h) and deadline_h > 0
    )
    deadline_undetermined_inputs: tuple[str, ...] = ()
    if not isinstance(journey_time, Unavailable) and deadline_ok:
        feasible: bool | None = journey_time <= deadline_h
        deadline_status = "meets deadline" if feasible else "misses deadline"
    else:
        feasible = None
        deadline_status = "undetermined"
        causes: list[str] = []
        if isinstance(journey_time, Unavailable):
            causes += list(journey_time.missing_inputs)
            causes += list(journey_time.invalid_inputs)
            if not causes:
                causes.append("journey_time_h")
        if not deadline_ok:
            causes.append("deadline_h")
        deadline_undetermined_inputs = tuple(dict.fromkeys(causes))

    # --- Infeasible_Result when loaded TEU is zero (Requirement 11.9) ---
    infeasible = (not isinstance(loaded, Unavailable)) and loaded == 0
    infeasible_reason: str | None
    if infeasible:
        infeasible_reason = (
            "loaded TEU is zero, so this option carries no payload; "
            "fuel cost per TEU is undefined"
        )
        # Fuel cost per TEU stays Unavailable when infeasible.
        cost_per_teu: float | Unavailable = Unavailable(
            reason="loaded TEU is zero", invalid_inputs=("loaded_teu",)
        )
    elif fuel_gap is not None:
        infeasible_reason = None
        cost_per_teu = _requires_total_fuel(
            "fuel cost per loaded TEU", fuel_gap, sailing_only_cost, loaded
        )
    else:
        infeasible_reason = None
        cost_per_teu = fuel_cost_per_teu_usd(voyage_cost, loaded)

    # --- Input provenance (Requirement 11.10) --------------------------
    input_provenance: dict[str, ProvenancedValue] = {
        "ship_capacity_teu": constants.ship_capacity_teu,
        "base_speed_kn": constants.base_speed_kn,
        "base_fuel_t_per_day": constants.base_fuel_t_per_day,
        "speed_exponent": constants.speed_exponent,
        "route_provenance": route_opt.provenance,
    }
    if route_opt.distance_nm is not None:
        input_provenance["distance_nm"] = route_opt.distance_nm
    if constants.waiting_fuel_t_per_day is not None:
        input_provenance["waiting_fuel_t_per_day"] = constants.waiting_fuel_t_per_day
    if constants.canal_fuel_t_per_day is not None:
        input_provenance["canal_fuel_t_per_day"] = constants.canal_fuel_t_per_day
    input_provenance["bunker_price_reference"] = constants.bunker_price_usd_per_t

    # Every result-driving scenario input, plus the emission factor (Task 15.4).
    scenario_inputs: list[tuple[str, float | str | None, str]] = [
        ("speed_kn", scenario.speed_kn, "knots"),
        ("load_factor", scenario.load_factor, "fraction"),
        ("bunker_price_usd_per_t", scenario.bunker_price_usd_per_t, "USD/t"),
        ("canal_duration_h", scenario.canal_duration_h, "hours"),
        ("deadline_h", scenario.deadline_h, "hours"),
        ("suez_available", "available" if scenario.suez_available else "unavailable", "-"),
        ("fuel_type", scenario.fuel_type, "-"),
    ]
    if is_panama:
        scenario_inputs.append(("waiting_duration_h", scenario.waiting_duration_h, "hours"))
    for name, value, unit in scenario_inputs:
        if value is not None:
            input_provenance[name] = ProvenancedValue(
                value=value,
                unit=unit,
                rationale="scenario input chosen in the controls",
                status=Status.ASSUMPTION,
            )
    if emission_factor is not None:
        input_provenance["co2_t_per_fuel_t"] = emission_factor.co2_t_per_fuel_t

    # Draft-loss input provenance (best-effort; never crash if a piece is
    # absent) (Requirements 20.5, 20.6, 20.9).
    if scenario.draft_loss_enabled:
        input_provenance["reference_draft_ft"] = constants.reference_draft_ft
        estimate_pv = constants.context.get("containers_lost_per_10cm_draft_cut")
        if scenario.containers_lost_per_10cm is not None:
            input_provenance["containers_lost_per_10cm"] = ProvenancedValue(
                value=float(scenario.containers_lost_per_10cm),
                unit="containers per 10 cm of draft shortfall",
                rationale="explicit scenario override of the analyst estimate",
                status=Status.ASSUMPTION,
            )
        elif estimate_pv is not None:
            input_provenance["containers_lost_per_10cm"] = estimate_pv
        input_provenance["avg_teu_per_container"] = ProvenancedValue(
            value=float(scenario.avg_teu_per_container),
            unit="TEU per container",
            rationale="assumed average TEU per lost container",
            status=Status.ASSUMPTION,
        )

    units: dict[str, str] = dict(_UNITS)

    modeled_here = draft_loss_computed and route_opt.option == "panama"
    without_draft_exclusion = tuple(x for x in EXCLUSIONS if x != "draft cargo-loss")
    if modeled_here:
        draft_note = DRAFT_MODELED_NOTE
        option_exclusions = without_draft_exclusion
    elif scenario.draft_loss_enabled and route_opt.option == "suez":
        # Draft loss is switched on but does not apply to Suez, so "draft
        # cargo-loss" is not an exclusion the user needs warned about here.
        draft_note = DRAFT_NOT_APPLIED_SUEZ
        option_exclusions = without_draft_exclusion
    else:
        draft_note = DRAFT_NOT_MODELED_DISCLOSURE
        option_exclusions = EXCLUSIONS
    if not is_panama:
        option_exclusions = option_exclusions + (SUEZ_WAITING_EXCLUSION,)

    return OptionResult(
        option=route_opt.option,
        route_id=route_opt.route_id,
        units=units,
        journey=journey,
        fuel=fuel,
        loaded_teu=loaded,
        voyage_fuel_cost_usd=voyage_cost,
        fuel_cost_per_teu_usd=cost_per_teu,
        co2_tank_to_wake_t=co2,
        feasible=feasible,
        deadline_status=deadline_status,
        infeasible=infeasible,
        infeasible_reason=infeasible_reason,
        draft_context_ft=scenario.canal_state.max_draft_ft,
        draft_not_modeled_disclosure=draft_note,
        exclusions=option_exclusions,
        input_provenance=input_provenance,
        draft_loss_enabled=scenario.draft_loss_enabled,
        draft_shortfall_ft=draft_shortfall_ft,
        containers_lost=draft_containers_lost,
        teu_lost=draft_teu_lost,
        draft_loss_disclosure=draft_loss_disclosure,
        sailing_only_fuel_cost_usd=sailing_only_cost,
        sailing_only_co2_t=sailing_only_co2,
        sailing_only_label=sailing_only_label,
        deadline_undetermined_inputs=deadline_undetermined_inputs,
        waiting_not_modeled_disclosure=None if is_panama else SUEZ_WAITING_DISCLOSURE,
    )


def _echo_duration(value: float | None, name: str) -> float | Unavailable:
    """Echo a scenario duration as a breakdown component.

    Prefers to show the provided value; a missing (``None``) or negative value
    is surfaced as an :class:`Unavailable` naming the input so the component is
    explicit rather than silently zeroed.
    """
    if value is None:
        return Unavailable(
            reason=f"{name} is an unresolved input",
            missing_inputs=(name,),
        )
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        return Unavailable(
            reason=f"{name} must be a non-negative number; it is invalid",
            invalid_inputs=(name,),
        )
    return float(value)


def _distance_float(route_opt: RouteOption | None) -> float | None:
    """Return a positive distance in nautical miles, or ``None``.

    Yields ``None`` when the option itself is absent, its ``distance_nm`` record
    is absent, the value is non-numeric, or the value is not strictly positive.
    Used only by the Task 11.1 distance precondition.
    """
    if route_opt is None or route_opt.distance_nm is None:
        return None
    value = route_opt.distance_nm.value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    distance = float(value)
    if distance <= 0:
        return None
    return distance


def _metric_value(
    option: OptionResult, priority: str
) -> float | Unavailable:
    """Return the selection metric for ``option`` under ``priority``.

    The metric is read in its own unit (Requirement 11.4):

    - ``"fastest"`` -> ``journey.journey_time_h`` (hours)
    - ``"lowest_cost_per_teu"`` -> ``fuel_cost_per_teu_usd`` (USD/TEU)
    - ``"lowest_co2"`` -> ``co2_tank_to_wake_t`` (tonnes)

    An :class:`Unavailable` metric means the option is not selectable on that
    priority (the caller filters those out as selection candidates).
    """
    if priority == "fastest":
        return option.journey.journey_time_h
    if priority == "lowest_cost_per_teu":
        return option.fuel_cost_per_teu_usd
    if priority == "lowest_co2":
        return option.co2_tank_to_wake_t
    # Unknown priority: nothing is selectable on it.
    return Unavailable(
        reason=f"unknown selection priority {priority!r}",
        invalid_inputs=("selection_priority",),
    )


def _journey_float(option: OptionResult) -> float | None:
    """Return the resolved journey time in hours, or ``None`` if unavailable."""
    jt = option.journey.journey_time_h
    if isinstance(jt, Unavailable):
        return None
    return float(jt)


def compare_od_pair(
    od_pair: ODPair,
    scenario: Scenario,
    constants: Constants,
    emission_factor: EmissionFactor | None,
    canal_state: CanalState,
) -> ComparisonResult:
    """Compare the Panama and Suez options for one OD pair and select by priority.

    The ``canal_state`` parameter matches the design signature; ``scenario`` is
    the source of truth for :func:`compute_option` inputs (``scenario.canal_state``
    supplies the draft context), so ``canal_state`` is accepted for signature
    compatibility and not used to override the scenario.

    Behaviour (Requirements 11.1-11.10):

    1. Distance precondition (11.1): both options must exist and each carry a
       strictly positive ``distance_nm``. Otherwise the comparison is rejected
       with a naming ``comparison_error`` and NO selection is made.
    2. Both options are computed via :func:`compute_option` (Panama first).
    3. Suez availability (11.2, 11.3): when ``scenario.suez_available`` is
       ``False`` Suez is excluded from selection and the exclusion recorded; the
       computed Suez result is still returned for display.
    4. Zero-TEU options are also excluded from selection when the active priority
       is ``lowest_cost_per_teu`` (11.9).
    5. Selection minimizes the single chosen metric (11.4, 11.6), with ties
       resolved metric -> lower journey time -> Panama convention (11.7, 11.8).
    6. Deadline miss (11.5): when no non-excluded option is feasible, no
       selection is made and the minimum-journey-time option is the closest.
    """
    panama_route = od_pair.panama
    suez_route = od_pair.suez

    # --- 1. Distance precondition (Requirement 11.1) -------------------
    panama_distance = _distance_float(panama_route)
    suez_distance = _distance_float(suez_route)

    if panama_distance is None or suez_distance is None:
        return _rejected_for_distance(
            od_pair, scenario, panama_distance, suez_distance
        )

    # --- 2. Compute both options (Panama first) ------------------------
    # od_pair.panama / .suez are guaranteed non-None here because their
    # distances resolved to positive floats above.
    assert panama_route is not None and suez_route is not None
    panama_result = compute_option(
        panama_route, scenario, constants, emission_factor
    )
    suez_result = compute_option(suez_route, scenario, constants, emission_factor)

    results: dict[str, OptionResult] = {
        "panama": panama_result,
        "suez": suez_result,
    }

    # --- 3. Exclusions -------------------------------------------------
    excluded_options: list[str] = []
    exclusion_reasons: dict[str, str] = {}

    # Suez availability is an explicit scenario assumption (Requirement 11.2).
    if not scenario.suez_available:
        excluded_options.append("suez")
        exclusion_reasons["suez"] = _SUEZ_UNAVAILABLE_REASON

    priority = scenario.selection_priority

    # Zero-TEU (infeasible) options are excluded from cost/TEU selection when the
    # active priority is lowest_cost_per_teu (Requirement 11.9).
    if priority == "lowest_cost_per_teu":
        for name, option in results.items():
            if option.infeasible and name not in excluded_options:
                excluded_options.append(name)
                exclusion_reasons[name] = (
                    "loaded TEU is zero, so fuel cost per TEU is undefined; "
                    "excluded from cost-per-TEU selection"
                )

    # --- 4. Candidate set = non-excluded options -----------------------
    candidate_names = [n for n in ("panama", "suez") if n not in excluded_options]

    # --- 5. Feasibility & deadline handling ----------------------------
    feasible_candidates = [
        n for n in candidate_names if results[n].feasible is True
    ]

    selection = _build_selection(
        priority=priority,
        results=results,
        candidate_names=candidate_names,
        feasible_candidates=feasible_candidates,
        exclusion_reasons=exclusion_reasons,
    )

    return ComparisonResult(
        od_pair_id=od_pair.route_id,
        panama=panama_result,
        suez=suez_result,
        excluded_options=tuple(excluded_options),
        exclusion_reasons=exclusion_reasons,
        selection=selection,
        comparison_error=None,
    )


def _rejected_for_distance(
    od_pair: ODPair,
    scenario: Scenario,
    panama_distance: float | None,
    suez_distance: float | None,
) -> ComparisonResult:
    """Build the rejected :class:`ComparisonResult` for a bad distance pair.

    Names which distance(s) are missing/invalid in the ``comparison_error`` and
    makes NO selection (Requirement 11.1). The per-option results are left as
    ``None`` because the comparison does not proceed.
    """
    bad: list[str] = []
    if panama_distance is None:
        bad.append("panama")
    if suez_distance is None:
        bad.append("suez")
    which = " and ".join(bad)
    reason = (
        "comparison rejected: the OD pair requires both a Panama distance > 0 nm "
        f"and a Suez distance > 0 nm; missing or invalid distance for: {which}"
    )
    comparison_error = Unavailable(
        reason=reason,
        missing_inputs=tuple(f"{name}.distance_nm" for name in bad),
        invalid_inputs=tuple(f"{name}.distance_nm" for name in bad),
    )
    selection = Selection(
        selected_option=None,
        priority=scenario.selection_priority,
        no_feasible_option=False,
        closest_option=None,
        tie_resolution=None,
        outcome="comparison_rejected",
        message=(
            "No selection was made because the comparison was rejected: "
            f"a valid positive distance is missing for {which}."
        ),
    )
    return ComparisonResult(
        od_pair_id=od_pair.route_id,
        panama=None,
        suez=None,
        excluded_options=(),
        exclusion_reasons={},
        selection=selection,
        comparison_error=comparison_error,
    )


def _closest_by_journey(
    results: Mapping[str, OptionResult], candidate_names: list[str]
) -> str | None:
    """Return the candidate with the minimum resolved journey time, else ``None``.

    Ties on journey time prefer Panama (the disclosed deterministic convention).
    ``None`` is returned when no candidate has a resolved journey time.
    """
    timed = [
        (name, _journey_float(results[name]))
        for name in candidate_names
    ]
    timed = [(name, jt) for name, jt in timed if jt is not None]
    if not timed:
        return None
    # Prefer the lower journey time; on a tie prefer panama via sort key.
    timed.sort(key=lambda item: (item[1], 0 if item[0] == "panama" else 1))
    return timed[0][0]


def _label(name: str) -> str:
    """Return the display label for an option name."""
    return name.capitalize()


def _describe_unresolved(unresolved: Mapping[str, tuple[str, ...]]) -> str:
    """Describe each option and the inputs that left it unresolved."""
    return "; ".join(
        f"{_label(name)} (needs {', '.join(inputs) or 'an unresolved input'})"
        for name, inputs in unresolved.items()
    )


def _pick_by_metric(
    priority: str, results: Mapping[str, OptionResult], scored: Mapping[str, float]
) -> tuple[str, str | None]:
    """Minimize the metric with tie handling: metric, journey time, Panama.

    Returns the selected option and the tie step that resolved it, if any
    (Requirements 11.4, 11.6, 11.7, 11.8).
    """
    tolerance = _METRIC_TOLERANCE.get(priority, 0.001)
    ordered = sorted(
        scored.items(), key=lambda item: (item[1], 0 if item[0] == "panama" else 1)
    )
    best_name, best_metric = ordered[0]
    tied = [name for name, value in ordered if abs(value - best_metric) <= tolerance]
    if len(tied) < 2:
        return best_name, None
    journey_times = {name: _journey_float(results[name]) for name in tied}
    resolvable = {name: jt for name, jt in journey_times.items() if jt is not None}
    if resolvable:
        min_jt = min(resolvable.values())
        leaders = [
            name for name, jt in resolvable.items()
            if abs(jt - min_jt) <= TIE_TOLERANCE_HOURS
        ]
    else:
        leaders = list(tied)
    if len(leaders) == 1:
        return leaders[0], (
            f"metric tie within {tolerance} resolved by lower journey time"
        )
    selected = "panama" if "panama" in leaders else sorted(leaders)[0]
    return selected, (
        "metric and journey time tied within tolerance; resolved by the "
        "Panama tie-break convention (a disclosed deterministic rule, not "
        "evidence Panama is superior)"
    )


def _build_selection(
    priority: str,
    results: Mapping[str, OptionResult],
    candidate_names: list[str],
    feasible_candidates: list[str],
    exclusion_reasons: Mapping[str, str] | None = None,
) -> Selection:
    """Resolve exactly one selection outcome (design "Deadline status and selection outcomes").

    ``candidate_names`` are the available options after exclusions. Only
    ``all_available_miss`` may say that no route meets the deadline, and its
    wording is scoped to the available routes (Requirements 3.1, 11.3-11.5).
    """
    reasons = dict(exclusion_reasons or {})
    common = {"priority": priority, "tie_resolution": None}

    if not candidate_names:
        detail = "; ".join(f"{_label(n)}: {r}" for n, r in reasons.items())
        return Selection(
            selected_option=None, no_feasible_option=False, closest_option=None,
            message=(
                "No route is available to compare, so no selection was made"
                + (f" ({detail})." if detail else ".")
            ),
            outcome="no_available_option", **common,
        )

    undetermined = {
        name: tuple(results[name].deadline_undetermined_inputs)
        for name in candidate_names
        if results[name].feasible is None
    }

    if feasible_candidates:
        metrics = {n: _metric_value(results[n], priority) for n in feasible_candidates}
        blocked = {
            name: tuple(m.missing_inputs) + tuple(m.invalid_inputs)
            for name, m in metrics.items()
            if isinstance(m, Unavailable)
        }
        if blocked:
            return Selection(
                selected_option=None, no_feasible_option=False, closest_option=None,
                message=(
                    f"No selection was made: the {priority} metric is unavailable "
                    f"for {_describe_unresolved(blocked)}."
                ),
                outcome="priority_metric_unavailable", unresolved_inputs=blocked,
                **common,
            )
        selected, tie_resolution = _pick_by_metric(
            priority, results, {n: float(m) for n, m in metrics.items()}
        )
        message = _selection_message(selected, priority, tie_resolution)
        if undetermined:
            message += (
                " Not compared because its deadline status is undetermined: "
                f"{_describe_unresolved(undetermined)}."
            )
        return Selection(
            selected_option=selected,  # type: ignore[arg-type]
            priority=priority, no_feasible_option=False, closest_option=None,
            tie_resolution=tie_resolution, message=message, outcome="selected",
            unresolved_inputs=undetermined,
        )

    if undetermined:
        misses = [n for n in candidate_names if results[n].feasible is False]
        message = (
            "No selection was made because the deadline status is undetermined "
            f"for {_describe_unresolved(undetermined)}."
        )
        for name in misses:
            message += f" {_label(name)} misses the deadline."
        return Selection(
            selected_option=None, no_feasible_option=False, closest_option=None,
            message=message, outcome="feasibility_undetermined",
            unresolved_inputs=undetermined, **common,
        )

    closest = _closest_by_journey(results, candidate_names)
    if len(candidate_names) > 1:
        message = "Neither route meets the deadline, so no selection was made."
        if closest is not None:
            message += f" The faster route is {_label(closest)}."
    else:
        only = candidate_names[0]
        message = (
            f"The only available route, {_label(only)}, misses the deadline, "
            "so no selection was made."
        )
        for name, reason in reasons.items():
            if name != only:
                message += f" {_label(name)} is excluded: {reason}."
    return Selection(
        selected_option=None, no_feasible_option=True,
        closest_option=closest,  # type: ignore[arg-type]
        message=message, outcome="all_available_miss", **common,
    )


def _selection_message(
    selected: str, priority: str, tie_resolution: str | None
) -> str:
    """Compose a plain-language selection message.

    When the Panama convention resolved a tie the message states explicitly that
    the convention is NOT evidence Panama is the superior route (Requirement
    11.8).
    """
    base = f"Selected {selected} as the option minimizing the {priority} metric."
    if tie_resolution is None:
        return base
    if "Panama tie-break convention" in tie_resolution:
        return (
            f"{base} The metric and journey time were tied within tolerance, so "
            "the result was resolved by the Panama tie-break convention. This "
            "convention is a disclosed deterministic rule and is NOT evidence "
            "that Panama is the superior route."
        )
    return f"{base} A metric tie was resolved by preferring the lower journey time."
