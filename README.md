# CanalCast

**Panama or Suez when the canal tightens?** A scenario simulator that compares the two routings for Asia to US East Coast and Gulf container trades under Panama Canal conditions you choose.

Hackachusetts 2026 · Track: **Climate Tech & Clean Energy** · Built with Kiro

Demo URL: https://shipping-route-sim.streamlit.app/

Demo video (under 3 minutes): PASTE_PUBLIC_VIDEO_LINK

<!-- Add a screenshot once the UI is final:
![CanalCast comparing Panama and Suez](docs/screenshot.png)
-->

## Quick start (for judges)

```bash
git clone https://github.com/nikshitharapolu/CanalCast.git
cd CanalCast
pip install -r requirements.txt
streamlit run app.py        # opens http://localhost:8501
```

After downloading the repository and installing dependencies, the app runs locally without an account, API key, or internet connection. Run the tests with `python -m pytest` (102 tests). Requires Python 3.11 or newer.

## What it does

You pick one of 10 lanes (Shanghai, Busan, Hong Kong or Singapore to New York, Boston, Savannah or Houston), set the voyage inputs (speed, load factor, bunker price, Panama waiting time, canal transit time, deadline, selection priority) and choose a Panama Canal condition. CanalCast then compares Panama with Suez and reports, for each route:

- journey time
- voyage fuel cost, and fuel cost per loaded TEU
- tank-to-wake (fuel-combustion) CO₂
- whether the route meets your deadline

**It is a scenario tool, not a forecast.** Every displayed number is computed by typed Python functions in a pure calculation core. Nothing is predicted or invented, and every input shows its value, unit, source or assumption, and status (sourced, approximate, assumption or derived).

Other behavior worth knowing:

- **One metric at a time.** The route is chosen by fastest, lowest fuel cost per TEU, or lowest CO₂, among routes that meet the deadline. Metrics are never blended into a score, and ties say which rule broke them.
- **Distinct failure messages.** A missing deadline, no available route, and every available route missing the deadline each get their own message.
- **Honest degradation.** If a required input is missing, the affected calculation is disabled and the screen says what is needed. Nothing is replaced by zero. A partial figure appears only as a labeled sailing-only estimate and is never used to pick a route.
- **Plain-language explanation** of at most 120 words, generated deterministically from the computed result. There is no language-model call at runtime.
- **El Niño context.** Historical ONI and RONI series are shown as two separate lines, as context only.

### Worked example

Shanghai to Boston at 18 knots, 85% load factor, $876.50 per tonne, 12 hours of canal transit and a 30-day (720 hour) deadline. Only Panama waiting time changes:

| Panama waiting | Panama time | Panama $/TEU | Suez time | Suez $/TEU | Chosen (fastest) |
|---|---|---|---|---|---|
| 0 days | 611.1 h | $247.7 | 693.7 h | $281.7 | Panama |
| 3 days | 683.1 h | $251.6 | 693.7 h | $281.7 | Panama |
| 4 days | 707.1 h | $252.9 | 693.7 h | $281.7 | Suez |
| 5 days | 731.1 h | $254.2 | 693.7 h | $281.7 | Suez (Panama misses the deadline) |

With "fastest", Suez takes over once Panama waiting passes about 3.4 days (82.6 hours). With "lowest fuel cost per TEU", Panama stays cheaper at every waiting time shown, but at 5 days it misses the deadline, so every priority picks Suez. The tool shows both facts instead of one verdict.

## How the numbers work

- **Sailing time** = distance ÷ speed.
- **Fuel** follows one documented curve: 175 t/day at 22 knots, scaled by (speed ÷ 22)³. Waiting and canal-transit fuel are separate line items.
- **Voyage fuel cost** = total fuel × bunker price. **Cost per TEU** divides that by loaded TEU (capacity × load factor).
- **CO₂** = total fuel × the IMO tank-to-wake factor for the selected fuel.
- **Waiting time applies to Panama only.** The Suez result states that Suez waiting is not modeled, so no one reads its time as including queueing.

## Optional draft-based cargo loss (tested core code, off in the interface)

The core includes an opt-in model that turns a tighter Panama draft into lost payload, for the Panama option only:

```
shortfall_ft    = 50.0 (reference draft) - canal-state draft, not below 0
containers_lost = shortfall_ft x 30.48 / 10 x containers-lost-per-10cm
TEU_lost        = containers_lost x average TEU per container
loaded TEU      = capacity x load factor - TEU_lost   (never below 0)
```

Defaults are 100 containers per 10 cm (an analyst estimate for Asia to US East Coast carriers, Seatrade Maritime, July 2026) and 1.7 TEU per container (an assumption). In the October 2026 preset it removes about 518 TEU from the Panama payload and raises Panama cost per TEU from about $248 to $264, while fuel and CO₂ tonnes stay fixed.

An independent review found that the first version could fail open when inputs were missing and that its on-screen wording contradicted itself. Both were fixed, and it now makes dependent figures unavailable instead. It was then hidden from the MVP interface. **In this version, the draft-limit and booking-slot presets are shown as context and do not change the results.** Turning the loss model on in the interface is a deliberate next step.

## Data and provenance

All data is local CSV under [`data/`](./data). **No network calls are made at runtime.**

