"""Task 15.6: rendered Streamlit regression tests for key labels and states."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def _app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)


def _texts(app: AppTest) -> str:
    groups = (app.title, app.header, app.subheader, app.markdown, app.caption,
              app.info, app.warning)
    return "\n".join(str(el.value) for group in groups for el in group)


def test_default_view_shows_voyage_totals_disclosures_and_provenance():
    app = _app()
    assert not app.exception
    text = _texts(app)
    assert "Scenario tool — not a forecast." in text
    assert "Sailing-only estimate" not in text
    assert "Suez waiting time is not modeled" in text
    assert "speed_kn" in text
    # The canal fuel rate is shown with its source and lower-bound caveat.
    assert "canal_fuel_t_per_day" in text and "LOWER BOUND" in text
    for label in ("Voyage fuel cost", "Fuel cost per loaded TEU",
                  "Fuel-combustion CO2 (tank-to-wake)"):
        values = [str(m.value) for m in app.metric if m.label == label]
        assert len(values) == 2 and not any("unavailable" in v.lower() for v in values)
    assert any(n.label == "Panama waiting time (days)" for n in app.number_input)


def _results_without_fuel_rates(data_dir: str) -> None:
    import dataclasses
    from pathlib import Path

    from src.canalcast.comparison import compare_od_pair
    from src.canalcast.loader import load_all
    from src.canalcast.models import Scenario
    from src.canalcast.ui.views import render_results

    req = load_all(Path(data_dir)).required
    constants = dataclasses.replace(
        req.constants, waiting_fuel_t_per_day=None, canal_fuel_t_per_day=None
    )
    state = next(s for s in req.canal_states if s.state == "current_oct2026")
    hfo = next(f for f in req.emission_factors if f.fuel_type == "HFO")
    pair = next(p for p in req.od_pairs if p.route_id == "shanghai_boston")
    scenario = Scenario(
        od_pair_id=pair.route_id, speed_kn=18.0, load_factor=0.85,
        bunker_price_usd_per_t=876.5, canal_duration_h=12.0, waiting_duration_h=0.0,
        deadline_h=720.0, suez_available=True, selection_priority="fastest",
        fuel_type="HFO", canal_state=state,
    )
    render_results(compare_od_pair(pair, scenario, constants, hfo, state))


def test_missing_fuel_rate_renders_unavailable_and_labeled_partial_estimate():
    app = AppTest.from_function(
        _results_without_fuel_rates, kwargs={"data_dir": str(ROOT / "data")}
    ).run(timeout=30)
    assert not app.exception
    assert "Sailing-only estimate" in _texts(app)
    costs = [m for m in app.metric if m.label == "Voyage fuel cost"]
    assert costs and all("unavailable" in str(m.value).lower() for m in costs)


def test_suez_marked_unavailable_is_shown_as_excluded():
    app = _app()
    next(r for r in app.radio if r.label == "Suez availability").set_value("Unavailable").run()
    assert not app.exception
    assert "Suez is excluded" in _texts(app)


def test_tight_deadline_says_neither_route_meets_it():
    app = _app()
    next(n for n in app.number_input if n.label == "Deadline (days)").set_value(1.0).run()
    assert not app.exception
    assert "Neither route meets the deadline" in _texts(app)


def _chart_with_missing_roni(data_dir: str) -> None:
    import dataclasses
    from pathlib import Path

    from src.canalcast.loader import load_all
    from src.canalcast.models import OptionalSeries
    from src.canalcast.ui.charts import render_oni_roni_chart

    result = load_all(Path(data_dir))
    optional = dict(result.optional)
    optional["roni"] = OptionalSeries(name="roni", available=False, reason="not found")
    render_oni_roni_chart(dataclasses.replace(result, optional=optional))


def test_missing_optional_series_is_named_instead_of_plotted():
    app = AppTest.from_function(
        _chart_with_missing_roni, kwargs={"data_dir": str(ROOT / "data")}
    ).run(timeout=30)
    assert not app.exception
    assert "RONI" in _texts(app)
