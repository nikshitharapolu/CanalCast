"""Task 15.1 regression tests: voyage cost and CO2 need resolved total fuel."""

import math
from pathlib import Path

import pytest

from src.canalcast.comparison import compare_od_pair
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario, Unavailable
from src.canalcast.results import SAILING_ONLY_LABEL

DATA = load_all(Path(__file__).resolve().parents[1] / "data").required
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIR = next(p for p in DATA.od_pairs if p.route_id == "shanghai_boston")


def _run(canal_h: float, priority: str = "fastest"):
    scenario = Scenario(
        od_pair_id=PAIR.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=canal_h,
        waiting_duration_h=0.0, deadline_h=720.0, suez_available=True,
        selection_priority=priority, fuel_type="HFO", canal_state=STATE,
    )
    return compare_od_pair(PAIR, scenario, DATA.constants, HFO, STATE)


def test_default_canal_time_without_rate_leaves_voyage_metrics_unavailable():
    result = _run(12.0)
    for option in (result.panama, result.suez):
        for value in (option.voyage_fuel_cost_usd, option.fuel_cost_per_teu_usd,
                      option.co2_tank_to_wake_t):
            assert isinstance(value, Unavailable)
            assert "canal_fuel_t_per_day" in value.missing_inputs
        assert isinstance(option.sailing_only_fuel_cost_usd, float)
        assert isinstance(option.sailing_only_co2_t, float)
        assert option.sailing_only_label == SAILING_ONLY_LABEL


def test_zero_canal_time_resolves_totals_from_formulas():
    option = _run(0.0).panama
    fuel_t = 175.0 * (18.0 / 22.0) ** 3 * (10783.5 / 18.0) / 24.0
    assert math.isclose(option.fuel.total_voyage_fuel_t, fuel_t, rel_tol=1e-9)
    assert math.isclose(option.voyage_fuel_cost_usd, fuel_t * 876.5, rel_tol=1e-9)
    assert math.isclose(option.fuel_cost_per_teu_usd, fuel_t * 876.5 / 8500.0, rel_tol=1e-9)
    assert math.isclose(option.co2_tank_to_wake_t, fuel_t * 3.114, rel_tol=1e-9)
    assert option.sailing_only_fuel_cost_usd is None
    assert option.sailing_only_label is None


@pytest.mark.parametrize("priority", ["lowest_cost_per_teu", "lowest_co2"])
def test_cost_and_co2_priorities_never_select_on_sailing_only_values(priority):
    assert _run(12.0, priority).selection.selected_option is None
