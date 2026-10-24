# Implementation Plan: CanalCast

## Overview

This plan builds CanalCast bottom-up and core-first. Phases 1â€“4 deliver the pure, tested Calculation_Core (loader, models, calculations, comparison, results, explanation) and MUST be implemented and passing automated tests before any Streamlit_Interface code is written (Requirements 19.1, 19.2). Phase 5 builds the UI on top of the tested core, and Phase 6 captures deployment and pinned dependencies. Every task references the requirement and/or correctness-property numbers it implements. All code lives under the `src/canalcast/` layout defined in the design.

## Tasks

- [x] 1. Typed domain models and provenance (`src/canalcast/models.py`)
  - [x] 1.1 Define `Status` enum and `ProvenancedValue` with value/unit/rationale/status plus optional `retrieved_on`, `method`, `derived_from`, `derivation`
    - Model missing required values as `Optional[...] = None`; never default to zero
    - _Requirements: 2.1, 2.2, 2.4, 1.6_
  - [x] 1.2 Define domain records `RouteOption`, `ODPair`, `EmissionFactor`, `CanalState`, `ContainerUnit`, `Constants`, `OptionalSeries`, `LoadResult`, `Scenario`
    - All `@dataclass(frozen=True)`, fully type-hinted, no I/O methods
    - Keep range/context constants (e.g. `34-36`) as `str`; keep `containers_lost_per_10cm_draft_cut` in context only
    - _Requirements: 5.1, 5.3, 10.1, 10.2_
  - [x] 1.3 Define the `Unavailable` type and `ResultOrUnavailable` alias (reason + missing_inputs + invalid_inputs)
    - Single consistent missing/invalid pattern used across the core; never `0`/`NaN`/`inf`
    - _Requirements: 3.2, 3.3_

- [x] 2. Data_Loader: all file I/O with provenance (`src/canalcast/loader.py`)
  - [x] 2.1 Implement required-data loading (`load_required`) reading routes, constants, canal_states, container_units, emission_factors read-only from `data/`
    - Abort with a file-naming error on a missing/unreadable required file; produce no partial Model_Input data
    - _Requirements: 1.1, 1.2, 1.4, 1.8_
  - [x] 2.2 Implement provenance validation on every Model_Input
    - Reject records missing value/unit/rationale/status; reject status outside {sourced, approximate, assumption, derived}; reject `derived` lacking derived_from/method; preserve original record and report record id + offending field
    - Parse only the computational constant keys to float; keep range/context keys as `str`
    - _Requirements: 1.5, 1.9, 2.3, 2.4, 2.5, 2.6_
  - [x] 2.3 Implement optional-series loading (`load_optional`) and assemble `load_all` into a `LoadResult`
    - Record each optional series available with provenance, or unavailable with reason "not found" / "could not be read"; continue loading the rest
    - Make no network calls anywhere in the loader
    - _Requirements: 1.7, 4.1, 4.2, 4.3_
  - [x]* 2.4 Write loader unit tests
    - Required-file-missing abort, each provenance-rejection branch, optional-series available/not-found/unreadable
    - _Requirements: 1.8, 1.9, 2.3, 2.4, 4.2, 4.3_

