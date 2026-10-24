"""Comparison and selection property tests for the CanalCast Calculation_Core
(Task 8.4).

These exercise :func:`canalcast.comparison.compare_od_pair` and
:func:`canalcast.comparison.compute_option`, plus the module-private
``_build_selection`` helper for the engineered tie cases, over the REAL required
data loaded once via ``load_all(Path("data"))``.

Each property is a single Hypothesis test with at least 100 examples, tagged
with its feature/property label and the requirements it validates.

Properties covered:

* Property 6  — a feasible option is never passed over for an infeasible one
  (Requirements 11.4, 18.6).
* Property 7  — selection minimizes the chosen priority metric
  (Requirements 11.4, 11.6).
* Property 8  — tie handling is deterministic: per-metric tolerance then lower
  journey time then the Panama convention (Requirements 11.7, 11.8).
* Property 13 — independent evaluation: one disabled calculation never
  suppresses the others whose inputs are present (Requirement 3.4).
* Property 14 — optional-series absence does not block the comparison
  (Requirements 4.4, 4.5).
* Both-miss deadline case — faster route identified AND no selection made with a
  "neither meets the deadline" statement (Requirement 11.5).
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.canalcast.comparison import (
    TIE_TOLERANCE_HOURS,
    _build_selection,
    compare_od_pair,
    compute_option,
)
from src.canalcast.loader import load_all
from src.canalcast.models import (
    CanalState,
    Constants,
    EmissionFactor,
    ODPair,
    Scenario,
    Unavailable,
)
from src.canalcast.results import (
    FuelBreakdown,
    JourneyTimeBreakdown,
    OptionResult,
)

# --- Real required data, loaded once -------------------------------------
#
# The core takes already-loaded, typed records; we load the real required data
# a single time at import and reuse the immutable records across examples.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_LOAD = load_all(DATA_DIR)
_REQUIRED = _LOAD.required
_CONSTANTS: Constants = _REQUIRED.constants
_CANAL_STATE: CanalState = next(
    cs for cs in _REQUIRED.canal_states if cs.state == "normal_reference"
)
_HFO: EmissionFactor = next(
    ef for ef in _REQUIRED.emission_factors if ef.fuel_type == "HFO"
)
_OD_PAIRS = {od.route_id: od for od in _REQUIRED.od_pairs}

# OD pairs with BOTH distances present and positive (so the distance
# precondition always passes and the comparison actually proceeds).
_COMPARABLE_OD_IDS = [
    od.route_id
    for od in _REQUIRED.od_pairs
    if od.panama is not None
    and od.suez is not None
    and od.panama.distance_nm is not None
    and od.suez.distance_nm is not None
]

_PRIORITIES = ("fastest", "lowest_cost_per_teu", "lowest_co2")

# A long canal settings-wide profile keeps example generation snappy.
_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


def _make_scenario(
    *,
    od_pair_id: str,
    speed_kn: float,
    deadline_h: float | None,
    priority: str,
    suez_available: bool,
    canal_duration_h: float = 0.0,
    waiting_duration_h: float = 0.0,
    load_factor: float = 0.85,
    bunker_price_usd_per_t: float = 876.5,
    fuel_type: str = "HFO",
) -> Scenario:
    """Build a valid :class:`Scenario` over the real canal state.

    Defaults mirror the loaded constants so every metric resolves unless a test
    deliberately disables one input.
    """
    return Scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        load_factor=load_factor,
        bunker_price_usd_per_t=bunker_price_usd_per_t,
        canal_duration_h=canal_duration_h,
        waiting_duration_h=waiting_duration_h,
        deadline_h=deadline_h,
        suez_available=suez_available,
        selection_priority=priority,  # type: ignore[arg-type]
        fuel_type=fuel_type,
        canal_state=_CANAL_STATE,
    )


def _metric_for(result: OptionResult, priority: str) -> float | Unavailable:
    """Read the selection metric from a computed :class:`OptionResult`."""
    if priority == "fastest":
        return result.journey.journey_time_h
    if priority == "lowest_cost_per_teu":
        return result.fuel_cost_per_teu_usd
    return result.co2_tank_to_wake_t


# ---------------------------------------------------------------------------
# Property 6: a feasible option is never passed over for an infeasible one.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 6: a feasible option is never passed over for an
# infeasible one.
@_SETTINGS
@given(
    od_pair_id=st.sampled_from(_COMPARABLE_OD_IDS),
    speed_kn=st.floats(
        min_value=8.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    priority=st.sampled_from(_PRIORITIES),
    suez_available=st.booleans(),
    # deadline_frac sometimes lands between the two journey times so that
    # exactly one option is feasible; sometimes above both so that both are.
    deadline_frac=st.floats(
        min_value=0.0, max_value=1.3, allow_nan=False, allow_infinity=False
    ),
)
def test_property_6_feasible_never_passed_over(
    od_pair_id, speed_kn, priority, suez_available, deadline_frac
):
    """Validates: Requirements 11.4, 18.6.

    Over generated scenarios, the selected option (when one is made) is always a
    Feasible_Option, and no option that misses the deadline is ever selected.
    """
    od_pair: ODPair = _OD_PAIRS[od_pair_id]

    # First compute both options with NO deadline to learn their journey times,
    # then place the deadline relative to them so one/both are feasible.
    probe_scn = _make_scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        deadline_h=None,
        priority=priority,
        suez_available=suez_available,
    )
    probe = compare_od_pair(od_pair, probe_scn, _CONSTANTS, _HFO, _CANAL_STATE)
    journey_times = []
    for opt in (probe.panama, probe.suez):
        if opt is not None and not isinstance(opt.journey.journey_time_h, Unavailable):
            journey_times.append(float(opt.journey.journey_time_h))
    assert journey_times, "both journey times should resolve for real data"

    lo, hi = min(journey_times), max(journey_times)
    # Interpolate a deadline within/around [lo, hi]; frac up to 1.3 exceeds hi.
    deadline_h = lo + deadline_frac * (hi - lo) if hi > lo else lo * deadline_frac

    scn = _make_scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        deadline_h=deadline_h,
        priority=priority,
        suez_available=suez_available,
    )
    result = compare_od_pair(od_pair, scn, _CONSTANTS, _HFO, _CANAL_STATE)
    selection = result.selection
    results_by_name = {"panama": result.panama, "suez": result.suez}

    if selection.selected_option is not None:
        chosen = results_by_name[selection.selected_option]
        assert chosen is not None
        # The selected option must itself be feasible (meets the deadline).
        assert chosen.feasible is True
        assert chosen.deadline_status == "meets deadline"
        # And it must not have been excluded.
        assert selection.selected_option not in result.excluded_options

    # No option that misses the deadline may ever be the selection.
    for name, opt in results_by_name.items():
        if opt is not None and opt.feasible is False:
            assert selection.selected_option != name


# ---------------------------------------------------------------------------
# Property 7: selection minimizes the chosen priority metric.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 7: selection minimizes the chosen priority
# metric.
@_SETTINGS
@given(
    od_pair_id=st.sampled_from(_COMPARABLE_OD_IDS),
    speed_kn=st.floats(
        min_value=8.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    priority=st.sampled_from(_PRIORITIES),
    suez_available=st.booleans(),
    load_factor=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_7_selection_minimizes_metric(
    od_pair_id, speed_kn, priority, suez_available, load_factor
):
    """Validates: Requirements 11.4, 11.6.

    When a selection is made, the selected option's priority metric is less than
    or equal to every other non-excluded feasible option's metric, within the
    per-metric tie tolerance of 0.001.
    """
    od_pair: ODPair = _OD_PAIRS[od_pair_id]
    # Generous deadline so both options are feasible (no deadline filtering),
    # isolating the metric-minimization behaviour.
    scn = _make_scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        deadline_h=1_000_000.0,
        priority=priority,
        suez_available=suez_available,
        load_factor=load_factor,
    )
    result = compare_od_pair(od_pair, scn, _CONSTANTS, _HFO, _CANAL_STATE)
    selection = result.selection

    if selection.selected_option is None:
        return  # nothing selected (e.g. metric unavailable) — nothing to assert

    results_by_name = {"panama": result.panama, "suez": result.suez}
    chosen = results_by_name[selection.selected_option]
    chosen_metric = _metric_for(chosen, priority)
    assert not isinstance(chosen_metric, Unavailable)
    chosen_value = float(chosen_metric)

    for name, opt in results_by_name.items():
        if name == selection.selected_option or opt is None:
            continue
        if name in result.excluded_options:
            continue
        if opt.feasible is not True:
            continue
        other_metric = _metric_for(opt, priority)
        if isinstance(other_metric, Unavailable):
            continue
        # Selected metric must not exceed any competing feasible option's metric
        # beyond the documented tolerance.
        assert chosen_value <= float(other_metric) + 0.001


# ---------------------------------------------------------------------------
# Property 8: tie handling is deterministic.
# ---------------------------------------------------------------------------
# Engineered OptionResults let us place metrics within 0.001 on purpose; real
# routes virtually never tie. We drive the pure ``_build_selection`` helper.


def _option(
    name,
    *,
    journey_h,
    cost_per_teu,
    co2_t,
    feasible=True,
):
    """Build a minimal feasible :class:`OptionResult` with controlled metrics.

    Only the fields the selection helper reads (journey time, cost/TEU, CO2,
    feasibility) carry meaningful values; the rest are valid placeholders.
    """
    journey = JourneyTimeBreakdown(
        sailing_time_h=journey_h,
        canal_duration_h=0.0,
        waiting_duration_h=0.0,
        journey_time_h=journey_h,
    )
    fuel = FuelBreakdown(
        fuel_rate_t_per_day=0.0,
        sailing_fuel_t=0.0,
        waiting_fuel_t=0.0,
        canal_fuel_t=0.0,
        total_voyage_fuel_t=0.0,
    )
    return OptionResult(
        option=name,
        route_id="engineered",
        units={},
        journey=journey,
        fuel=fuel,
        loaded_teu=1000.0,
        voyage_fuel_cost_usd=cost_per_teu * 1000.0,
        fuel_cost_per_teu_usd=cost_per_teu,
        co2_tank_to_wake_t=co2_t,
        feasible=feasible,
        deadline_status="meets deadline" if feasible else "misses deadline",
        infeasible=False,
        infeasible_reason=None,
        draft_context_ft=_CANAL_STATE.max_draft_ft,
        draft_not_modeled_disclosure="",
        exclusions=(),
    )


# Feature: canalcast, Property 8: tie handling is deterministic (per-metric
# tolerance, lower journey time, then the Panama convention).
@_SETTINGS
@given(
    priority=st.sampled_from(_PRIORITIES),
    # A metric difference strictly inside the 0.001 tolerance => a tie.
    metric_delta=st.floats(
        min_value=0.0, max_value=0.0009, allow_nan=False, allow_infinity=False
    ),
    base_metric=st.floats(
        min_value=1.0, max_value=5_000.0, allow_nan=False, allow_infinity=False
    ),
    base_journey=st.floats(
        min_value=100.0, max_value=5_000.0, allow_nan=False, allow_infinity=False
    ),
    # A clearly-resolving journey gap (well above the 0.001h journey tolerance).
    journey_gap=st.floats(
        min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    suez_faster=st.booleans(),
)
def test_property_8_tie_handling_deterministic(
    priority, metric_delta, base_metric, base_journey, journey_gap, suez_faster
):
    """Validates: Requirements 11.7, 11.8.

    Two feasible options tied within 0.001 on the priority metric:

    * when their journey times differ, the lower-journey-time option wins and a
      tie resolution is recorded;
    * when their journey times are also tied within 0.001h, Panama wins by the
      disclosed convention and a tie resolution is recorded.
    """

    def metrics_for(metric_value):
        """Return the (cost_per_teu, co2_t) pair placing the priority metric at
        ``metric_value`` while keeping the OTHER two metrics clearly distinct so
        only the active priority can produce a tie."""
        if priority == "fastest":
            return 10.0, 50.0  # journey carries the metric; others fixed
        if priority == "lowest_cost_per_teu":
            return metric_value, 50.0
        return 10.0, metric_value  # lowest_co2

    # --- Case A: metric tied within tolerance, journey times differ --------
    if priority == "fastest":
        # For "fastest" the metric IS the journey time, so a within-tolerance
        # metric tie is by construction also a journey tie -> Panama convention.
        panama = _option("panama", journey_h=base_journey, cost_per_teu=10.0, co2_t=50.0)
        suez = _option(
            "suez",
            journey_h=base_journey + metric_delta,
            cost_per_teu=10.0,
            co2_t=50.0,
        )
        selection = _build_selection(
            priority=priority,
            results={"panama": panama, "suez": suez},
            candidate_names=["panama", "suez"],
            feasible_candidates=["panama", "suez"],
        )
        assert selection.selected_option == "panama"
        assert selection.tie_resolution is not None
        return

    # Non-journey priorities: construct a genuine journey-time difference.
    p_cost, p_co2 = metrics_for(base_metric)
    s_cost, s_co2 = metrics_for(base_metric + metric_delta)

    if suez_faster:
        panama_journey = base_journey + journey_gap
        suez_journey = base_journey
        expected_faster = "suez"
    else:
        panama_journey = base_journey
        suez_journey = base_journey + journey_gap
        expected_faster = "panama"

    panama = _option(
        "panama", journey_h=panama_journey, cost_per_teu=p_cost, co2_t=p_co2
    )
    suez = _option("suez", journey_h=suez_journey, cost_per_teu=s_cost, co2_t=s_co2)

    selection = _build_selection(
        priority=priority,
        results={"panama": panama, "suez": suez},
        candidate_names=["panama", "suez"],
        feasible_candidates=["panama", "suez"],
    )
    # Metric tie resolved by the lower journey time.
    assert selection.selected_option == expected_faster
    assert selection.tie_resolution is not None

    # --- Case B: metric AND journey tied within tolerance -> Panama --------
    panama_b = _option("panama", journey_h=base_journey, cost_per_teu=p_cost, co2_t=p_co2)
    suez_b = _option(
        "suez",
        journey_h=base_journey + (TIE_TOLERANCE_HOURS / 2.0),
        cost_per_teu=s_cost,
        co2_t=s_co2,
    )
    selection_b = _build_selection(
        priority=priority,
        results={"panama": panama_b, "suez": suez_b},
        candidate_names=["panama", "suez"],
        feasible_candidates=["panama", "suez"],
    )
    assert selection_b.selected_option == "panama"
    assert selection_b.tie_resolution is not None
    assert "Panama" in selection_b.tie_resolution


# ---------------------------------------------------------------------------
# Property 13: independent evaluation of calculations.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 13: independent evaluation of calculations.
@_SETTINGS
@given(
    od_pair_id=st.sampled_from(_COMPARABLE_OD_IDS),
    option_name=st.sampled_from(("panama", "suez")),
    speed_kn=st.floats(
        min_value=8.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    load_factor=st.floats(
        min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_13_independent_evaluation(
    od_pair_id, option_name, speed_kn, load_factor
):
    """Validates: Requirements 3.4.

    Disabling ONE calculation (cost, via a missing bunker price) never suppresses
    the independent calculations whose inputs are all present: journey time,
    CO2, and loaded TEU still compute, while cost and cost/TEU are Unavailable.
    """
    od_pair: ODPair = _OD_PAIRS[od_pair_id]
    route_opt = od_pair.panama if option_name == "panama" else od_pair.suez
    assert route_opt is not None

    # bunker_price_usd_per_t=None disables ONLY cost and cost/TEU.
    scn = _make_scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        deadline_h=1_000_000.0,
        priority="fastest",
        suez_available=True,
        load_factor=load_factor,
        bunker_price_usd_per_t=None,
    )
    result = compute_option(route_opt, scn, _CONSTANTS, _HFO)

    # Independent calculations still resolve to numeric floats.
    assert isinstance(result.journey.journey_time_h, float)
    assert isinstance(result.co2_tank_to_wake_t, float)
    assert isinstance(result.loaded_teu, float)

    # The cost calculations are cleanly disabled, not substituted.
    assert isinstance(result.voyage_fuel_cost_usd, Unavailable)
    assert isinstance(result.fuel_cost_per_teu_usd, Unavailable)
    assert "bunker_price_usd_per_t" in result.voyage_fuel_cost_usd.missing_inputs


# ---------------------------------------------------------------------------
# Property 14: optional-series absence does not block the comparison.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 14: optional-series absence does not block the
# comparison.
@_SETTINGS
@given(
    od_pair_id=st.sampled_from(_COMPARABLE_OD_IDS),
    speed_kn=st.floats(
        min_value=8.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    priority=st.sampled_from(_PRIORITIES),
    suez_available=st.booleans(),
)
def test_property_14_optional_absence_does_not_block(
    od_pair_id, speed_kn, priority, suez_available
):
    """Validates: Requirements 4.4, 4.5.

    The core comparison receives ONLY required data (OD pair, scenario,
    constants, emission factor, canal state) — never an optional series — yet it
    still produces a complete ComparisonResult with per-option results and a
    Selection. This demonstrates that optional-series absence cannot block the
    comparison.
    """
    od_pair: ODPair = _OD_PAIRS[od_pair_id]
    scn = _make_scenario(
        od_pair_id=od_pair_id,
        speed_kn=speed_kn,
        deadline_h=1_000_000.0,
        priority=priority,
        suez_available=suez_available,
    )
    result = compare_od_pair(od_pair, scn, _CONSTANTS, _HFO, _CANAL_STATE)

    # A complete comparison was produced without any optional series.
    assert result.comparison_error is None
    assert isinstance(result.panama, OptionResult)
    assert isinstance(result.suez, OptionResult)
    assert result.selection is not None
    # Both core journey times resolve for real required data.
    assert isinstance(result.panama.journey.journey_time_h, float)
    assert isinstance(result.suez.journey.journey_time_h, float)
    # And the five required metrics are present on each option (numeric or an
    # explicit Unavailable, never silently dropped).
    for opt in (result.panama, result.suez):
        assert isinstance(
            opt.journey.journey_time_h, (float, Unavailable)
        )
        assert isinstance(opt.voyage_fuel_cost_usd, (float, Unavailable))
        assert isinstance(opt.fuel_cost_per_teu_usd, (float, Unavailable))
        assert isinstance(opt.co2_tank_to_wake_t, (float, Unavailable))
        assert isinstance(opt.loaded_teu, (float, Unavailable))


# ---------------------------------------------------------------------------
# Both-miss deadline case (Requirement 11.5).
# ---------------------------------------------------------------------------
def test_both_miss_deadline_identifies_faster_route_and_makes_no_selection():
    """Validates: Requirements 11.5.

    With a deadline too small for either route, no selection is made,
    ``no_feasible_option`` is True, and the closest option is the faster route by
    minimum journey time, with a plain-language "no option meets the deadline"
    statement.
    """
    od_pair: ODPair = _OD_PAIRS["singapore_new_york"]

    speed_kn = 18.0
    canal_duration_h = 12.0
    waiting_duration_h = 0.0

    # Learn the two journey times first (no deadline), then pick a deadline below
    # both so neither is feasible.
    probe_scn = _make_scenario(
        od_pair_id="singapore_new_york",
        speed_kn=speed_kn,
        deadline_h=None,
        priority="fastest",
        suez_available=True,
        canal_duration_h=canal_duration_h,
        waiting_duration_h=waiting_duration_h,
    )
    probe = compare_od_pair(od_pair, probe_scn, _CONSTANTS, _HFO, _CANAL_STATE)
    panama_jt = float(probe.panama.journey.journey_time_h)
    suez_jt = float(probe.suez.journey.journey_time_h)
    assert panama_jt != suez_jt  # real route distances differ

    tiny_deadline = min(panama_jt, suez_jt) - 1.0
    scn = _make_scenario(
        od_pair_id="singapore_new_york",
        speed_kn=speed_kn,
        deadline_h=tiny_deadline,
        priority="fastest",
        suez_available=True,
        canal_duration_h=canal_duration_h,
        waiting_duration_h=waiting_duration_h,
    )
    result = compare_od_pair(od_pair, scn, _CONSTANTS, _HFO, _CANAL_STATE)
    selection = result.selection

    assert selection.no_feasible_option is True
    assert selection.selected_option is None

    expected_closest = "suez" if suez_jt < panama_jt else "panama"
    assert selection.closest_option == expected_closest

    message = selection.message.lower()
    assert "deadline" in message
    assert "no selection" in message or "no option" in message or "neither" in message
