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
DRAFT_LOSS_DISCLOSURE = (
    "The draft-based cargo-loss adjustment rests on an analyst-estimate "
    "containers-lost-per-10cm figure and an assumption average-TEU-per-container "
    "factor; the reduced loaded TEU and the per-TEU figures derived from it are "
    "estimates, not observed values."
)

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

    Fuel-for-cost basis: ``voyage_fuel_cost_usd`` and ``co2_tank_to_wake_t`` are
    computed on the best-resolved fuel figure. When ``total_voyage_fuel_t`` is a
    true total (all components resolved) it is used; otherwise the
    sailing-only ``sailing_fuel_t`` is used as a partial estimate (per the
    Task 4.2 design note), and when even sailing fuel is unavailable the cost and
    CO2 are themselves ``Unavailable``. In the normal all-zero-duration scenario
    (waiting = 0, canal = 0) the waiting and canal line items resolve to ``0.0``,
    so the total equals the sailing fuel and the full total is used.
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
    waiting_component = _echo_duration(
        scenario.waiting_duration_h, "waiting_duration_h"
    )

    journey_time = journey_time_hours(
        sailing_time, scenario.canal_duration_h, scenario.waiting_duration_h
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
    waiting_fuel = waiting_fuel_t(
        scenario.waiting_duration_h, constants.waiting_fuel_t_per_day
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

    # Best-resolved fuel basis for cost and CO2: prefer the true total; fall
    # back to the sailing-only partial estimate; else Unavailable.
    if not isinstance(total_fuel, Unavailable):
        fuel_for_cost_basis: float | Unavailable = total_fuel
        fuel_basis_note = "total voyage fuel (all components resolved)"
    elif not isinstance(sailing_fuel, Unavailable):
        fuel_for_cost_basis = sailing_fuel
        fuel_basis_note = (
            "sailing-only partial estimate (waiting/canal fuel unresolved)"
        )
    else:
        fuel_for_cost_basis = Unavailable(
            reason="cost/CO2 basis requires voyage fuel, which is unavailable",
            missing_inputs=("total_voyage_fuel_t", "sailing_fuel_t"),
        )
        fuel_basis_note = "no resolvable fuel figure"

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

        draft_loss_disclosure = DRAFT_LOSS_DISCLOSURE
        if isinstance(draft_loss, DraftLoss):
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
            # invalid). Keep the base loaded TEU intact and disclose which
            # inputs were missing, rather than crashing or inventing a loss
            # (independent evaluation, Req 3.4).
            missing_bits = ", ".join(
                draft_loss.missing_inputs + draft_loss.invalid_inputs
            )
            draft_loss_disclosure = (
                DRAFT_LOSS_DISCLOSURE
                + " The adjustment could not be computed because of unresolved "
                + f"inputs ({missing_bits})."
                if missing_bits
                else DRAFT_LOSS_DISCLOSURE
                + " The adjustment could not be computed because of unresolved inputs."
            )

    # --- Cost and cost per TEU (independent) ---------------------------
    voyage_cost = voyage_fuel_cost_usd(
        fuel_for_cost_basis, scenario.bunker_price_usd_per_t
    )

    # --- CO2 (independent) ---------------------------------------------
    co2 = co2_tank_to_wake_t(fuel_for_cost_basis, emission_factor, scenario.fuel_type)

    # --- Feasibility / deadline status ---------------------------------
    if not isinstance(journey_time, Unavailable) and scenario.deadline_h is not None:
        feasible: bool | None = journey_time <= scenario.deadline_h
        deadline_status = "meets deadline" if feasible else "misses deadline"
    else:
        feasible = None
        deadline_status = "undetermined"

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

    # Record which fuel basis fed cost/CO2 in the units map notes.
    units: dict[str, str] = dict(_UNITS)
    units["fuel_for_cost_basis"] = fuel_basis_note

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
        draft_not_modeled_disclosure=DRAFT_NOT_MODELED_DISCLOSURE,
        exclusions=EXCLUSIONS,
        input_provenance=input_provenance,
        draft_loss_enabled=scenario.draft_loss_enabled,
        draft_shortfall_ft=draft_shortfall_ft,
        containers_lost=draft_containers_lost,
        teu_lost=draft_teu_lost,
        draft_loss_disclosure=draft_loss_disclosure,
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
        no_feasible_option=True,
        closest_option=None,
        tie_resolution=None,
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


def _build_selection(
    priority: str,
    results: Mapping[str, OptionResult],
    candidate_names: list[str],
    feasible_candidates: list[str],
) -> Selection:
    """Build the :class:`Selection` outcome for the comparison.

    Applies the deadline-miss rule (Requirement 11.5) when no non-excluded option
    is feasible, otherwise minimizes the chosen metric with deterministic tie
    handling (Requirements 11.4, 11.6, 11.7, 11.8).
    """
    # --- Deadline miss: no non-excluded Feasible_Option (Req 11.5) -----
    if not feasible_candidates:
        closest = _closest_by_journey(results, candidate_names)
        if closest is None:
            message = (
                "No option meets the deadline, and no journey time could be "
                "resolved for the available options, so no closest option could "
                "be identified."
            )
        else:
            message = (
                "Neither route meets the deadline, so no selection was made. "
                f"The closest option by journey time is {closest}."
            )
        return Selection(
            selected_option=None,
            priority=priority,
            no_feasible_option=True,
            closest_option=closest,
            tie_resolution=None,
            message=message,
        )

    # --- Selection candidates: feasible AND a resolved metric ----------
    scored: list[tuple[str, float]] = []
    for name in feasible_candidates:
        metric = _metric_value(results[name], priority)
        if not isinstance(metric, Unavailable):
            scored.append((name, float(metric)))

    if not scored:
        # Feasible options exist, but none has a resolved metric on this
        # priority, so no metric-based selection can be made.
        closest = _closest_by_journey(results, candidate_names)
        return Selection(
            selected_option=None,
            priority=priority,
            no_feasible_option=False,
            closest_option=closest,
            tie_resolution=None,
            message=(
                "A feasible option exists, but the selected priority metric "
                f"({priority}) is unavailable for every feasible option, so no "
                "selection could be made."
            ),
        )

    tolerance = _METRIC_TOLERANCE.get(priority, 0.001)

    # Best by metric (minimize). Panama-first ordering of scored makes the
    # initial pick deterministic before tie resolution is applied.
    scored.sort(
        key=lambda item: (item[1], 0 if item[0] == "panama" else 1)
    )
    best_name, best_metric = scored[0]

    # Identify metric ties with the best option (within the metric tolerance).
    tied = [
        name
        for name, value in scored
        if abs(value - best_metric) <= tolerance
    ]

    tie_resolution: str | None = None
    selected = best_name

    if len(tied) > 1:
        # Step 2: prefer the lower journey time among the tied options.
        journey_times = {
            name: _journey_float(results[name]) for name in tied
        }
        resolvable = {
            name: jt for name, jt in journey_times.items() if jt is not None
        }
        if resolvable:
            min_jt = min(resolvable.values())
            jt_leaders = [
                name
                for name, jt in resolvable.items()
                if abs(jt - min_jt) <= TIE_TOLERANCE_HOURS
            ]
        else:
            jt_leaders = list(tied)

        if len(jt_leaders) == 1:
            selected = jt_leaders[0]
            tie_resolution = (
                f"metric tie within {tolerance} resolved by lower journey time"
            )
        else:
            # Step 3: Panama convention (a disclosed deterministic CONVENTION,
            # NOT evidence Panama is superior).
            if "panama" in jt_leaders:
                selected = "panama"
            else:
                selected = sorted(jt_leaders)[0]
            tie_resolution = (
                "metric and journey time tied within tolerance; resolved by the "
                "Panama tie-break convention (a disclosed deterministic rule, "
                "not evidence Panama is superior)"
            )

    message = _selection_message(selected, priority, tie_resolution)

    return Selection(
        selected_option=selected,  # type: ignore[arg-type]
        priority=priority,
        no_feasible_option=False,
        closest_option=None,
        tie_resolution=tie_resolution,
        message=message,
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
