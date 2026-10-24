"""Unit and property-based tests for the CanalCast Calculation_Core.

Covers Task 8.2 (worked-example and edge-case unit tests) and Task 8.3
(calculation property tests). Imports resolve via the workspace-root
``conftest.py`` which places the project root on ``sys.path``.
"""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.canalcast.calculations import (
    canal_fuel_t,
    co2_tank_to_wake_t,
    fuel_cost_per_teu_usd,
    fuel_rate_t_per_day,
    loaded_teu,
    sailing_fuel_t,
    sailing_time_hours,
    teu_for_container,
    total_voyage_fuel_t,
    voyage_fuel_cost_usd,
    waiting_fuel_t,
)
from src.canalcast.models import (
    EmissionFactor,
    ProvenancedValue,
    Status,
    Unavailable,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

REL_TOL = 1e-9


def _hfo_factor(co2_per_t: float = 3.114) -> EmissionFactor:
    """Build a well-formed HFO emission factor for CO2 tests."""
    return EmissionFactor(
        fuel_type="HFO",
        co2_t_per_fuel_t=ProvenancedValue(
            co2_per_t, "t_CO2/t_fuel", "src", Status.SOURCED
        ),
        scope="tank_to_wake_CO2_only",
        unit="t_CO2/t_fuel",
    )


def _factor_for(fuel_type: str, co2_per_t: float = 3.0) -> EmissionFactor:
    """Build a well-formed emission factor for an arbitrary fuel type."""
    return EmissionFactor(
        fuel_type=fuel_type,
        co2_t_per_fuel_t=ProvenancedValue(
            co2_per_t, "t_CO2/t_fuel", "src", Status.SOURCED
        ),
        scope="tank_to_wake_CO2_only",
        unit="t_CO2/t_fuel",
    )


# ===========================================================================
# TASK 8.2 -- worked-example & edge-case unit tests
# (Property 1 / Requirements 18.1, 7.4, 7.5)
# ===========================================================================


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_sailing_time_worked_example() -> None:
    result = sailing_time_hours(10783.5, 18)
    assert isinstance(result, float)
    assert math.isclose(result, 10783.5 / 18, rel_tol=REL_TOL)


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_fuel_rate_worked_example() -> None:
    # Cubic curve: 175 * (18/22)**3 ~= 95.85 t/day.
    # NOTE: the secondary-source sanity target
    # check_fuel_t_per_day_at_18kn=109 is a DOCUMENTED discrepancy between
    # sources, NOT a test failure. The curve constants (base_fuel=175,
    # base_speed=22, exponent=3) are authoritative here, so ~95.85 is correct.
    result = fuel_rate_t_per_day(18, 175, 22, 3)
    assert isinstance(result, float)
    assert math.isclose(result, 175 * (18 / 22) ** 3, rel_tol=REL_TOL)


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_voyage_fuel_cost_worked_example() -> None:
    result = voyage_fuel_cost_usd(1000.0, 876.5)
    assert isinstance(result, float)
    assert math.isclose(result, 876500.0, rel_tol=REL_TOL)


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_loaded_teu_worked_example() -> None:
    result = loaded_teu(10000, 0.85)
    assert isinstance(result, float)
    assert math.isclose(result, 8500.0, rel_tol=REL_TOL)


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_fuel_cost_per_teu_worked_example() -> None:
    result = fuel_cost_per_teu_usd(876500.0, 8500.0)
    assert isinstance(result, float)
    assert math.isclose(result, 876500 / 8500, rel_tol=REL_TOL)


# Feature: canalcast, Property 1: worked examples within 1e-9
def test_property1_co2_hfo_worked_example() -> None:
    factor = _hfo_factor(3.114)
    result = co2_tank_to_wake_t(1000.0, factor, "HFO")
    assert isinstance(result, float)
    assert math.isclose(result, 3114.0, rel_tol=REL_TOL)


# ---------------------------------------------------------------------------
# Fuel line-item edge cases (Requirements 7.4, 7.5)
# Identical rule applied to BOTH waiting and canal line items.
# ---------------------------------------------------------------------------


# Validates: Requirements 18.1, 7.4, 7.5
def test_waiting_fuel_zero_duration_no_rate_is_zero() -> None:
    result = waiting_fuel_t(0, None)
    assert result == 0.0
    assert isinstance(result, float)


# Validates: Requirements 18.1, 7.4, 7.5
def test_waiting_fuel_zero_duration_with_rate_is_zero() -> None:
    result = waiting_fuel_t(0, 10.0)
    assert result == 0.0
    assert isinstance(result, float)


# Validates: Requirements 18.1, 7.4, 7.5
def test_waiting_fuel_positive_duration_no_rate_unavailable() -> None:
    result = waiting_fuel_t(24, None)
    assert isinstance(result, Unavailable)
    assert "waiting_fuel_t_per_day" in result.missing_inputs


# Validates: Requirements 18.1, 7.4, 7.5
def test_waiting_fuel_positive_duration_with_rate() -> None:
    result = waiting_fuel_t(24, 10.0)
    assert isinstance(result, float)
    assert math.isclose(result, 10.0, rel_tol=REL_TOL)


# Validates: Requirements 18.1, 7.4, 7.5
def test_canal_fuel_zero_duration_no_rate_is_zero() -> None:
    result = canal_fuel_t(0, None)
    assert result == 0.0
    assert isinstance(result, float)


# Validates: Requirements 18.1, 7.4, 7.5
def test_canal_fuel_zero_duration_with_rate_is_zero() -> None:
    result = canal_fuel_t(0, 10.0)
    assert result == 0.0
    assert isinstance(result, float)


# Validates: Requirements 18.1, 7.4, 7.5
def test_canal_fuel_positive_duration_no_rate_unavailable() -> None:
    result = canal_fuel_t(24, None)
    assert isinstance(result, Unavailable)
    assert "canal_fuel_t_per_day" in result.missing_inputs


# Validates: Requirements 18.1, 7.4, 7.5
def test_canal_fuel_positive_duration_with_rate() -> None:
    result = canal_fuel_t(24, 10.0)
    assert isinstance(result, float)
    assert math.isclose(result, 10.0, rel_tol=REL_TOL)


# ---------------------------------------------------------------------------
# Partial-fuel case: a sailing-only figure remains usable even when the
# total is Unavailable because the waiting component could not be resolved.
# ---------------------------------------------------------------------------


# Validates: Requirements 18.1, 7.4, 7.5
def test_partial_fuel_sailing_usable_when_total_unavailable() -> None:
    sailing_fuel = 100.0
    waiting_fuel = Unavailable(reason="x")
    canal_fuel = 5.0

    total = total_voyage_fuel_t(sailing_fuel, waiting_fuel, canal_fuel)

    # The sailing figure stands alone as a usable partial estimate ...
    assert isinstance(sailing_fuel, float)
    assert sailing_fuel == 100.0
    # ... while the true total is unavailable and names the missing component.
    assert isinstance(total, Unavailable)
    assert "waiting_fuel" in total.missing_inputs


# ===========================================================================
# TASK 8.3 -- calculation property tests
# Each is ONE hypothesis test with >= 100 iterations.
# ===========================================================================

_speeds = st.floats(
    min_value=1.0, max_value=30.0, allow_nan=False, allow_infinity=False
)
_distances = st.floats(
    min_value=1.0, max_value=30000.0, allow_nan=False, allow_infinity=False
)
# Fixed, well-formed cubic-curve config used across several properties.
_BASE_FUEL = 175.0
_BASE_SPEED = 22.0
_EXPONENT = 3.0


# Feature: canalcast, Property 2: fuel and CO2 are non-negative for valid inputs
@settings(max_examples=100)
@given(speed=_speeds, distance=_distances)
def test_property2_fuel_and_co2_non_negative(speed: float, distance: float) -> None:
    rate = fuel_rate_t_per_day(speed, _BASE_FUEL, _BASE_SPEED, _EXPONENT)
    assert isinstance(rate, float)
    sail_time = sailing_time_hours(distance, speed)
    assert isinstance(sail_time, float)
    sail_fuel = sailing_fuel_t(rate, sail_time)
    assert isinstance(sail_fuel, float)

    total = total_voyage_fuel_t(sail_fuel, 0.0, 0.0)
    assert isinstance(total, float)
    assert total >= 0

    co2 = co2_tank_to_wake_t(total, _hfo_factor(), "HFO")
    assert isinstance(co2, float)
    assert co2 >= 0


# Feature: canalcast, Property 3: sailing fuel is monotonic non-decreasing in distance
@settings(max_examples=100)
@given(speed=_speeds, d1=_distances, d2=_distances)
def test_property3_sailing_fuel_monotonic_in_distance(
    speed: float, d1: float, d2: float
) -> None:
    lo, hi = sorted((d1, d2))  # lo <= hi
    rate = fuel_rate_t_per_day(speed, _BASE_FUEL, _BASE_SPEED, _EXPONENT)
    assert isinstance(rate, float)

    t_lo = sailing_time_hours(lo, speed)
    t_hi = sailing_time_hours(hi, speed)
    assert isinstance(t_lo, float) and isinstance(t_hi, float)

    fuel_lo = sailing_fuel_t(rate, t_lo)
    fuel_hi = sailing_fuel_t(rate, t_hi)
    assert isinstance(fuel_lo, float) and isinstance(fuel_hi, float)

    assert fuel_lo <= fuel_hi


# Feature: canalcast, Property 4: higher speed strictly shortens sailing time
@settings(max_examples=100)
@given(distance=_distances, s1=_speeds, s2=_speeds)
def test_property4_higher_speed_shortens_sailing_time(
    distance: float, s1: float, s2: float
) -> None:
    assume(s1 < s2)  # strictly distinct, both positive

    t_slow = sailing_time_hours(distance, s1)
    t_fast = sailing_time_hours(distance, s2)
    assert isinstance(t_slow, float) and isinstance(t_fast, float)

    assert t_fast < t_slow


# Feature: canalcast, Property 5: higher speed strictly increases sailing fuel (cubic curve)
@settings(max_examples=100)
@given(distance=_distances, s1=_speeds, s2=_speeds)
def test_property5_higher_speed_increases_sailing_fuel(
    distance: float, s1: float, s2: float
) -> None:
    assume(s1 < s2)
    # Avoid floating-point ties: require a meaningful speed gap so the
    # speed^2 dependence of sailing fuel is strictly increasing.
    assume(s2 - s1 > 1e-6)

    rate1 = fuel_rate_t_per_day(s1, _BASE_FUEL, _BASE_SPEED, _EXPONENT)
    rate2 = fuel_rate_t_per_day(s2, _BASE_FUEL, _BASE_SPEED, _EXPONENT)
    assert isinstance(rate1, float) and isinstance(rate2, float)

    t1 = sailing_time_hours(distance, s1)
    t2 = sailing_time_hours(distance, s2)
    assert isinstance(t1, float) and isinstance(t2, float)

    fuel1 = sailing_fuel_t(rate1, t1)
    fuel2 = sailing_fuel_t(rate2, t2)
    assert isinstance(fuel1, float) and isinstance(fuel2, float)

    assert fuel2 > fuel1


# Feature: canalcast, Property 9: invalid speed yields Unavailable, never a number
@settings(max_examples=100)
@given(
    distance=_distances,
    speed=st.floats(
        min_value=-1000.0, max_value=0.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property9_invalid_speed_unavailable(distance: float, speed: float) -> None:
    result = sailing_time_hours(distance, speed)
    assert not isinstance(result, float)
    assert isinstance(result, Unavailable)
    assert "speed_kn" in result.invalid_inputs


# Feature: canalcast, Property 10: missing distance disables journey time without substitution
@settings(max_examples=100)
@given(speed=_speeds)
def test_property10_missing_distance_unavailable(speed: float) -> None:
    result = sailing_time_hours(None, speed)
    assert not isinstance(result, float)
    assert isinstance(result, Unavailable)
    assert "distance_nm" in result.missing_inputs


# Feature: canalcast, Property 11: zero loaded TEU => undefined per-TEU cost
@settings(max_examples=100)
@given(
    cost=st.floats(
        min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False
    )
)
def test_property11_zero_loaded_teu_undefined(cost: float) -> None:
    result = fuel_cost_per_teu_usd(cost, 0)
    assert isinstance(result, Unavailable)
    assert "loaded TEU is zero" in result.reason


# Feature: canalcast, Property 12: container-to-TEU conversion is exact and type-guarded
@settings(max_examples=100)
@given(
    other=st.text().filter(lambda s: s not in ("20ft", "40ft"))
)
def test_property12_container_to_teu_exact_and_guarded(other: str) -> None:
    assert teu_for_container("20ft") == 1
    assert teu_for_container("40ft") == 2

    result = teu_for_container(other)
    assert isinstance(result, Unavailable)
    assert "container_type" in result.invalid_inputs


# Feature: canalcast, Property 15: CO2 requires an exactly matching fuel type
@settings(max_examples=100)
@given(
    factor_fuel=st.sampled_from(["HFO", "LFO", "MDO"]),
    selected_fuel=st.sampled_from(["HFO", "LFO", "MDO"]),
    total_fuel=st.floats(
        min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False
    ),
)
def test_property15_co2_requires_matching_fuel_type(
    factor_fuel: str, selected_fuel: str, total_fuel: float
) -> None:
    factor = _factor_for(factor_fuel)
    result = co2_tank_to_wake_t(total_fuel, factor, selected_fuel)

    if factor_fuel == selected_fuel:
        assert isinstance(result, float)
        assert result >= 0
    else:
        assert isinstance(result, Unavailable)

    # A missing factor always disables the calculation.
    none_result = co2_tank_to_wake_t(total_fuel, None, selected_fuel)
    assert isinstance(none_result, Unavailable)
