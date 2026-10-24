"""CanalCast — Streamlit entry point composing loader -> core -> explanation -> UI.

Run locally with::

    streamlit run app.py

This module is the Streamlit_Interface entry point. It is the ONLY place that
wires the pure Calculation_Core (loader, comparison, explanation) to the
Streamlit widgets. The architectural contract is strict: the UI layer imports
the core, and the core NEVER imports Streamlit (design "Streamlit Interface
Design"; Requirements 19.1, 19.2). Keeping all Streamlit calls in ``app.py`` and
the ``ui`` package preserves that one-directional dependency.

Responsibilities (Requirements 17.1, 19.1, 19.2):

* Load required/optional data once via :func:`canalcast.loader.load_all`,
  wrapped so a :class:`~canalcast.loader.LoaderError` surfaces to the UI naming
  the failing file (Req 1.8) and stops the app. Loading is cached so reruns are
  cheap; no network call is made anywhere (Req 1.7).
* Render the sidebar scenario controls, assemble a :class:`Scenario`, and — when
  inputs are complete — call :func:`canalcast.comparison.compare_od_pair` and
  render the side-by-side results, the <=120-word deterministic explanation
  (rendered inside :func:`canalcast.ui.views.render_results`), and the
  disclosure panel.
* Always render the historical ONI/RONI observations section, even when no
  comparison can be run (Req 16).

Everything stays local; the app exposes no public endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Under ``streamlit run app.py`` the current working directory is the repo root,
# but the script directory is not guaranteed to be on ``sys.path``. Insert it so
# the ``src.canalcast`` package resolves whether launched via ``streamlit run``
# or imported directly for a smoke test.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from src.canalcast.comparison import compare_od_pair
from src.canalcast.loader import LoaderError, load_all
from src.canalcast.models import (
    CanalState,
    EmissionFactor,
    LoadResult,
    ODPair,
    Scenario,
)
from src.canalcast.ui.charts import render_oni_roni_chart
from src.canalcast.ui.controls import render_sidebar
from src.canalcast.ui.views import render_results

#: Directory holding the read-only CSV inputs, relative to the repo root.
DATA_DIR = Path(_REPO_ROOT) / "data"

#: The fixed framing shown in the header; the authoritative disclaimer text
#: "Scenario tool — not a forecast." is also rendered by the results view.
_INTRO = (
    "CanalCast compares the Panama and Suez routings for a single "
    "origin-destination pair under a scenario you choose. It is a scenario "
    "exploration tool — not a forecast."
)


@st.cache_data(show_spinner="Loading CanalCast data…")
def load_data(data_dir: str) -> LoadResult:
    """Load the required and optional data, cached on the data directory.

    The loader performs only read-only file I/O and makes no network call
    (Req 1.7), so caching the result on the directory path is safe and keeps
    Streamlit reruns cheap. A :class:`~canalcast.loader.LoaderError` is allowed
    to propagate so the caller can surface it to the UI and stop (Req 1.8).

    Args:
        data_dir: Filesystem path to the directory of CSV inputs. Passed as a
            string so Streamlit can hash it for the cache key.

    Returns:
        The fully assembled :class:`~canalcast.models.LoadResult`.

    Raises:
        LoaderError: On a missing/unreadable required file or a provenance
            failure; the caller renders the message and stops.
    """
    return load_all(Path(data_dir))


def select_emission_factor(
    load_result: LoadResult, fuel_type: str
) -> EmissionFactor | None:
    """Return the loaded emission factor whose fuel type matches the scenario.

    The match is exact: CO2 is only computed with a factor whose ``fuel_type``
    equals the scenario's selected fuel type (Req 9.2-9.4). When no factor
    matches, ``None`` is returned so the core marks the CO2 metric unavailable
    rather than substituting a value.

    Args:
        load_result: The loaded required/optional data.
        fuel_type: The scenario's selected fuel-type identifier.

    Returns:
        The matching :class:`~canalcast.models.EmissionFactor`, or ``None`` when
        none matches.
    """
    for factor in load_result.required.emission_factors:
        if factor.fuel_type == fuel_type:
            return factor
    return None


def render_comparison(
    load_result: LoadResult, scenario: Scenario, selected_od_pair: ODPair
) -> None:
    """Run the core comparison for the selected scenario and render the results.

    Picks the emission factor matching ``scenario.fuel_type`` (Req 9), resolves
    the canal state from the scenario, calls
    :func:`~canalcast.comparison.compare_od_pair`, and hands the
    :class:`~canalcast.results.ComparisonResult` to
    :func:`~canalcast.ui.views.render_results`, which renders the five metrics,
    the selection, the deterministic explanation, and the disclosure panel.

    Args:
        load_result: The loaded required/optional data.
        scenario: The assembled scenario to evaluate.
        selected_od_pair: The OD pair chosen in the controls.
    """
    emission_factor: EmissionFactor | None = select_emission_factor(
        load_result, scenario.fuel_type
    )
    canal_state: CanalState = scenario.canal_state

    result = compare_od_pair(
        selected_od_pair,
        scenario,
        load_result.required.constants,
        emission_factor,
        canal_state,
    )
    render_results(result)


def render_historical_section(load_result: LoadResult) -> None:
    """Render the clearly separated historical ONI/RONI observations section.

    This section is independent of the comparison and always renders, so the app
    stays useful even when no scenario can be evaluated (Req 16.3).

    Args:
        load_result: The loaded required/optional data.
    """
    st.divider()
    st.header("Historical observations")
    st.caption(
        "Observed ONI and RONI series shown for historical context only. "
        "Historical replay does not constitute model validation and does not "
        "forecast canal conditions."
    )
    render_oni_roni_chart(load_result)


def main() -> None:
    """Compose the full CanalCast app: load, controls, comparison, charts.

    Top-level flow (Req 17.1, 19.1, 19.2):

    1. Configure the page and show the intro/framing.
    2. Load data (cached); on a :class:`LoaderError` show the failing file and
       stop (Req 1.8).
    3. Render the sidebar controls to obtain a scenario, messages, and the
       selected OD pair.
    4. When the scenario or OD pair is incomplete, explain what is needed and
       skip the comparison; still render the historical section.
    5. Otherwise run the comparison and render the results, then the historical
       section.
    """
    st.set_page_config(
        page_title="CanalCast",
        page_icon="🚢",
        layout="wide",
    )

    st.title("CanalCast")
    st.write(_INTRO)

    # --- 2. Load data, surfacing a required-file failure to the UI --------
    try:
        load_result = load_data(str(DATA_DIR))
    except LoaderError as error:
        st.error(
            "CanalCast could not load its required data and cannot run: "
            f"{error}"
        )
        st.stop()
        return  # Unreachable after st.stop(); keeps type-checkers happy.

    # --- 3. Sidebar controls ---------------------------------------------
    scenario, messages, selected_od_pair = render_sidebar(load_result)

    # --- 4. Incomplete inputs: explain and skip the comparison ------------
    if scenario is None or selected_od_pair is None:
        st.info(
            "Complete the scenario inputs in the sidebar to run a comparison. "
            "The historical observations below are shown regardless."
        )
        for message in messages:
            st.warning(message)
        render_historical_section(load_result)
        return

    # --- 5. Run the comparison and render the results ---------------------
    render_comparison(load_result, scenario, selected_od_pair)
    render_historical_section(load_result)


if __name__ == "__main__":
    main()
