"""Task 15.3 tests: draft is context only in the MVP; v2 draft loss fails closed."""

import dataclasses
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.canalcast.comparison import compare_od_pair
from src.canalcast.loader import load_all
from src.canalcast.models import Scenario, Unavailable

ROOT = Path(__file__).resolve().parents[1]
DATA = load_all(ROOT / "data").required
STATE = next(s for s in DATA.canal_states if s.state == "current_oct2026")
HFO = next(f for f in DATA.emission_factors if f.fuel_type == "HFO")
PAIR = next(p for p in DATA.od_pairs if p.route_id == "shanghai_boston")


def test_mvp_ui_has_no_draft_loss_controls():
    app = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    assert not app.exception
    assert not any("draft-based cargo loss" in t.label.lower() for t in app.toggle)


def test_enabled_draft_loss_with_missing_slope_fails_closed():
    constants = dataclasses.replace(DATA.constants, context={})
    scenario = Scenario(
        od_pair_id=PAIR.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=0.0,
        waiting_duration_h=0.0, deadline_h=720.0, suez_available=True,
        selection_priority="fastest", fuel_type="HFO", canal_state=STATE,
        draft_loss_enabled=True,
    )
    panama = compare_od_pair(PAIR, scenario, constants, HFO, STATE).panama
    assert isinstance(panama.loaded_teu, Unavailable)
    assert isinstance(panama.fuel_cost_per_teu_usd, Unavailable)
