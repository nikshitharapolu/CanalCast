"""Task 15.7 tests: waiting applies only to Panama; Suez waiting is not modeled."""

import math
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from src.canalcast.comparison import compare_od_pair
from src.canalcast.loader import load_all
from src.canalcast.models import NotModeled, Scenario, Unavailable

DATA = load_all(Path(__file__).resolve().parents[1] / "data").required
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIR = next(p for p in DATA.od_pairs if p.route_id == "shanghai_new_york")


def _run(wait_h, deadline_h=960.0, priority="fastest"):
    scenario = Scenario(
        od_pair_id=PAIR.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=12.0,
        waiting_duration_h=wait_h, deadline_h=deadline_h, suez_available=True,
        selection_priority=priority, fuel_type="HFO", canal_state=STATE,
    )
    return compare_od_pair(PAIR, scenario, DATA.constants, HFO, STATE)


def _jt(option):
    return float(option.journey.journey_time_h)


# Feature: canalcast, Property 16: waiting changes only the Panama journey time.
@settings(max_examples=100, deadline=None)
@given(
    w1=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False),
    w2=st.floats(min_value=0.0, max_value=2000.0, allow_nan=False),
)
def test_property_16_waiting_moves_only_panama(w1, w2):
    r1, r2 = _run(w1), _run(w2)
    assert _jt(r1.suez) == _jt(r2.suez)
    assert math.isclose(_jt(r2.panama), _jt(r1.panama) + (w2 - w1), rel_tol=1e-9)


def test_panama_waiting_flips_fastest_route_after_break_even():
    assert _run(72.0).selection.selected_option == "panama"   # 28.1 vs 29.2 days
    assert _run(120.0).selection.selected_option == "suez"    # 30.1 vs 29.2 days
    gap = _jt(_run(0.0).suez) - _jt(_run(0.0).panama)
    assert math.isclose(gap, (12380.2 - 10638.9) / 18.0, rel_tol=1e-9)  # ~96.7 h


def test_missing_waiting_disables_only_panama():
    result = _run(None)
    panama_jt = result.panama.journey.journey_time_h
    assert isinstance(panama_jt, Unavailable)
    assert "waiting_duration_h" in panama_jt.missing_inputs
    assert result.panama.deadline_status == "undetermined"
    assert isinstance(result.suez.journey.journey_time_h, float)
    assert "neither" not in result.selection.message.lower()


def test_suez_result_identical_for_any_waiting_input():
    base = _run(0.0).suez
    for wait in (48.0, None, -5.0, float("nan")):
        other = _run(wait).suez
        assert other.journey == base.journey
        assert other.fuel == base.fuel
        assert isinstance(other.journey.waiting_duration_h, NotModeled)
        assert isinstance(other.fuel.waiting_fuel_t, NotModeled)
        assert "Suez waiting time (not modeled)" in other.exclusions
        assert other.waiting_not_modeled_disclosure