| Data | Source |
|---|---|
| Route distances (10 lanes, 20 rows) | Generated offline with `searoute 1.4.3` from approximate approach points. Each Panama row was checked to pass through Panama and each Suez row through Suez, not around a cape. Status: approximate. |
| Panama Canal draft and booking-slot states, events, transits | Panama Canal Authority advisories and monthly operations data (pancanal.com), plus trade-press reports for the 2023-24 drought. Status: sourced or approximate. |
| Fuel curve and ship | Secondary-source figures for a 10,000 TEU New Panamax ship at 22 knots. Ship size and load factor are assumptions. |
| Waiting and canal fuel rates (12.69 and 18.96 t/day) | Derived from the ICCT 2013-2015 shipping-emissions methodology (auxiliary engine and boiler power, 8,000-12,000 TEU container ships). Approximate. The canal rate is a lower bound. |
| Bunker price ($876.50/t) | Ship & Bunker 20-port VLSFO average, 6 October 2026. A slider, because it is volatile. |
| CO₂ factors | IMO MEPC.346(78), tank-to-wake CO₂ only. |
| Container to TEU | US Bureau of Transportation Statistics definitions. |
| ONI and RONI El Niño series, 2022-2026 | NOAA Climate Prediction Center. |

When a required value is missing, it stays missing: the affected calculation is disabled and the app states what is needed.

## Model limitations

- **Not a forecast.** It computes the consequences of the scenario you choose. Historical replay is not model validation.
- **Fuel cost only.** Tolls, insurance, carrier surcharges and other costs are excluded and disclosed in the app. CO₂ is tank-to-wake, not lifecycle.
- **Presets are context in this version.** Changing the draft limit or booking-slot preset does not change the results. Booking slots are never converted into waiting time; waiting is an explicit input.
- **Waiting and canal fuel rates are size-bin averages** from a 2017 methodology, not figures for the modeled ship. Their effect is small next to sailing fuel (about $1 per TEU at 12 hours of canal transit).
- **Draft-loss assumptions.** The slope and the TEU-per-container factor are assumptions. The loss model assumes the 10,000 TEU ship at 85% load would otherwise load to the full 50 ft reference draft. A ship loaded below that could lose less or nothing.
- **Fuel and CO₂ stay fixed when payload falls,** so cost per TEU is, if anything, overstated.
- **Distances are approximate** shortest paths, with no weather routing, port calls or canal-availability checks. The set of 10 lanes is fixed. To add a lane, generate both route rows with the same tool and keep status `approximate`; do not hand-type distances.
- **Testing scope.** The interface has focused rendered tests (Streamlit `AppTest`), not property tests. It has not been tested with real shippers.

## Built with Kiro

The `.kiro/` folder at the root holds the specs and steering used to build this project.

| Kiro feature | How we used it |
|---|---|
| IDE spec workflow | Spec at `.kiro/specs/canalcast`, written Requirements-First: 20 numbered requirements, a design with 16 numbered correctness properties, and 54 tasks, all complete. Each task cites the requirements it implements. |
| Task execution | Tasks were grouped into dependency waves. Independent tasks ran in parallel through sub-agents; tasks editing the same file ran in sequence. The spec enforced build order: the calculation core and its tests had to pass before any Streamlit code. |
| Steering | `product.md` and `tech.md` in `.kiro/steering/` state the non-negotiables: Python computes every number, missing values stay missing, every input has a status, no shipping-line names. |
| Property-based testing | 18 Hypothesis property tests (at least 100 examples each) drawn from the design's correctness properties, plus worked-example, edge-case and UI rendering tests. 102 tests in total. |
| Agent hooks, MCP, Powers | Not used; the project was built using Kiro’s spec workflow, steering files, and task execution. |

Two examples of the spec doing real work:

- **Draft cargo loss.** Wanting tighter draft to change cargo and cost reversed a documented non-goal. We added Requirement 20, a design addendum and tasks before any code, then built it off by default with a regression test.
- **Waiting time.** A review found that waiting was applied to both routes, so no Panama condition could ever change the winner. The fix started in the requirements ("waiting applies to Panama only") and was verified with a property test.

Honest lesson: the first build passed 61 tests while its default screen presented a sailing-only fuel figure as the voyage total, because our own test had encoded that fallback as intended. An independent review caught it. Spec-driven development gave us traceability and a place to record decisions before code existed; it did not replace review. During development none of the property tests failed, so they guarded invariants but did not find a bug our example tests had missed.

## Project layout

```
app.py                      Streamlit entry point (wires loader -> core -> UI)
requirements.txt            Pinned dependencies
data/                       Read-only CSV inputs (routes, constants, factors, ...)
tests/                      Core test suite (unit + property-based + UI rendering)
.kiro/
    specs/canalcast/        Requirements, design, tasks
    steering/               product.md, tech.md, structure.md
src/canalcast/
    models.py               Typed domain records + provenance
    loader.py               All file I/O with provenance (no network calls)
    calculations.py         Pure calculation functions
    comparison.py           Route comparison and selection
    results.py              Result structures
    explain.py              Deterministic (<=120-word) explanation
    ui/                     Streamlit controls, views, and charts
```

The core modules (`calculations`, `comparison`, `results`, `models`, `explain`) perform no file or network I/O, and a test enforces that by reading their imports. Only `loader.py` reads from `data/`. The UI imports the core; the core never imports Streamlit.

## Deployment

CanalCast v1 runs **locally only** (Requirement 19.3): `.streamlit/config.toml` binds the server to `localhost`. Hosted deployment, including Streamlit Community Cloud, is out of scope for v1 because it creates a public endpoint that needs its own access decision. The Quick start above is the supported way to run and test it.

If `streamlit` is not on your `PATH`, use `python -m streamlit run app.py`. To use a virtual environment: `python -m venv .venv`, then activate it (`.venv\Scripts\Activate.ps1` on Windows PowerShell, `source .venv/bin/activate` on macOS or Linux).

## Verified environments

Tests and the app were run on Python 3.11.9 with the pinned `requirements.txt`. The test suite also passes on Python 3.13.2.