- [x] 3. Checkpoint - loader and models
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Pure calculation functions (`src/canalcast/calculations.py`)
  - [x] 4.1 Implement time functions: `sailing_time_hours` and `journey_time_hours`
    - Sailing time = distance/speed when distance > 0 and speed > 0; `Unavailable` naming invalid speed when speed â‰¤ 0; `Unavailable` naming missing distance when absent
    - Journey time = sailing + canal + waiting when all present and â‰¥ 0; `Unavailable` naming the offending duration when any is missing/negative; waiting derived only from its explicit input, never from a booking-slot limit
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_
  - [x] 4.2 Implement fuel functions: `fuel_rate_t_per_day`, `sailing_fuel_t`, and waiting/canal fuel line items
    - Cubic curve `base_fuel * (speed/base_speed)^exponent` using loaded constants only, no alternate ship profile; sailing fuel = rate Ã— sailing days
    - Waiting/canal fuel as distinct line items (never folded into sailing fuel). Zero duration â‡’ zero fuel even when its fuel rate is absent (always resolvable); positive duration + absent rate â‡’ `Unavailable` (unresolved input). Apply the identical rule to both waiting and canal fuel
    - `total_voyage_fuel_t` is reported as "total" only when sailing, waiting, and canal components are all resolved; when any component is `Unavailable`, label the available figure as a sailing-only/partial estimate and mark the total `Unavailable` naming the missing components
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - [x] 4.3 Implement cost and TEU functions: `voyage_fuel_cost_usd`, `loaded_teu`, `fuel_cost_per_teu_usd`
    - Cost = total fuel Ã— bunker price; loaded TEU = capacity Ã— load factor for load factor in [0,1]; cost/TEU when loaded TEU > 0
    - Loaded TEU zero â‡’ cost/TEU `Unavailable(reason="loaded TEU is zero")`, never zero/invented; required-input-missing or load factor out of [0,1] â‡’ affected output `Unavailable`; label output "fuel cost", never "total shipping cost"; record exclusions (tolls, insurance, surcharges)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_
  - [x] 4.4 Implement CO2 function `co2_tank_to_wake_t` and container-to-TEU conversion
    - CO2 = total fuel Ã— emission factor using a fuel type that exactly matches; mismatch or missing factor â‡’ `Unavailable`; label tank-to-wake, not lifecycle
    - Container conversion: exactly 1 TEU per 20ft, 2 TEU per 40ft; unsupported type â‡’ leave TEU missing, disable only that conversion, keep other quantities
    - _Requirements: 5.3, 5.4, 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 5. Result structures (`src/canalcast/results.py`)
  - [x] 5.1 Define `JourneyTimeBreakdown`, `FuelBreakdown`, `OptionResult`, `Selection`, `ComparisonResult`
    - Per-option units map, feasibility, deadline status, infeasible flag/reason, `draft_context_ft` + fixed draft-not-modeled disclosure, exclusions, cost label, input provenance, and fixed disclaimer "Scenario tool â€” not a forecast."
    - _Requirements: 8.6, 8.8, 10.1, 10.3, 10.4, 11.10_

- [x] 6. Route comparison and selection (`src/canalcast/comparison.py`)
  - [x] 6.1 Implement `compute_option` assembling a full `OptionResult` from the calculation functions
    - Independent evaluation: one disabled calculation never suppresses another whose inputs are present; draft carried as context only, never reducing TEU/cost/fuel/CO2; zero loaded TEU â‡’ Infeasible_Result with undefined cost/TEU
    - _Requirements: 3.1, 3.4, 10.1, 10.3, 10.4, 11.9_
  - [x] 6.2 Implement `compare_od_pair` with priority selection, tie handling, and deadline handling
    - Require both Panama and Suez distances > 0 or reject with a naming `comparison_error`; treat Suez availability as explicit assumption and exclude+record when unavailable; select the single non-excluded Feasible_Option minimizing the chosen metric (no weighted composites); exclude zero-TEU option from cost/TEU selection
    - Per-metric tie tolerances defined separately in each metric's own units (journey time in hours, cost/TEU in USD/TEU, CO2 in tonnes) with documented values; tie-break order = metric, then lower journey time, then Panama; record which tie step resolved it. The final Panama tie-break is a deterministic CONVENTION â€” disclose it as such in `Selection`/messaging, not as evidence Panama is superior
    - Deadline-miss: when no option is feasible, make no selection, identify the faster available route by minimum journey time, and state clearly that NEITHER route meets the deadline
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 11.9, 11.10_

- [x] 7. Deterministic explanation (`src/canalcast/explain.py`)
  - [x] 7.1 Implement `explain(result, max_words=120)` deriving every value solely from the current `ComparisonResult`
    - No runtime network call; â‰¤120 words; omit and name missing values (never invent); never imply forecast/prediction
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5_

