"""Tests for the optional draft-based cargo-loss adjustment (Requirement 20).

The draft-loss feature is a version-2 adjustment that is DISABLED by default.
When off, it preserves exact v1 behavior: canal-state draft remains pure context
and never reduces TEU, cost, fuel, or CO2 (Requirement 20.1). When on, it is a
Panama-only effect that reduces loaded TEU (and the per-TEU figures derived from
it) while leaving journey time and CO2 untouched (Requirement 20.10).

These exercise the pure :func:`canalcast.calculations.draft_cargo_loss` and its
integration through :func:`canalcast.comparison.compute_option`, over the REAL
required data loaded once via ``load_all(Path("data"))``.

Tests:

* Default-off regression — the feature is truly opt-in (Requirement 20.1).
* Worked example — exact loss figures and a higher per-TEU cost when on
  (Requirements 20.2-20.6).
* Property 16 — enabling draft loss never changes CO2 or journey time
  (Requirement 20.10).
* Property 17 — no draft loss when draft meets/exceeds reference
  (Requirement 20.3).
* Property 18 — Suez is never draft-reduced (Requirement 20.7).
* Zero/infeasible clamp — loaded TEU never goes negative; a huge estimate
  clamps it to zero and makes the option infeasible with an undefined per-TEU
  cost (Requirements 20.8, 11.9).
"""

from __future__ import annotations

import math
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from src.canalcast.calculations import draft_cargo_loss
from src.canalcast.comparison import compute_option
from src.canalcast.loader import load_all
from src.canalcast.models import (
    CanalState,
    Constants,
    DraftLoss,
    EmissionFactor,
    ODPair,
    RouteOption,
    Scenario,
    Unavailable,
)

# --- Real required data, loaded once -------------------------------------
#
# The core takes already-loaded, typed records; we load the real required data a
# single time at import and reuse the immutable records across examples.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_LOAD = load_all(DATA_DIR)
_REQUIRED = _LOAD.required
_CONSTANTS: Constants = _REQUIRED.constants
_HFO: EmissionFactor = next(
    ef for ef in _REQUIRED.emission_factors if ef.fuel_type == "HFO"
)
_OD_PAIRS = {od.route_id: od for od in _REQUIRED.od_pairs}

# Canal states keyed by name: the 50.0 ft design-draft reference and the 49.0 ft
# current (Oct 2026) restricted state give a clean 1.0 ft shortfall.
_CANAL_STATES = {cs.state: cs for cs in _REQUIRED.canal_states}
_NORMAL_REFERENCE: CanalState = _CANAL_STATES["normal_reference"]  # 50.0 ft
_CURRENT_OCT2026: CanalState = _CANAL_STATES["current_oct2026"]  # 49.0 ft

# The shanghai_boston OD pair carries both a Panama and a Suez option.
_OD: ODPair = _OD_PAIRS["shanghai_boston"]
_PANAMA_ROUTE: RouteOption = _OD.panama
_SUEZ_ROUTE: RouteOption = _OD.suez

_SETTINGS = settings(max_examples=100, deadline=None)


def _make_scenario(
    *,
    canal_state: CanalState,
    draft_loss_enabled: bool = False,
    containers_lost_per_10cm: float | None = None,
    avg_teu_per_container: float = 1.7,
    speed_kn: float = 18.0,
    load_factor: float = 0.85,
) -> Scenario:
    """Build a valid :class:`Scenario` over a real canal state.

    Mirrors the pattern used in ``tests/test_comparison.py``: every required
    numeric input resolves from the loaded constants so the base metrics all
    compute, isolating the draft-loss behavior under test. Zero canal/waiting
    durations keep total voyage fuel equal to sailing fuel.
    """
    return Scenario(
        od_pair_id=_OD.route_id,
        speed_kn=speed_kn,
        load_factor=load_factor,
        bunker_price_usd_per_t=876.5,
        canal_duration_h=0.0,
        waiting_duration_h=0.0,
        deadline_h=None,
        suez_available=True,
        selection_priority="lowest_cost_per_teu",
        fuel_type="HFO",
        canal_state=canal_state,
        draft_loss_enabled=draft_loss_enabled,
        containers_lost_per_10cm=containers_lost_per_10cm,
        avg_teu_per_container=avg_teu_per_container,
    )


