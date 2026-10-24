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


def test_default_view_labels_partial_fuel_disclosures_and_provenance():
    app = _app()
    assert not app.exception
    text = _texts(app)
    assert "Scenario tool — not a forecast." in text
    assert "Sailing-only estimate" in text
    assert "Suez waiting time is not modeled" in text
    assert "speed_kn" in text
    costs = [m for m in app.metric if m.label == "Voyage fuel cost"]
    assert costs and all("unavailable" in str(m.value).lower() for m in costs)
    assert any(n.label == "Panama waiting time (days)" for n in app.number_input)


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
