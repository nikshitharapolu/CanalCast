# CanalCast

CanalCast is a scenario simulator that compares the **Panama** and **Suez**
routings for a single origin–destination pair under Panama Canal conditions you
select (draft limit, booking slots, speed, load factor, bunker price, waiting
time, deadline, and selection priority). **It is not a forecast.** Every
displayed number is computed by typed Python functions in a pure calculation
core — nothing is predicted or invented. The tool reports **fuel cost** (not
total shipping cost) and **tank-to-wake CO₂** (fuel-combustion emissions, not
lifecycle); tolls, insurance, and surcharges are excluded and disclosed in the
app.

## Requirements

- **Python 3.11+** (the project targets Python 3.11 per `tech.md`; it also runs
  on newer CPython such as 3.14).
- Dependencies are listed and pinned to exact versions in
  [`requirements.txt`](./requirements.txt).

## Local run

1. (Optional) create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate
   ```

2. Install the pinned dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Launch the app (entry point is `app.py`):

   ```bash
   streamlit run app.py
   ```

   If the `streamlit` console script is not on your `PATH`, use the module form
   instead:

   ```bash
   python -m streamlit run app.py
   ```

The app serves on <http://localhost:8501> by default. CanalCast v1 is
**local only** — it exposes no public endpoint (Req 19.3).

## Run the tests

```bash
pip install -r requirements.txt
python -m pytest        # or: pytest
```

The pure calculation core is fully tested with both property-based (Hypothesis)
and worked-example/edge-case tests. The Streamlit UI is built on top of this
tested core.

## Project layout

```
app.py                      Streamlit entry point (wires loader -> core -> UI)
requirements.txt            Pinned dependencies
data/                       Read-only CSV inputs (routes, constants, factors, ...)
tests/                      Core test suite (unit + property-based)
src/canalcast/
    models.py               Typed domain records + provenance
    loader.py               All file I/O with provenance (no network calls)
    calculations.py         Pure calculation functions
    comparison.py           Route comparison and selection
    results.py              Result structures
    explain.py              Deterministic (<=120-word) explanation
    ui/                      Streamlit controls, views, and charts
```

The core modules (`calculations`, `comparison`, `results`, `models`, `explain`)
perform no file or network I/O; only `loader.py` reads from `data/`. The UI
layer imports the core, and the core never imports Streamlit.

## Deployment (Streamlit)

The entry point is **`app.py`**. A standard Streamlit deployment runs:

```bash
streamlit run app.py
```

For **Streamlit Community Cloud**, point the app at `app.py` as the main file
and use `requirements.txt` as the dependency file. CanalCast v1 is intended to
run locally and is **not exposed publicly by default** (Req 19.3).

## Data & provenance

All data is local CSV under [`data/`](./data). Every model input carries
provenance — a source/status (sourced, approximate, assumption, or derived) and
data date. **No network calls are made at runtime.** When a required value is
missing it stays missing: the affected calculation is disabled and the app
states what is needed, rather than substituting zero or an invented number.
