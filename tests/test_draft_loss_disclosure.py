"""Disclosure and fixed-fuel checks for the optional draft-loss feature (Req 20.9, 20.10).

Verifies that enabling draft loss (a) states the assumed slope, the
container-to-TEU conversion, and the ship-applicability limit, (b) does not
contradict itself with the v1 "not modeled" text, and (c) leaves voyage fuel,
fuel cost, and CO2 unchanged while loaded TEU falls.
"""

from __future__ import annotations

from pathlib import Path

from src.canalcast.comparison import compute_option
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario, Unavailable

_REQ = load_all(Path(__file__).resolve().parents[1] / "data").required
_STATES = {s.state: s for s in _REQ.canal_states}
_HFO = next(e for e in _REQ.emission_factors if e.fuel_type == "HFO")
_OD = next(o for o in _REQ.od_pairs if o.route_id == "shanghai_boston")


def _scenario(enabled: bool) -> Scenario:
    return Scenario(
        od_pair_id=_OD.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=0.0,
        waiting_duration_h=0.0, deadline_h=None, suez_available=True,
        selection_priority="fastest", fuel_type="HFO",
        canal_state=_STATES["current_oct2026"], draft_loss_enabled=enabled,
        containers_lost_per_10cm=100.0, avg_teu_per_container=1.7,
    )


def test_disclosure_states_slope_conversion_applicability_and_fixed_fuel():
    result = compute_option(_OD.panama, _scenario(True), _REQ.constants, _HFO)
    text = result.draft_loss_disclosure or ""
    assert "100 containers lost per 10 cm" in text          # assumed slope
    assert "linearly" in text
    assert "analyst estimate" in text
    assert "1.7" in text and "TEU" in text                  # conversion
    assert "10,000-TEU ship" in text and "85%" in text      # applicability
    assert "load to the full reference draft" in text
    assert "fuel and CO2 tonnes are held fixed" in text


def test_v1_not_modeled_text_is_not_shown_when_loss_is_modeled():
    on = compute_option(_OD.panama, _scenario(True), _REQ.constants, _HFO)
    off = compute_option(_OD.panama, _scenario(False), _REQ.constants, _HFO)
    assert "not modeled" not in on.draft_not_modeled_disclosure
    assert "draft cargo-loss" not in on.exclusions
    # Default-off keeps the v1 wording and exclusion exactly.
    assert "not modeled" in off.draft_not_modeled_disclosure
    assert "draft cargo-loss" in off.exclusions


def test_suez_is_told_draft_limits_do_not_apply():
    suez = compute_option(_OD.suez, _scenario(True), _REQ.constants, _HFO)
    assert "not applied to the Suez route" in (suez.draft_loss_disclosure or "")
    assert suez.teu_lost == 0.0


def test_voyage_fuel_cost_and_co2_fixed_while_loaded_teu_falls():
    off = compute_option(_OD.panama, _scenario(False), _REQ.constants, _HFO)
    on = compute_option(_OD.panama, _scenario(True), _REQ.constants, _HFO)
    assert not isinstance(on.loaded_teu, Unavailable)
    assert on.loaded_teu < off.loaded_teu                    # payload fell
    assert on.fuel.total_voyage_fuel_t == off.fuel.total_voyage_fuel_t
    assert on.fuel.sailing_fuel_t == off.fuel.sailing_fuel_t
    assert on.voyage_fuel_cost_usd == off.voyage_fuel_cost_usd
    assert on.co2_tank_to_wake_t == off.co2_tank_to_wake_t
    assert on.fuel_cost_per_teu_usd > off.fuel_cost_per_teu_usd
