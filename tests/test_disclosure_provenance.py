"""Task 15.4 tests: accurate tie disclosure and complete input provenance."""

from pathlib import Path

from src.canalcast.comparison import _build_selection, compare_od_pair
from src.canalcast.explain import explain
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario
from src.canalcast.results import ComparisonResult
from tests.test_comparison import _option

DATA = load_all(Path(__file__).resolve().parents[1] / "data").required
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIR = next(p for p in DATA.od_pairs if p.route_id == "shanghai_boston")


def _explain_tie(panama_journey, suez_journey):
    panama = _option("panama", journey_h=panama_journey, cost_per_teu=100.0, co2_t=50.0)
    suez = _option("suez", journey_h=suez_journey, cost_per_teu=100.0, co2_t=50.0)
    sel = _build_selection(
        priority="lowest_cost_per_teu", results={"panama": panama, "suez": suez},
        candidate_names=["panama", "suez"], feasible_candidates=["panama", "suez"],
    )
    result = ComparisonResult(
        od_pair_id="x", panama=panama, suez=suez, excluded_options=(),
        exclusion_reasons={}, selection=sel, comparison_error=None,
    )
    return sel, explain(result)


def test_tie_settled_by_journey_time_does_not_claim_panama_convention():
    sel, text = _explain_tie(panama_journey=600.0, suez_journey=500.0)
    assert sel.selected_option == "suez"
    assert "Panama tie-break" not in text
    assert "lower journey time" in text


def test_full_tie_discloses_panama_convention():
    sel, text = _explain_tie(panama_journey=600.0, suez_journey=600.0)
    assert sel.selected_option == "panama"
    assert "Panama tie-break convention" in text


def test_provenance_covers_scenario_inputs_and_emission_factor():
    scenario = Scenario(
        od_pair_id=PAIR.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=12.0,
        waiting_duration_h=24.0, deadline_h=720.0, suez_available=True,
        selection_priority="fastest", fuel_type="HFO", canal_state=STATE,
    )
    result = compare_od_pair(PAIR, scenario, DATA.constants, HFO, STATE)
    expected = {"speed_kn", "load_factor", "bunker_price_usd_per_t", "canal_duration_h",
                "deadline_h", "suez_available", "fuel_type", "co2_t_per_fuel_t",
                "bunker_price_reference"}
    assert expected | {"waiting_duration_h"} <= set(result.panama.input_provenance)
    assert expected <= set(result.suez.input_provenance)
    assert "waiting_duration_h" not in result.suez.input_provenance