- [x] 8. Core test suite (`src/tests/`) â€” must pass before any UI code (Req 19.1, 19.2)
  - [x]* 8.1 Write the no-I/O boundary test (`test_no_io_boundary.py`)
    - Parse calculations/comparison/results/models/explain and assert no file-I/O or network imports
    - _Requirements: 1.3, 1.7, 19.4_
  - [x]* 8.2 Write worked-example and edge-case unit tests (`test_calculations.py`)
    - **Property 1: worked examples within 1e-9** â€” sailing time, cubic rate (~95.9 t/day at 18 kn, record 109 check target as context), voyage cost, loaded TEU 8500, cost/TEU, HFO CO2
    - Four waiting-fuel cases (zero/positive duration Ã— rate present/absent) and the identical four canal-fuel cases; partial-fuel case asserts sailing-only/partial label with total `Unavailable` naming missing components
    - **Validates: Requirements 18.1, 7.4, 7.5**
  - [x]* 8.3 Write calculation property tests (`test_calculations.py`)
    - **Property 2: fuel and CO2 non-negative for valid inputs** â€” _Requirements 18.2_
    - **Property 3: sailing fuel monotonic in distance** â€” _Requirements 18.3_
    - **Property 4: higher speed strictly shortens sailing time** â€” _Requirements 18.4_
    - **Property 5: higher speed strictly increases sailing fuel** â€” _Requirements 18.5_
    - **Property 9: invalid speed yields Unavailable, not a number** â€” _Requirements 6.7, 18.7_
    - **Property 10: missing distance disables journey time without substitution** â€” _Requirements 6.6, 18.8_
    - **Property 11: zero loaded TEU â‡’ undefined per-TEU cost, excluded from cost selection** â€” _Requirements 8.4, 11.9, 18.9_
    - **Property 12: container-to-TEU conversion exact and type-guarded** â€” _Requirements 5.3, 5.4_
    - **Property 15: CO2 requires an exactly matching fuel type** â€” _Requirements 9.2, 9.3, 9.4_
    - Each property is one Hypothesis test, â‰¥100 iterations, tagged `# Feature: canalcast, Property N: ...`
  - [x]* 8.4 Write comparison and selection property tests (`test_comparison.py`)
    - **Property 6: a feasible option is never passed over for an infeasible one** â€” _Requirements 11.4, 18.6_
    - **Property 7: selection minimizes the chosen priority metric** â€” _Requirements 11.4, 11.6_
    - **Property 8: tie handling is deterministic (per-metric tolerance, Panama convention)** â€” _Requirements 11.7, 11.8_
    - **Property 13: independent evaluation of calculations** â€” _Requirements 3.4_
    - **Property 14: optional-series absence does not block the comparison** â€” _Requirements 4.4, 4.5_
    - Both-miss deadline case: assert faster route identified AND "neither meets the deadline" statement present, no selection made â€” _Requirements 11.5_

- [x] 9. Checkpoint - core complete and gated
  - Ensure all core tests pass. The UI phase (Tasks 10+) MUST NOT begin until this checkpoint is green (Requirements 19.1, 19.2). Ask the user if questions arise.

- [x] 10. Streamlit presets and controls (`src/canalcast/ui/controls.py`)
  - [x] 10.1 Implement presets and custom scenario
    - Normal-reference preset â‡’ draft 50.0 ft, 36 slots/day; October 2026 snapshot â‡’ draft 49.0 ft, 33 slots/day; custom â‡’ user sets draft and whole booking-slot count directly; missing required custom input disables the dependent calc and states in plain language what is needed
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_
  - [x] 10.2 Implement scenario input controls with range enforcement
    - Controls for route, speed (>0), load factor ([0,1]), bunker price (>0), waiting duration (â‰¥0 days), deadline (>0 days), Selection_Priority (exactly the three values), Suez availability (available/unavailable); route selection restricted to OD_Pairs with both distances; in-range change recomputes and replaces results; out-of-range input rejected, last valid scenario retained, offending input indicated
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

- [x] 11. Streamlit results, disclosure, and charts (`src/canalcast/ui/views.py`, `src/canalcast/ui/charts.py`)
  - [x] 11.1 Implement side-by-side results view and disclosure panel (`views.py`)
    - Panama and Suez in two adjacent columns (Panama first), each with exactly the five metrics + units; unavailable calcs named with no substitution; infeasible options show explanation + undefined cost/TEU; display exact text "Scenario tool â€” not a forecast."
    - Disclosure panel: per-input rationale/status/data date; excluded cost items (tolls, insurance, others) and fuel-combustion-CO2-only (not lifecycle); no shipping-line name/logo; carrier examples labeled Carrier A/B/C; render the Panama tie-break convention disclosure; accessible palette (â‰¥4.5:1 normal, â‰¥3:1 large text)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 15.1, 15.2, 15.3, 15.4, 15.5, 17.6_
  - [x] 11.2 Implement ONI/RONI historical charts (`charts.py`)
    - ONI and RONI as two visually distinct labeled series, never combined/averaged/summed; unavailable series omitted with in-chart note naming it; all-unavailable â‡’ suppress chart with note and keep app running; no text implying an ENSO index predicts/forecasts/causes canal restrictions; label each chart as historical observations and state historical replay is not model validation
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

