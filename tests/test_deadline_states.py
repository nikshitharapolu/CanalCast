"""Task 15.2 regression tests: deadline and eligibility outcomes."""

import dataclasses
from pathlib import Path

from src.canalcast.comparison import _build_selection, compare_od_pair
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario

DATA = load_all(Path(__file__).resolve().parents[1] / "data").required
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIRS = {p.route_id: p for p in DATA.od_pairs}
NO_RATES = dataclasses.replace(
    DATA.constants, waiting_fuel_t_per_day=None, canal_fuel_t_per_day=None
)


def _run(route_id, deadline_h, suez_available=True, canal_h=0.0, priority="fastest",
         constants=DATA.constants):
    scenario = Scenario(
        od_pair_id=route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=canal_h,
        waiting_duration_h=0.0, deadline_h=deadline_h,
        suez_available=suez_available, selection_priority=priority,
        fuel_type="HFO", canal_state=STATE,
    )
    return compare_od_pair(PAIRS[route_id], scenario, constants, HFO, STATE)


def test_missing_deadline_is_undetermined_not_a_miss():
    sel = _run("shanghai_boston", None).selection
    assert sel.outcome == "feasibility_undetermined"
    assert sel.selected_option is None and sel.no_feasible_option is False
    assert "neither" not in sel.message.lower()
    assert set(sel.unresolved_inputs) == {"panama", "suez"}
    assert all("deadline_h" in inputs for inputs in sel.unresolved_inputs.values())


def test_excluded_suez_is_not_reported_as_missing_the_deadline():
    # Singapore -> New York at 18 kn: Panama ~704 h misses 634.4 h; Suez ~565 h would meet.
    sel = _run("singapore_new_york", 634.4, suez_available=False).selection
    assert sel.outcome == "all_available_miss"
    assert "neither" not in sel.message.lower()
    assert "The only available route, Panama, misses the deadline" in sel.message
    assert sel.closest_option == "panama"


def test_both_available_routes_missing_names_the_faster_route():
    sel = _run("singapore_new_york", 100.0).selection
    assert sel.outcome == "all_available_miss"
    assert sel.message.startswith("Neither route meets the deadline")
    assert sel.closest_option == "suez" and sel.selected_option is None


def test_unavailable_priority_metric_blocks_selection():
    sel = _run("shanghai_boston", 720.0, canal_h=12.0, priority="lowest_co2",
               constants=NO_RATES).selection
    assert sel.outcome == "priority_metric_unavailable"
    assert sel.selected_option is None
    assert any("canal_fuel_t_per_day" in v for v in sel.unresolved_inputs.values())


def test_no_available_option_makes_no_deadline_claim():
    sel = _build_selection("fastest", {}, [], [], {"suez": "marked unavailable"})
    assert sel.outcome == "no_available_option"
    assert "deadline" not in sel.message.lower()