# ---------------------------------------------------------------------------
# 1. Default-off regression (Requirement 20.1).
# ---------------------------------------------------------------------------
def test_default_off_preserves_v1_behavior():
    """Validates: Requirement 20.1.

    Under the restricted 49.0 ft canal state, a Panama option computed with
    ``draft_loss_enabled=False`` keeps the full base loaded TEU (8500.0), yields
    the SAME fuel cost per TEU and CO2 as a reference run with the feature off,
    and leaves every draft-loss field (shortfall, containers lost, TEU lost)
    ``None`` — proving the adjustment is truly opt-in.
    """
    scenario = _make_scenario(canal_state=_CURRENT_OCT2026, draft_loss_enabled=False)
    reference = _make_scenario(canal_state=_CURRENT_OCT2026, draft_loss_enabled=False)

    result = compute_option(_PANAMA_ROUTE, scenario, _CONSTANTS, _HFO)
    ref = compute_option(_PANAMA_ROUTE, reference, _CONSTANTS, _HFO)

    # Full base loaded TEU, undiminished by the 49.0 ft draft.
    assert result.loaded_teu == 8500.0

    # Cost per TEU and CO2 match the reference run exactly (feature is inert).
    assert not isinstance(result.fuel_cost_per_teu_usd, Unavailable)
    assert not isinstance(ref.fuel_cost_per_teu_usd, Unavailable)
    assert result.fuel_cost_per_teu_usd == ref.fuel_cost_per_teu_usd
    assert not isinstance(result.co2_tank_to_wake_t, Unavailable)
    assert result.co2_tank_to_wake_t == ref.co2_tank_to_wake_t

    # No draft-loss fields are populated when the feature is off.
    assert result.draft_loss_enabled is False
    assert result.draft_shortfall_ft is None
    assert result.containers_lost is None
    assert result.teu_lost is None


# ---------------------------------------------------------------------------
# 2. Worked example within 1e-9 (Requirements 20.2-20.6).
# ---------------------------------------------------------------------------
def test_worked_example_exact_loss_and_higher_cost_per_teu():
    """Validates: Requirements 20.2, 20.3, 20.4, 20.5, 20.6.

    A 1.0 ft shortfall (50.0 ft reference minus 49.0 ft available) at 100
    containers lost per 10 cm and 1.7 TEU per container gives exactly:

    * ``shortfall_ft`` = 1.0
    * ``containers_lost`` = 1.0 ft x 30.48 cm/ft / 10 cm x 100 = 304.8
    * ``teu_lost`` = 304.8 x 1.7 = 518.16

    Through ``compute_option`` the loaded TEU falls to 8500 - 518.16 = 7981.84,
    and the fuel cost per TEU rises above the feature-off run (same fuel cost
    spread over fewer TEU).
    """
    expected_shortfall = 1.0
    expected_containers = 1.0 * 30.48 / 10.0 * 100.0  # 304.8
    expected_teu_lost = expected_containers * 1.7  # 518.16

    loss = draft_cargo_loss("panama", 49.0, 50.0, 100.0, 1.7, enabled=True)
    assert isinstance(loss, DraftLoss)
    assert math.isclose(loss.shortfall_ft, expected_shortfall, rel_tol=1e-9)
    assert math.isclose(loss.containers_lost, expected_containers, rel_tol=1e-9)
    assert math.isclose(loss.teu_lost, expected_teu_lost, rel_tol=1e-9)
    # Pin the concrete literals as well.
    assert math.isclose(loss.containers_lost, 304.8, rel_tol=1e-9)
    assert math.isclose(loss.teu_lost, 518.16, rel_tol=1e-9)

    # Integrated through compute_option on the restricted state.
    on = _make_scenario(
        canal_state=_CURRENT_OCT2026,
        draft_loss_enabled=True,
        containers_lost_per_10cm=100.0,
        avg_teu_per_container=1.7,
    )
    off = _make_scenario(canal_state=_CURRENT_OCT2026, draft_loss_enabled=False)

    result_on = compute_option(_PANAMA_ROUTE, on, _CONSTANTS, _HFO)
    result_off = compute_option(_PANAMA_ROUTE, off, _CONSTANTS, _HFO)

    assert not isinstance(result_on.loaded_teu, Unavailable)
    assert math.isclose(result_on.loaded_teu, 8500.0 - 518.16, rel_tol=1e-9)
    assert math.isclose(result_on.loaded_teu, 7981.84, rel_tol=1e-9)

    # Fewer loaded TEU over the same fuel cost => a strictly higher cost per TEU.
    cost_on = result_on.fuel_cost_per_teu_usd
    cost_off = result_off.fuel_cost_per_teu_usd
    assert not isinstance(cost_on, Unavailable)
    assert not isinstance(cost_off, Unavailable)
    assert cost_on > cost_off