- [x] 12. Wire the Streamlit app (`app.py`)
  - [x] 12.1 Compose loader â†’ core â†’ explanation â†’ UI in `app.py`
    - Load data, build scenario from controls/presets, call `compare_od_pair`, render views/charts and the â‰¤120-word explanation; UI imports the core, core never imports Streamlit
    - _Requirements: 17.1, 19.1, 19.2_

- [x] 13. Deployment artifacts and instructions
  - [x] 13.1 Create a pinned `requirements.txt` and document local run + Streamlit deploy in the README
    - Every dependency pinned to an exact version (`==`), no open ranges; local run `pip install -r requirements.txt` then `streamlit run app.py`; entry point `app.py`; no public endpoint beyond localhost
    - _Requirements: 19.3, 19.5, 19.6, 19.7, 19.8_

- [x] 14. Version 2 — optional draft-based cargo-loss modeling (Requirement 20)
  - [x] 14.1 Extend `Scenario` and add a `DraftLoss` result type
    - Add `draft_loss_enabled: bool = False`, `containers_lost_per_10cm: float | None = None`, `avg_teu_per_container: float = 1.7` to `Scenario` (all default to v1 behavior); add a frozen `DraftLoss(shortfall_ft, containers_lost, teu_lost)` type
    - _Requirements: 20.1, 20.5, 20.6_
  - [x] 14.2 Implement the pure `draft_cargo_loss` function (`calculations.py`)
    - Panama-only; shortfall = reference_draft_ft - canal_state max_draft_ft clamped at 0; ten-cm units via 1 ft = 30.48 cm; containers_lost = units x estimate; teu_lost = containers_lost x avg_teu_per_container; disabled/off/Suez ⇒ zero loss; missing required input while enabled ⇒ `Unavailable` naming it (never substituted)
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.10_
  - [x] 14.3 Integrate draft loss into `compute_option` (`comparison.py`) and `OptionResult`
    - When enabled, adjusted loaded TEU = max(0, base - teu_lost); zero ⇒ Infeasible_Result reusing the Req 11.9 path, never negative; fuel/cubic curve/journey time/CO2 factor untouched; add labeled `draft_shortfall_ft`/`containers_lost`/`teu_lost` + analyst-estimate/assumption disclosure to the result (default to no-loss so v1 construction is unaffected)
    - _Requirements: 20.7, 20.8, 20.9, 20.10_
  - [x]* 14.4 Tests: default-off regression + draft-loss worked example and properties
    - Default-off ⇒ all existing metrics unchanged (guards the 51 v1 tests); worked example 50→49 ft ⇒ ~518.16 TEU lost, loaded 8500→~7981.84, cost/TEU rises (1e-9); properties: shortfall clamped at zero for draft ≥ reference, Suez never reduced, TEU never negative (Infeasible when it would be), enabling never changes CO2 tonnes or journey time
    - _Requirements: 20.2, 20.3, 20.7, 20.8, 20.10_
  - [x] 14.5 UI: draft-loss toggle, slider, and disclosure (`controls.py`, `views.py`)
    - Toggle defaulting OFF; when on, containers-lost-per-10cm slider seeded from the loaded estimate and an avg-TEU-per-container input; display Draft_Shortfall_Ft, Containers_Lost, TEU_Lost and the analyst-estimate/assumption disclosures alongside the Panama option; panel unchanged when off
    - _Requirements: 20.11_

## Notes

- Tasks marked with `*` are optional test sub-tasks and are not auto-implemented by the code-generation agent; core correctness still depends on running them.
- Phases 1â€“4 (Tasks 1â€“9) deliver the pure, tested Calculation_Core and are gated by the checkpoint in Task 9 before the UI phase (Tasks 10â€“12) begins.
- Each property test is a single Hypothesis test of â‰¥100 iterations tagged `# Feature: canalcast, Property N: ...`.
- The Panama tie-break is a disclosed deterministic convention, not a claim of route superiority.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["4.1", "4.2", "4.3", "4.4", "5.1"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2", "7.1"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3", "8.4"] },
    { "id": 8, "tasks": ["10.1", "10.2", "11.2"] },
    { "id": 9, "tasks": ["11.1"] },
    { "id": 10, "tasks": ["12.1"] },
    { "id": 11, "tasks": ["13.1"] }
  ]
}
```
