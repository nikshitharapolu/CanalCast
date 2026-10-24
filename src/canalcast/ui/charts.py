"""Historical ONI/RONI context charts for the Streamlit_Interface.

This module is part of the Streamlit_Interface, not the Calculation_Core, so it
MAY import ``streamlit`` and ``plotly`` (the core never does). To keep the module
importable outside a running Streamlit session, every widget/plot call is wrapped
inside :func:`render_oni_roni_chart`; importing the module runs no Streamlit or
plotly code at import time, and the pure helper :func:`_extract_series` can be
reasoned about without any runtime.

The chart presents the Oceanic Nino Index (ONI) and the Relative Oceanic Nino
Index (RONI) as historical observations only. The following requirements govern
its behavior:

* **Req 16.1** ONI and RONI are drawn as two visually distinct, separately
  labelled traces; they are NEVER combined, averaged, or summed into one series.
* **Req 16.2** An unavailable series is omitted and a visible in-chart note names
  which series is missing, while the available series still renders without error.
* **Req 16.3** When every series is unavailable the chart is suppressed and a
  visible note reports that no historical data is available; the app keeps running.
* **Req 16.4** No text/caption/label/annotation states or implies that an ENSO
  index (ONI or RONI) predicts, forecasts, or causes Panama Canal restrictions;
  captions stay strictly descriptive of the historical series.
* **Req 16.5** A visible label identifies the chart as historical observations and
  a visible statement declares that historical replay does not constitute model
  validation, both in the same chart view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping

from ..models import LoadResult, OptionalSeries

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import cost
    import plotly.graph_objects as go

__all__ = ["render_oni_roni_chart"]


# --- Presentation copy (Req 16.4, 16.5) ------------------------------------
# Strictly descriptive of the historical series. No predictive/forecast/causal
# language about ONI, RONI, ENSO, or canal restrictions appears anywhere here.
_CHART_TITLE = "Historical observations: ONI and RONI"
_VALIDATION_NOTE = "Historical replay does not constitute model validation."
_NO_DATA_NOTE = "No historical data is available for this chart."

# Accessible, distinguishable colors for the two series. Blue (#1f77b4) and
# orange (#d55e00) are a common colorblind-safe pair that also differ in
# luminance, so the two traces remain distinguishable beyond color alone.
_ONI_COLOR = "#1f77b4"
_RONI_COLOR = "#d55e00"

# The configured series: (series key in load_result.optional, value column, label).
_SERIES = (
    ("oni", "oni", "ONI", _ONI_COLOR),
    ("roni", "roni", "RONI", _RONI_COLOR),
)


def _extract_series(
    series: OptionalSeries, value_key: str
) -> tuple[list[str], list[float]]:
    """Extract aligned ``(months, values)`` lists from one optional series.

    Pure helper with no Streamlit or plotly dependency so it can be unit-reasoned
    without a runtime. Reads the ``month`` column for x and ``value_key`` for y,
    keeping only rows where the value parses to a finite ``float`` (loader stores
    every cell as a trimmed string, so parsing is required). The two returned
    lists are positionally aligned and never combined with any other series,
    preserving the one-series-per-index invariant (Req 16.1).

    Args:
        series: The :class:`~canalcast.models.OptionalSeries` to read. When the
            series is unavailable its ``rows`` are empty, yielding two empty lists.
        value_key: The row key holding the numeric value (``"oni"`` or ``"roni"``).

    Returns:
        A ``(months, values)`` tuple of equal length. ``months`` holds the raw
        month strings (e.g. ``"2022-01-01"``) and ``values`` the parsed floats.
    """
    months: list[str] = []
    values: list[float] = []
    for row in series.rows:
        raw_month = row.get("month")
        raw_value = row.get(value_key)
        if raw_month is None or raw_value is None:
            continue
        month = str(raw_month).strip()
        value_text = str(raw_value).strip()
        if not month or not value_text:
            continue
        try:
            value = float(value_text)
        except (TypeError, ValueError):
            continue
        # Exclude non-finite values (NaN/inf) to avoid misleading plotted points.
        if value != value or value in (float("inf"), float("-inf")):
            continue
        months.append(month)
        values.append(value)
    return months, values


def _optional_from(
    optional: Mapping[str, OptionalSeries], key: str
) -> OptionalSeries:
    """Return the named optional series, or an ``unavailable`` stand-in.

    A series absent from the mapping is treated exactly like one the loader
    recorded as unavailable, so downstream rendering uniformly handles the
    missing case (Req 16.2, 16.3).
    """
    found = optional.get(key)
    if found is not None:
        return found
    return OptionalSeries(
        name=key,
        available=False,
        reason="not found",
        rows=(),
        provenance=None,
    )


def render_oni_roni_chart(source: LoadResult | Mapping[str, OptionalSeries]) -> None:
    """Render the historical ONI/RONI chart into the current Streamlit view.

    Accepts either a :class:`~canalcast.models.LoadResult` or its ``optional``
    mapping directly. All Streamlit and plotly calls happen inside this function,
    so merely importing the module stays side-effect free.

    Behavior:

    * Each available series is drawn as its own labelled trace with a distinct,
      accessible color; the two are never combined, averaged, or summed
      (Req 16.1).
    * An unavailable series is omitted and a visible caption names it, while the
      available series still renders (Req 16.2).
    * When all series are unavailable the chart is suppressed and a visible note
      reports the absence; the caller (app) keeps running (Req 16.3).
    * All visible copy is strictly descriptive, with no predictive/forecast/causal
      claims about ONI, RONI, ENSO, or canal restrictions (Req 16.4).
    * The chart is labelled as historical observations and carries the statement
      that historical replay does not constitute model validation (Req 16.5).

    Args:
        source: The full :class:`~canalcast.models.LoadResult` or its optional
            series mapping.
    """
    # Imported lazily so the module imports cleanly without a Streamlit runtime.
    import plotly.graph_objects as go
    import streamlit as st

    optional: Mapping[str, OptionalSeries]
    optional = source.optional if isinstance(source, LoadResult) else source

    fig = go.Figure()
    plotted_any = False
    unavailable_labels: list[str] = []

    for key, value_key, label, color in _SERIES:
        series = _optional_from(optional, key)
        if not series.available:
            unavailable_labels.append(label)
            continue
        months, values = _extract_series(series, value_key)
        if not months:
            # Available but contains no usable points: treat as unavailable for
            # display and name it so the view stays honest (Req 16.2).
            unavailable_labels.append(label)
            continue
        fig.add_trace(
            go.Scatter(
                x=months,
                y=values,
                mode="lines+markers",
                name=label,
                legendgroup=label,
                line=dict(color=color, width=2),
                marker=dict(color=color, size=5),
            )
        )
        plotted_any = True

    # Req 16.3: nothing plottable -> suppress the chart, show a visible note,
    # and return so the rest of the simulator continues running.
    if not plotted_any:
        st.subheader(_CHART_TITLE)
        st.warning(_NO_DATA_NOTE)
        st.caption(_VALIDATION_NOTE)
        return

    # Req 16.5: historical-observations title and validation-disclaimer caption,
    # both present in the same chart view.
    fig.update_layout(
        title=_CHART_TITLE,
        xaxis_title="Month (historical observation)",
        yaxis_title="Index value (degC)",
        legend_title_text="Series",
        hovermode="x unified",
    )

    st.subheader(_CHART_TITLE)
    st.plotly_chart(fig, use_container_width=True)

    # Req 16.2: name any series omitted because it was unavailable, inside the
    # same chart view, without erroring on the series that did render.
    if unavailable_labels:
        joined = " and ".join(unavailable_labels)
        st.caption(
            f"The {joined} series "
            f"{'is' if len(unavailable_labels) == 1 else 'are'} unavailable and "
            "omitted from this chart."
        )

    st.caption(_VALIDATION_NOTE)
