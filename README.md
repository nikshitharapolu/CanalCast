# CanalCast 🚢

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

CanalCast v1 runs **locally only** (Req 19.3): `.streamlit/config.toml` binds the
server to `localhost`. Hosted deployment, including Streamlit Community Cloud,
is out of scope for v1 because it creates a public endpoint. Adding it later
needs its own access-control decision.

## Data & provenance

All data is local CSV under [`data/`](./data). Every model input carries
provenance — a source/status (sourced, approximate, assumption, or derived) and
data date. **No network calls are made at runtime.** When a required value is
missing it stays missing: the affected calculation is disabled and the app
states what is needed, rather than substituting zero or an invented number.

## Optional draft-based cargo loss (off by default)

The sidebar toggle **Model draft-based cargo loss (v2)** is off by default; with it
off, the canal draft is shown as context only and no result changes with the
preset. When on, for the **Panama option only**:

```
shortfall_ft     = 50.0 (reference draft) - canal-state draft, clamped at 0
containers_lost  = shortfall_ft x 30.48 / 10 x containers-lost-per-10cm
TEU_lost         = containers_lost x average TEU per container
loaded TEU       = capacity x load factor - TEU_lost   (never below 0)
```

Defaults: 100 containers per 10 cm (analyst estimate) and 1.7 TEU per container
(assumption). Both are adjustable in the sidebar and disclosed next to the results.

## Model limitations

- **Not a forecast.** It computes the consequences of the scenario you choose.
- **Fuel cost only.** Tolls, insurance, carrier surcharges and other costs are
  excluded. CO2 is tank-to-wake fuel combustion, not lifecycle.
- **Draft-loss slope is an assumption.** The 100 containers per 10 cm figure is an
  analyst estimate for Asia-USEC carriers (Seatrade Maritime, Jul 2026). It is
  applied linearly to the whole shortfall and is not a measurement for the
  modeled ship.
- **Container-to-TEU factor is an assumption** (1.7 TEU per lost container; a
  20 ft container is 1 TEU and a 40 ft container is 2 TEU).
- **Ship applicability is not established.** The loss model assumes the modeled
  10,000-TEU ship at 85% load would otherwise load to the full 50 ft reference
  draft. A ship loaded below that draft could lose less, or nothing.
- **Fuel and CO2 stay fixed when payload falls.** Draft loss changes only loaded
  TEU and the per-TEU figures. A lighter ship would burn somewhat less fuel; the
  model does not capture that, so cost per TEU is, if anything, overstated.
- **Waiting and canal fuel rates are size-bin averages.** Waiting at anchor
  burns 12.69 t/day and canal transit 18.96 t/day. Both are derived from the
  ICCT 2013-2015 shipping-emissions methodology (auxiliary engine and boiler
  power for 8,000-12,000 TEU container ships) and marked `approximate`. They
  are not specific to the modeled ship. The canal rate is a lower bound because
  it leaves out main-engine propulsion during the transit. If either rate is
  removed from `data/constants.csv`, the affected totals show as unavailable
  and the app shows a labeled sailing-only estimate instead.
- **Route distances are approximate** (searoute shortest paths) with no weather
  routing, port calls, or canal availability checks.
- **The route set is small and fixed.** `data/routes.csv` holds 10 origin-destination pairs (Asia to the US East Coast and Gulf). Each Panama and Suez distance came from `searoute 1.4.3` run offline with approximate approach points, and each was checked to pass through its own canal and not around a cape. To add a route, generate both rows the same way and keep status `approximate`; do not hand-type distances.
- **Booking slots are not transits and do not set waiting time.** Waiting is an
  explicit input.
- **Historical ONI/RONI charts are context only.** They do not change with the
  route or scenario, and historical replay is not model validation.
- **Waiting time applies only to Panama.** Suez waiting isn't modeled, and the
  Suez result says so.
- **The UI has focused rendered tests** (Streamlit `AppTest`) for key labels and
  states; it isn't property-tested.

## Verified environments

Tests and the app were run on Python 3.11.9 with the pinned `requirements.txt`.
The test suite also passes on Python 3.13.2.
