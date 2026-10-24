"""Sourced waiting and canal fuel rates (Requirement 7.5 resolved by data).

Both rates come from the ICCT 2013-2015 shipping-emissions methodology for the
8,000-12,000 TEU container bin and are loaded as ``approximate``. The canal
rate covers auxiliaries and boilers only, so it is disclosed as a lower bound.
"""

from __future__ import annotations

import math
from pathlib import Path

from src.canalcast.comparison import compute_option
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario, Status

DATA = load_all(Path(__file__).resolve().parents[1] / "data").required
C = DATA.constants
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIR = next(p for p in DATA.od_pairs if p.route_id == "shanghai_boston")

ICCT_URL = "theicct.org/wp-content/uploads/2022/01/Global-shipping-GHG-emissions"


def _expected(aux_kw: float, boiler_kw: float) -> float:
    return (aux_kw * 707 / 3.114 + boiler_kw * 950 / 3.114) * 24 / 1e6


def _option(route, canal_h: float, wait_h: float):
    scenario = Scenario(
        od_pair_id=PAIR.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=canal_h,
        waiting_duration_h=wait_h, deadline_h=720.0, suez_available=True,
        selection_priority="fastest", fuel_type="HFO", canal_state=STATE,
    )
    return compute_option(route, scenario, C, HFO)


def test_rates_load_as_approximate_with_icct_source():
    for pv, aux_kw in ((C.waiting_fuel_t_per_day, 1630), (C.canal_fuel_t_per_day, 2780)):
        assert pv is not None
        assert pv.unit == "t/day"
        assert pv.status is Status.APPROXIMATE
        assert ICCT_URL in pv.rationale
        assert math.isclose(pv.value, round(_expected(aux_kw, 520), 2), rel_tol=1e-9)
    assert "LOWER BOUND" in (C.canal_fuel_t_per_day.method or "")
    assert "main engine assumed off" in (C.waiting_fuel_t_per_day.method or "")


def test_canal_and_panama_waiting_fuel_add_exactly_rate_times_days():
    base = _option(PAIR.panama, 0.0, 0.0)
    both = _option(PAIR.panama, 12.0, 48.0)
    assert math.isclose(both.fuel.canal_fuel_t, C.canal_fuel_t_per_day.value * 0.5, rel_tol=1e-9)
    assert math.isclose(both.fuel.waiting_fuel_t, C.waiting_fuel_t_per_day.value * 2.0, rel_tol=1e-9)
    assert math.isclose(
        both.fuel.total_voyage_fuel_t,
        base.fuel.total_voyage_fuel_t + both.fuel.canal_fuel_t + both.fuel.waiting_fuel_t,
        rel_tol=1e-9,
    )
    assert both.co2_tank_to_wake_t > base.co2_tank_to_wake_t
    assert both.sailing_only_label is None


def test_rates_appear_in_result_provenance():
    option = _option(PAIR.panama, 12.0, 48.0)
    assert "canal_fuel_t_per_day" in option.input_provenance
    assert "waiting_fuel_t_per_day" in option.input_provenance