# ---------------------------------------------------------------------------
# 3. Property 16 — enabling draft loss never changes CO2 or journey time.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 16: enabling draft loss never changes CO2 tonnes
# or journey time
@_SETTINGS
@given(
    speed_kn=st.floats(
        min_value=8.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    estimate=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    avg_teu=st.floats(
        min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
    state_name=st.sampled_from(["normal_reference", "current_oct2026"]),
)
def test_property_16_draft_loss_preserves_co2_and_journey_time(
    speed_kn, estimate, avg_teu, state_name
):
    """Validates: Requirement 20.10.

    Draft loss touches only loaded TEU and the per-TEU figures derived from it;
    it never changes the fuel burn, so the tank-to-wake CO2 and the journey time
    are identical whether the adjustment is off or on, for the Panama option.
    """
    canal_state = _CANAL_STATES[state_name]
    off = _make_scenario(
        canal_state=canal_state, draft_loss_enabled=False, speed_kn=speed_kn
    )
    on = _make_scenario(
        canal_state=canal_state,
        draft_loss_enabled=True,
        containers_lost_per_10cm=estimate,
        avg_teu_per_container=avg_teu,
        speed_kn=speed_kn,
    )

    result_off = compute_option(_PANAMA_ROUTE, off, _CONSTANTS, _HFO)
    result_on = compute_option(_PANAMA_ROUTE, on, _CONSTANTS, _HFO)

    # CO2 is unchanged (both resolve for real data at any speed in range).
    co2_off = result_off.co2_tank_to_wake_t
    co2_on = result_on.co2_tank_to_wake_t
    assert not isinstance(co2_off, Unavailable)
    assert not isinstance(co2_on, Unavailable)
    assert math.isclose(co2_on, co2_off, rel_tol=1e-12, abs_tol=0.0)

    # Journey time is unchanged.
    jt_off = result_off.journey.journey_time_h
    jt_on = result_on.journey.journey_time_h
    assert not isinstance(jt_off, Unavailable)
    assert not isinstance(jt_on, Unavailable)
    assert math.isclose(jt_on, jt_off, rel_tol=1e-12, abs_tol=0.0)


# ---------------------------------------------------------------------------
# 4. Property 17 — no draft loss when draft >= reference.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 17: no draft loss when draft >= reference
@_SETTINGS
@given(
    draft=st.floats(
        min_value=50.0, max_value=60.0, allow_nan=False, allow_infinity=False
    ),
    estimate=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    avg_teu=st.floats(
        min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_17_no_loss_when_draft_meets_or_exceeds_reference(
    draft, estimate, avg_teu
):
    """Validates: Requirement 20.3.

    When the available canal draft meets or exceeds the reference draft there is
    no shortfall, so the Panama draft loss clamps to ``DraftLoss(0, 0, 0)`` for
    any containers-lost estimate and average-TEU factor.
    """
    loss = draft_cargo_loss("panama", draft, 50.0, estimate, avg_teu, enabled=True)
    assert loss == DraftLoss(0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 5. Property 18 — Suez is never draft-reduced.
# ---------------------------------------------------------------------------
# Feature: canalcast, Property 18: Suez is never draft-reduced
@_SETTINGS
@given(
    draft=st.floats(
        min_value=20.0, max_value=60.0, allow_nan=False, allow_infinity=False
    ),
    reference=st.floats(
        min_value=20.0, max_value=60.0, allow_nan=False, allow_infinity=False
    ),
    estimate=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    avg_teu=st.floats(
        min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_18_suez_is_never_draft_reduced(draft, reference, estimate, avg_teu):
    """Validates: Requirement 20.7.

    The draft-based cargo loss is a Panama-only effect. The Suez option is never
    reduced on the basis of the Panama Canal draft, so the loss is always
    ``DraftLoss(0, 0, 0)`` regardless of draft, reference, estimate, or factor.
    """
    loss = draft_cargo_loss("suez", draft, reference, estimate, avg_teu, enabled=True)
    assert loss == DraftLoss(0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 6. TEU never negative / infeasible clamp (Requirements 20.8, 11.9).
# ---------------------------------------------------------------------------
def test_huge_estimate_clamps_loaded_teu_to_zero_and_marks_infeasible():
    """Validates: Requirements 20.8, 11.9.

    A containers-lost estimate large enough that the TEU lost exceeds the base
    loaded TEU never drives the loaded TEU negative: it clamps at exactly 0.0.
    With zero payload the option is infeasible and the fuel cost per TEU is an
    ``Unavailable`` whose reason names the zero loaded TEU (reusing the
    Requirement 11.9 contract).
    """
    # Base loaded TEU is 8500; a 1.0 ft shortfall gives 3.048 ten-cm units, so
    # an estimate of 100000 containers/10cm with 1.7 TEU each far exceeds 8500.
    scenario = _make_scenario(
        canal_state=_CURRENT_OCT2026,
        draft_loss_enabled=True,
        containers_lost_per_10cm=100000.0,
        avg_teu_per_container=1.7,
    )
    result = compute_option(_PANAMA_ROUTE, scenario, _CONSTANTS, _HFO)

    # Clamped to zero, never negative.
    assert result.loaded_teu == 0.0

    # Zero payload => infeasible with an undefined per-TEU cost.
    assert result.infeasible is True
    cost_per_teu = result.fuel_cost_per_teu_usd
    assert isinstance(cost_per_teu, Unavailable)
    assert "loaded TEU is zero" in cost_per_teu.reason
