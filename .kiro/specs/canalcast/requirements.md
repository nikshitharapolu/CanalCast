# Requirements Document

## Introduction

CanalCast is a scenario simulator that compares a Panama Canal shipping route against a Suez Canal shipping route for the same origin-destination pair, under Panama Canal operating conditions that the user selects. CanalCast is explicitly not a forecast: it computes the consequences of user-chosen scenario inputs and describes the resulting numbers, it does not predict future canal restrictions or shipping behavior.

Every displayed number is produced by typed Python calculation functions. The system reports, for each route option, total journey time, voyage fuel cost, fuel cost per loaded TEU, and fuel-combustion (tank-to-wake) carbon dioxide, together with deadline feasibility. The system deliberately excludes tolls, insurance, carrier surcharges, lifecycle emissions, and draft-related cargo-loss effects, and discloses these exclusions.

The requirements are organized so that the calculation core is specified, built, and tested before the Streamlit interface. Requirements 1 through 11 define the data loading, provenance, and calculation core. Requirements 12 through 17 define the Streamlit interface and are a distinct, later phase. Requirements 18 and 19 define verification and non-goals.

This document uses the following status vocabulary for model inputs, drawn directly from the project data: **sourced**, **approximate**, **assumption**, and **derived**.

## Glossary

- **CanalCast**: The overall scenario simulator comprising the Data_Loader, the Calculation_Core, and the Streamlit_Interface.
- **Data_Loader**: The module responsible for reading CSV files from the local `data/` folder, validating them, and exposing typed records with provenance. The Data_Loader performs all file input and output. No other module performs file input or output.
- **Calculation_Core**: The set of pure, typed Python functions in `src/` that compute journey time, fuel, cost, carbon dioxide, and route comparison. The Calculation_Core performs no file input or output and no network input or output.
- **Streamlit_Interface**: The browser-based user interface built with Streamlit that presents controls and results and that invokes the Calculation_Core.
- **Route_Option**: One row describing a single canal choice for an origin-destination pair, identified by route_id and option, where option is either `panama` or `suez`.
- **OD_Pair**: An origin-destination pair (for example, Shanghai to New York) that may have a Panama Route_Option and a Suez Route_Option.
- **Scenario**: The complete set of user-selected and data-derived inputs for one comparison run, including draft limit, booking-slot count, waiting duration, speed, load factor, bunker price, deadline, Suez availability, and selection priority.
- **Model_Input**: Any value consumed by the Calculation_Core. Every Model_Input carries a value, a unit, a source or assumption rationale, and a status.
- **Provenance**: The combination of unit, source or assumption rationale, status, and (where present) retrieval date and method attached to a Model_Input.
- **Required_Input**: A Model_Input without which a specific calculation cannot be performed.
- **Optional_Historical_Series**: Historical context data (canal events, actual transits, ONI, RONI, ENSO context, surcharges, Gatun levels) that is not required for the Calculation_Core to run.
- **Loaded_TEU**: The number of twenty-foot equivalent units treated as loaded for a voyage, computed in version 1 as ship capacity in TEU multiplied by load factor.
- **TEU**: Twenty-foot equivalent unit. A twenty-foot container is one TEU; a forty-foot container is two TEU.
- **Actual_Transit**: An observed, historically recorded canal passage count.
- **Booking_Slot_Limit**: The number of daily transit booking slots made available under a canal state. A Booking_Slot_Limit is not an Actual_Transit.
- **Canal_State**: A named Panama Canal operating condition consisting of a maximum draft in feet and a daily booking-slot count, drawn from `canal_states.csv`.
- **Sailing_Time**: Time spent sailing, computed as distance in nautical miles divided by speed in knots.
- **Canal_Duration**: Time attributed to transiting the canal, supplied as an explicit scenario input separate from Sailing_Time.
- **Waiting_Duration**: Time spent waiting for canal access, supplied as an explicit scenario input separate from Sailing_Time and Canal_Duration.
- **Journey_Time**: Sailing_Time plus Canal_Duration plus Waiting_Duration for a Route_Option.
- **Cubic_Fuel_Curve**: The single speed-to-fuel relationship fuel_t_per_day = base_fuel_t_per_day multiplied by (speed_kn divided by base_speed_kn) raised to the speed_exponent, with speed_exponent equal to 3.
- **Sailing_Fuel**: Fuel consumed while sailing, derived from the Cubic_Fuel_Curve and Sailing_Time.
- **Emission_Factor**: Tank-to-wake carbon dioxide produced per tonne of fuel burned, in tonnes of carbon dioxide per tonne of fuel, for a specific fuel type.
- **Feasible_Option**: A Route_Option whose Journey_Time is less than or equal to the user-selected deadline.
- **Infeasible_Result**: A result for a Route_Option whose Loaded_TEU is zero, carrying an explanation and an undefined fuel cost per TEU.
- **Selection_Priority**: The user-selected basis for choosing among Feasible_Options: fastest Journey_Time, lowest fuel cost per TEU, or lowest carbon dioxide.

## Requirements

### Requirement 1: Load local data with provenance

**User Story:** As a developer, I want all model data loaded from local CSV files with their provenance intact, so that every number shown to a user can be traced to a source or a stated assumption.

#### Acceptance Criteria

1. THE Data_Loader SHALL read route, constant, canal-state, container-unit, and emission-factor data from CSV files in the local `data` folder.
2. THE Data_Loader SHALL perform all file input and output for CanalCast.
3. THE Calculation_Core SHALL perform no file input or output.
4. THE Data_Loader SHALL open the source CSV files in read-only mode and SHALL perform no write operations to those files.
5. WHEN the Data_Loader reads a Model_Input, THE Data_Loader SHALL retain that input's unit, source or assumption rationale, and status.
6. WHERE a Model_Input record includes a retrieval date or method, THE Data_Loader SHALL retain the retrieval date and method with that input.
7. THE CanalCast system SHALL make no network calls at runtime.
8. IF a required CSV file in the local `data` folder is missing or cannot be read, THEN THE Data_Loader SHALL stop loading and SHALL return an error indicating which file could not be read, without producing partial Model_Input data.
9. IF a Model_Input record is missing its unit, source or assumption rationale, or status, THEN THE Data_Loader SHALL reject that record and SHALL return an error indicating which required provenance field is absent.

### Requirement 2: Represent every model input with complete provenance

**User Story:** As a user, I want every input to carry a value, unit, source or rationale, and status, so that I can judge how much to trust each result.

#### Acceptance Criteria

1. THE Data_Loader SHALL represent each Model_Input with a value, a unit, a source or assumption rationale, and a status.
2. THE Data_Loader SHALL restrict each Model_Input status to exactly one of the values sourced, approximate, assumption, or derived.
3. IF a Model_Input record carries a status value that is not one of sourced, approximate, assumption, or derived, THEN THE Data_Loader SHALL reject that record, preserve the original record unchanged, and report the record identifier and the unrecognized status value.
4. WHERE a Model_Input has the status derived, THE Data_Loader SHALL record a non-empty list of the input identifiers used and a non-empty description of the method used to derive that input.
5. IF a Model_Input record is missing its status field, THEN THE Data_Loader SHALL reject that record, preserve the original record unchanged, and report the record identifier and an indication that the status field is missing.
6. IF a Model_Input record is missing its value, its unit, or its source or assumption rationale, THEN THE Data_Loader SHALL reject that record, preserve the original record unchanged, and report the record identifier and an indication of which mandatory field is missing.

### Requirement 3: Handle missing required inputs without invented values

**User Story:** As a user, I want missing required values to stay missing rather than be replaced with guesses or zero, so that I am never shown a fabricated result.

#### Acceptance Criteria

1. IF one or more Required_Inputs for a calculation are missing, THEN THE Calculation_Core SHALL disable that calculation and return an explanation that names each missing Required_Input.
2. WHILE a calculation is disabled because a Required_Input is missing, THE Calculation_Core SHALL return no numeric value for that calculation and SHALL mark that calculation's result as unavailable.
3. IF a Required_Input for a calculation is missing, THEN THE Calculation_Core SHALL leave the missing value missing and SHALL NOT substitute a default, a zero, or any other invented number for that Required_Input or for the disabled calculation's result.
4. WHEN one calculation is disabled because of a missing Required_Input, THE Calculation_Core SHALL evaluate every other calculation independently and SHALL compute each other calculation whose Required_Inputs are all present.

### Requirement 4: Load optional historical series without blocking

**User Story:** As a user, I want the simulator to keep running even when optional historical data is absent, so that missing context never breaks the core comparison.

#### Acceptance Criteria

1. WHERE an Optional_Historical_Series is present and readable, THE Data_Loader SHALL load that series, retain its Provenance, and record that series as available.
2. IF an Optional_Historical_Series is absent, THEN THE Data_Loader SHALL record that series as unavailable with a reason indicating the series was not found, and THE Data_Loader SHALL continue loading the remaining Optional_Historical_Series.
3. IF an Optional_Historical_Series is present but unreadable, THEN THE Data_Loader SHALL record that series as unavailable with a reason indicating the series could not be read, and THE Data_Loader SHALL continue loading the remaining Optional_Historical_Series.
4. THE Calculation_Core SHALL compute Journey_Time, Sailing_Fuel, voyage fuel cost, fuel cost per loaded TEU, and carbon dioxide without requiring any Optional_Historical_Series.
5. WHILE every Optional_Historical_Series is recorded as unavailable, THE Calculation_Core SHALL still produce a complete route comparison for an OD_Pair whose Required_Inputs are present.

### Requirement 5: Distinguish transits, slots, containers, TEU, and scenarios from observations

**User Story:** As a user, I want actual transits, booking-slot limits, containers, TEU, and historical observations kept distinct from modeled scenarios, so that I do not mistake one quantity for another.

#### Acceptance Criteria

1. WHEN CanalCast displays an Actual_Transit value or a Booking_Slot_Limit value, THE CanalCast system SHALL label the Actual_Transit value as an actual transit, SHALL label the Booking_Slot_Limit value as a booking-slot limit, and SHALL NOT present one as interchangeable with the other.
2. THE CanalCast system SHALL represent a container count and a TEU count as separate labeled quantities and SHALL NOT sum them together, substitute one for the other, or display one in place of the other.
3. WHERE a container-to-TEU conversion is explicitly required, THE Calculation_Core SHALL convert using one TEU per twenty-foot container and two TEU per forty-foot container.
4. IF a container record has a container type that is not twenty-foot or forty-foot, THEN THE Calculation_Core SHALL leave the TEU value missing, disable only the calculation that depends on that conversion, indicate the unsupported container type, and continue to display every other correctly labeled quantity normally.
5. WHEN CanalCast displays a historical observation or a modeled scenario result, THE CanalCast system SHALL label the historical observation as a historical observation, SHALL label the modeled scenario result as a modeled scenario result, and SHALL NOT label a modeled scenario result as a historical observation.

### Requirement 6: Compute journey time from separate sailing, canal, and waiting durations

**User Story:** As a user, I want journey time built from separately identified sailing, canal, and waiting durations, so that waiting is never silently inferred from booking slots.

#### Acceptance Criteria

1. WHEN a Route_Option has a distance greater than zero nautical miles and a speed greater than zero knots, THE Calculation_Core SHALL compute Sailing_Time in hours as the distance in nautical miles divided by the speed in knots.
2. THE Calculation_Core SHALL accept Canal_Duration in hours and Waiting_Duration in hours as explicit scenario inputs that are separate from each other and from Sailing_Time.
3. THE Calculation_Core SHALL derive Waiting_Duration only from its explicit Waiting_Duration scenario input.
4. THE Calculation_Core SHALL NOT use a Booking_Slot_Limit as a source for Waiting_Duration.
5. WHEN Sailing_Time, Canal_Duration, and Waiting_Duration are all present and each is greater than or equal to zero hours, THE Calculation_Core SHALL compute Journey_Time as their sum in hours.
6. IF a Route_Option distance is missing, THEN THE Calculation_Core SHALL disable the Journey_Time calculation for that Route_Option, leave the distance missing without substituting a value, and report the missing distance.
7. IF a speed input is less than or equal to zero knots, THEN THE Calculation_Core SHALL reject the Sailing_Time calculation, leave Sailing_Time missing without substituting a value, and report the invalid speed.
8. IF Canal_Duration or Waiting_Duration is missing or less than zero hours, THEN THE Calculation_Core SHALL disable the Journey_Time calculation and report which duration is missing or invalid.

### Requirement 7: Apply one consistent cubic speed-fuel curve

**User Story:** As a user, I want one documented speed-fuel relationship applied consistently, so that fuel figures are reproducible and traceable to the constants.

#### Acceptance Criteria

1. THE Calculation_Core SHALL compute daily fuel consumption using the Cubic_Fuel_Curve, where fuel_t_per_day equals base_fuel_t_per_day multiplied by the ratio of the configured sailing speed in knots to base_speed_kn raised to the speed_exponent.
2. THE Calculation_Core SHALL take base_fuel_t_per_day, base_speed_kn, and speed_exponent from the loaded constants, using the loaded value for each without substitution or default.
3. THE Calculation_Core SHALL compute Sailing_Fuel as the Cubic_Fuel_Curve daily rate multiplied by the Sailing_Time expressed in days.
4. THE Calculation_Core SHALL report waiting fuel and canal-operation fuel as line items distinct from Sailing_Fuel, each with its own value and without summing them into Sailing_Fuel.
5. IF a fuel rate required for waiting fuel or canal-operation fuel is missing, THEN THE Calculation_Core SHALL leave that rate as an unresolved input, disable the fuel figure that depends on the missing rate, and report which rate is needed while still reporting any fuel figures whose inputs are fully resolved.
6. THE Calculation_Core SHALL compute fuel figures using only the loaded ship constants and SHALL NOT combine them with any alternative ship profile.

### Requirement 8: Compute voyage fuel cost and fuel cost per loaded TEU

**User Story:** As a user, I want fuel cost per voyage and per loaded TEU, so that I can compare routes on fuel economics without mistaking the figure for total shipping cost.

#### Acceptance Criteria

1. WHEN total voyage fuel in tonnes and the bunker price are present, THE Calculation_Core SHALL compute voyage fuel cost in United States dollars as total voyage fuel in tonnes multiplied by the bunker price in United States dollars per tonne.
2. WHEN ship capacity in TEU and load factor are present and load factor is from zero to one inclusive, THE Calculation_Core SHALL compute Loaded_TEU as ship capacity in TEU multiplied by load factor.
3. WHEN Loaded_TEU is greater than zero, THE Calculation_Core SHALL compute fuel cost per loaded TEU in United States dollars per TEU as voyage fuel cost divided by Loaded_TEU.
4. IF Loaded_TEU is zero, THEN THE Calculation_Core SHALL leave fuel cost per loaded TEU missing, SHALL NOT substitute a zero or invented value, and SHALL record the reason that Loaded_TEU is zero.
5. IF a Required_Input for voyage fuel cost or fuel cost per loaded TEU is missing or load factor is outside zero to one inclusive, THEN THE Calculation_Core SHALL leave the affected output missing and record which input is missing or invalid.
6. THE Calculation_Core SHALL exclude tolls, insurance, carrier surcharges, and other unmodeled costs from voyage fuel cost and SHALL record these exclusions in the result.
7. THE Calculation_Core SHALL NOT add carrier surcharges to the modeled fuel cost.
8. THE Calculation_Core SHALL label the fuel cost output as fuel cost and SHALL NOT label it as total shipping cost.

### Requirement 9: Compute tank-to-wake carbon dioxide with agreeing fuel type and factor

**User Story:** As a user, I want fuel-combustion carbon dioxide computed from a factor matching the fuel type, so that emissions are consistent and limited to tank-to-wake scope.

#### Acceptance Criteria

1. WHEN total voyage fuel in tonnes and a matching Emission_Factor are present, THE Calculation_Core SHALL compute carbon dioxide in tonnes as total voyage fuel in tonnes multiplied by the Emission_Factor in tonnes of carbon dioxide per tonne of fuel.
2. THE Calculation_Core SHALL use an Emission_Factor whose fuel type is an exact match of the fuel type used for the voyage fuel calculation.
3. IF the selected fuel type and the Emission_Factor fuel type do not match, THEN THE Calculation_Core SHALL disable the carbon dioxide calculation, leave the carbon dioxide result missing, and report the fuel-type mismatch.
4. IF no Emission_Factor record exists for the selected fuel type, THEN THE Calculation_Core SHALL disable the carbon dioxide calculation, leave the carbon dioxide result missing, and report that the Emission_Factor is missing.
5. THE Calculation_Core SHALL report the carbon dioxide result as tank-to-wake fuel-combustion carbon dioxide and SHALL NOT report it as lifecycle emissions.

### Requirement 10: Treat draft restrictions as context without modeling cargo loss

**User Story:** As a user, I want draft restrictions shown as scenario context in version 1, so that I understand conditions without seeing unsupported cargo-loss numbers.

#### Acceptance Criteria

1. WHEN a Scenario includes a Canal_State, THE Calculation_Core SHALL include that Canal_State maximum draft in feet in the result as scenario context, labeled as context rather than as a calculation input.
2. THE Calculation_Core SHALL compute Loaded_TEU in version 1 as ship capacity in TEU multiplied by load factor, and SHALL NOT use the Canal_State maximum draft as a factor in the Loaded_TEU computation.
3. THE Calculation_Core SHALL NOT reduce Loaded_TEU, voyage fuel cost, fuel cost per loaded TEU, or carbon dioxide on the basis of the Canal_State maximum draft in version 1.
4. WHEN a draft restriction is present in a Scenario, THE Calculation_Core SHALL record in the result a disclosure that cargo-capacity effects of draft are not modeled in version 1.

### Requirement 11: Compare Panama and Suez options and select by priority

**User Story:** As a user, I want a direct comparison between the Panama and Suez options with a clear selection by my chosen priority, so that I can see which route best meets my goal and deadline.

#### Acceptance Criteria

1. IF an OD_Pair does not have both a Panama distance greater than zero nautical miles and a Suez distance greater than zero nautical miles, THEN THE Calculation_Core SHALL reject the comparison for that OD_Pair and report which distance is missing or invalid.
2. THE Calculation_Core SHALL treat Suez availability as an explicit scenario assumption.
3. WHERE Suez is marked unavailable in the Scenario, THE Calculation_Core SHALL exclude the Suez Route_Option from selection and record that exclusion.
4. WHEN at least one non-excluded Route_Option is a Feasible_Option, THE Calculation_Core SHALL select the single non-excluded Feasible_Option that minimizes the user-selected Selection_Priority metric, where that metric is Journey_Time in hours for fastest, fuel cost per loaded TEU in United States dollars per TEU for lowest fuel cost per TEU, or carbon dioxide in tonnes for lowest carbon dioxide.
5. IF no Route_Option is a Feasible_Option, THEN THE Calculation_Core SHALL identify the non-excluded option with the minimum Journey_Time as the closest option, make no selection, and state that no option meets the deadline.
6. THE Calculation_Core SHALL select by direct comparison of the single Selection_Priority metric and SHALL NOT use weighted composite scores.
7. WHEN two Feasible_Options have Selection_Priority metric values equal within 0.001 of the metric unit, THE Calculation_Core SHALL select the option with the lower Journey_Time, and WHEN their Journey_Time values are also equal within 0.001 hours, THE Calculation_Core SHALL select the Panama Route_Option.
8. THE Calculation_Core SHALL record which tie-handling step resolved the selection when a tie occurs.
9. IF Loaded_TEU is zero for a Route_Option, THEN THE Calculation_Core SHALL return an Infeasible_Result for that Route_Option with an explanation and an undefined fuel cost per TEU, and SHALL exclude that Route_Option from selection when the active Selection_Priority is lowest fuel cost per TEU.
10. THE Calculation_Core SHALL include in each comparison result the per-option units, feasibility, exclusions, and input Provenance.

### Requirement 12: Provide scenario presets and custom scenarios in the interface

**User Story:** As a user, I want preset and custom scenarios in the interface, so that I can start from a reference condition or build my own.

#### Acceptance Criteria

1. THE Streamlit_Interface SHALL present a normal-reference preset as a selectable option that uses the normal_reference Canal_State.
2. WHEN a user selects the normal-reference preset, THE Streamlit_Interface SHALL populate the Scenario with the normal_reference maximum draft of 50.0 feet and booking-slot count of 36 slots per day.
3. THE Streamlit_Interface SHALL present an October 2026 snapshot preset as a selectable option that uses the current_oct2026 Canal_State.
4. WHEN a user selects the October 2026 snapshot preset, THE Streamlit_Interface SHALL populate the Scenario with the current_oct2026 maximum draft of 49.0 feet and booking-slot count of 33 slots per day.
5. THE Streamlit_Interface SHALL present a custom scenario as a selectable option in which the user sets the draft limit in feet and the booking-slot count in whole slots per day directly, together with the other scenario inputs.
6. IF a required custom scenario input is missing, THEN THE Streamlit_Interface SHALL leave that input missing, disable the dependent calculation, and state in plain language what value is needed.

### Requirement 13: Provide scenario input controls

**User Story:** As a user, I want controls for the main scenario inputs, so that I can explore how conditions change the comparison.

#### Acceptance Criteria

1. THE Streamlit_Interface SHALL provide controls for route selection, speed in knots, load factor, bunker price in United States dollars per tonne, Waiting_Duration in days, deadline in days, and Selection_Priority.
2. THE Streamlit_Interface SHALL restrict each numeric control to the range defined for its Model_Input in the loaded constants: speed greater than zero knots, load factor from zero to one inclusive, bunker price greater than zero, Waiting_Duration greater than or equal to zero days, and deadline greater than zero days.
3. THE Streamlit_Interface SHALL restrict the Selection_Priority control to exactly the values fastest Journey_Time, lowest fuel cost per TEU, and lowest carbon dioxide.
4. THE Streamlit_Interface SHALL restrict route selection to the OD_Pairs that have both a Panama Route_Option distance and a Suez Route_Option distance.
5. THE Streamlit_Interface SHALL provide a Suez-availability control with the two values available and unavailable as an explicit scenario assumption.
6. WHEN a user changes any scenario input control to a value within its permitted range, THE Streamlit_Interface SHALL recompute every affected result from the Calculation_Core using the updated Scenario and SHALL replace the previously displayed results with the recomputed results.
7. IF a user enters a numeric scenario input outside its permitted range, THEN THE Streamlit_Interface SHALL reject that value, retain the last valid Scenario, and display an indication identifying the out-of-range input.

### Requirement 14: Present Panama and Suez results side by side

**User Story:** As a user, I want Panama and Suez results shown side by side, so that I can compare the two options at a glance.

#### Acceptance Criteria

1. THE Streamlit_Interface SHALL display the Panama option and the Suez option in two adjacent columns in a single viewport row, with the Panama option before the Suez option.
2. THE Streamlit_Interface SHALL display for each option exactly these five metrics, each with its unit: Journey_Time, voyage fuel cost, fuel cost per loaded TEU, fuel-combustion carbon dioxide, and deadline status.
3. WHEN a calculation is disabled because of a missing Required_Input, THE Streamlit_Interface SHALL show that the value is unavailable, name each missing Required_Input, and SHALL NOT substitute a zero or invented value.
4. WHEN a Route_Option is an Infeasible_Result, THE Streamlit_Interface SHALL show the option as infeasible with its explanation and SHALL show the fuel cost per loaded TEU as undefined.
5. WHEN the results view is displayed, THE Streamlit_Interface SHALL display the exact text "Scenario tool — not a forecast." in the results view.

### Requirement 15: Disclose assumptions, sources, dates, missing inputs, and exclusions

**User Story:** As a user, I want assumptions, sources, data dates, missing inputs, and exclusions stated in plain language, so that I understand the limits of each result.

#### Acceptance Criteria

1. WHEN results are displayed, THE Streamlit_Interface SHALL display, for each input behind those results, the input's source or assumption rationale, its status as one of sourced, approximate, assumption, or derived, and the data date associated with that input.
2. WHEN results are displayed, THE Streamlit_Interface SHALL display the list of excluded cost items, stating at minimum that tolls, insurance, and other unmodeled costs are excluded, and SHALL state that the displayed emissions represent fuel-combustion carbon dioxide only and exclude lifecycle emissions.
3. WHEN a Required_Input is missing, THE Streamlit_Interface SHALL list that missing input by name, disable the calculation that depends on it, and state in plain language what value is needed to enable that calculation.
4. THE Streamlit_Interface SHALL NOT display any shipping-line name or logo.
5. WHERE a carrier example is shown, THE Streamlit_Interface SHALL label it as Carrier A, Carrier B, or Carrier C.

### Requirement 16: Present historical context without claiming predictive power

**User Story:** As a user, I want historical context charts that keep distinct indices separate and avoid predictive claims, so that I do not over-interpret the history.

#### Acceptance Criteria

1. WHEN a historical chart that includes both the ONI series and the RONI series is rendered, THE Streamlit_Interface SHALL display the ONI series and the RONI series as two visually distinct series, each with its own label identifying it as ONI or RONI, and SHALL NOT combine, average, or sum the two series into a single plotted series.
2. IF an Optional_Historical_Series is unavailable, THEN THE Streamlit_Interface SHALL omit that series from the chart and SHALL display a visible note, within the same chart view, indicating which named series is unavailable, and SHALL continue to render all available series without error.
3. IF all series required for a historical chart are unavailable, THEN THE Streamlit_Interface SHALL suppress the chart and SHALL display a visible note indicating that no historical data is available for that chart, and SHALL allow the rest of the simulator to continue running.
4. THE Streamlit_Interface SHALL NOT display any text, caption, label, or annotation stating or implying that an ENSO index, including ONI or RONI, predicts, forecasts, or causes Panama Canal restrictions.
5. WHEN a historical chart is rendered, THE Streamlit_Interface SHALL display a visible label identifying the chart as historical observations and SHALL display a visible statement that historical replay does not constitute model validation, with both elements present in the same chart view.

### Requirement 17: Generate deterministic explanations of the current result

**User Story:** As a user, I want a short explanation generated from the current result, so that I can read a plain-language summary that matches the numbers on screen.

#### Acceptance Criteria

1. WHEN results are computed, THE Streamlit_Interface SHALL generate a text explanation of no more than 120 words that describes the current calculated results.
2. WHEN generating the explanation, THE Streamlit_Interface SHALL derive every stated value solely from the current calculated result, using only local data and performing no runtime network call.
3. IF the explanation generation attempts any runtime network call, THEN THE Streamlit_Interface SHALL omit that call and generate the explanation from the locally available current result.
4. WHEN generating the explanation, THE Streamlit_Interface SHALL describe only the current calculated results and SHALL NOT state or imply that the results are a forecast or prediction.
5. IF one or more values required for the explanation are missing, THEN THE Streamlit_Interface SHALL omit those values from the explanation, SHALL NOT substitute invented or zero values, and SHALL indicate which values are unavailable.
6. WHILE displaying results and explanations, THE Streamlit_Interface SHALL render all text using foreground-to-background color contrast ratios of at least 4.5:1 for normal text and at least 3:1 for large text.

### Requirement 18: Verifiability of the calculation core

**User Story:** As a developer, I want the calculation core to satisfy explicit, testable properties, so that correctness can be checked with pytest and Hypothesis.

#### Acceptance Criteria

1. WHEN a known unit conversion or worked calculation example is evaluated, THE Calculation_Core SHALL produce the expected result within a relative tolerance of 1e-9.
2. WHEN all Required_Inputs are present, finite, and within their documented valid ranges, THE Calculation_Core SHALL produce a fuel value and a carbon dioxide value that are each greater than or equal to zero.
3. WHILE speed and ship configuration and all other Required_Inputs are fixed, THE Calculation_Core SHALL produce Sailing_Fuel for a larger distance that is greater than or equal to the Sailing_Fuel for a smaller distance.
4. WHILE distance and ship configuration and all other Required_Inputs are fixed, THE Calculation_Core SHALL produce a strictly shorter Sailing_Time at a higher valid speed.
5. WHILE distance and ship configuration and all other Required_Inputs are fixed, THE Calculation_Core SHALL produce a strictly larger Sailing_Fuel at a higher valid speed under the Cubic_Fuel_Curve.
6. WHEN at least one Feasible_Option exists, THE Calculation_Core SHALL select a Feasible_Option and SHALL NOT select a Route_Option that misses the deadline over a Feasible_Option.
7. IF a speed is invalid, THEN THE Calculation_Core SHALL handle the condition explicitly as specified in Requirement 6.
8. IF a distance is missing, THEN THE Calculation_Core SHALL handle the condition explicitly as specified in Requirements 6 and 11.
9. IF payload is zero, THEN THE Calculation_Core SHALL handle the condition explicitly as specified in Requirements 8 and 11.

### Requirement 19: Project boundaries and non-goals

**User Story:** As a developer, I want the version 1 boundaries fixed, so that out-of-scope features are not built prematurely.

#### Acceptance Criteria

1. THE CanalCast system SHALL implement and pass automated tests for all Calculation_Core functions before any Streamlit_Interface code is created.
2. IF a Streamlit_Interface component would depend on a Calculation_Core function that has not passed its automated tests, THEN THE CanalCast system SHALL not build that component until the Calculation_Core function passes its tests.
3. THE CanalCast system SHALL NOT expose CanalCast over a public network endpoint outside the local machine in version 1.
4. THE CanalCast system SHALL NOT include runtime artificial-intelligence features, agent-coordination hooks, or advanced draft-loss modeling in version 1, and SHALL contain no source module that invokes such behavior at runtime.
5. THE CanalCast project SHALL provide instructions that enable a developer to install dependencies and start CanalCast on a local machine.
6. THE CanalCast project SHALL provide instructions that enable a developer to deploy CanalCast with Streamlit, including the application entry point and the deployment steps.
7. THE CanalCast project SHALL pin each dependency to an exact version in a requirements file, with no open or unbounded version range.
8. IF a dependency in the requirements file is specified without an exact version, THEN THE CanalCast project SHALL treat the requirements file as invalid and report the unpinned dependency.

### Requirement 20: Optional draft-based cargo-loss modeling (version 2)

**User Story:** As a user, I want an optional, clearly-disclosed draft-based cargo-loss adjustment, so that a tighter Panama Canal draft visibly reduces loaded TEU and therefore changes fuel cost per TEU and per-TEU figures when I choose to enable it.

This requirement defines a version 2 feature that is DISABLED by default. When the draft-loss toggle is off, Requirement 10 governs unchanged (draft is context only). When the toggle is on, this requirement supersedes Requirement 10.2 and 10.3 for the affected option.

#### Acceptance Criteria

1. THE Calculation_Core SHALL accept an explicit scenario flag Draft_Loss_Enabled that defaults to false, and WHILE Draft_Loss_Enabled is false THE Calculation_Core SHALL behave exactly as specified in Requirement 10 (draft is context only).
2. WHILE Draft_Loss_Enabled is true AND the Route_Option is the Panama Route_Option, THE Calculation_Core SHALL compute a Draft_Shortfall_Ft as the reference draft in feet minus the Canal_State maximum draft in feet, using reference_draft_ft from the loaded constants.
3. IF the Draft_Shortfall_Ft is less than or equal to zero feet, THEN THE Calculation_Core SHALL set Containers_Lost to zero and SHALL NOT increase Loaded_TEU above the no-loss value.
4. WHILE Draft_Loss_Enabled is true AND Draft_Shortfall_Ft is greater than zero, THE Calculation_Core SHALL convert the shortfall to 10-centimetre units using 1 foot equals 30.48 centimetres, and SHALL compute Containers_Lost as the shortfall in 10-centimetre units multiplied by the containers-lost-per-10cm estimate.
5. THE Calculation_Core SHALL take the containers-lost-per-10cm estimate from the loaded containers_lost_per_10cm_draft_cut constant by default, and SHALL accept an explicit scenario override of that estimate when provided.
6. THE Calculation_Core SHALL convert Containers_Lost to TEU_Lost using an assumed average TEU-per-container factor Avg_Teu_Per_Container, carried as a Model_Input with status assumption.
7. WHILE Draft_Loss_Enabled is true, THE Calculation_Core SHALL compute Loaded_TEU for the Panama Route_Option as ship capacity in TEU multiplied by load factor, minus TEU_Lost, and SHALL NOT reduce the Suez Route_Option Loaded_TEU on the basis of the Panama Canal draft.
8. IF the draft-adjusted Loaded_TEU is less than or equal to zero, THEN THE Calculation_Core SHALL clamp Loaded_TEU to zero and return an Infeasible_Result for that Route_Option as specified in Requirement 11.9, without producing a negative Loaded_TEU.
9. WHILE Draft_Loss_Enabled is true, THE Calculation_Core SHALL record in the result that the cargo-loss adjustment rests on an analyst-estimate containers-lost figure and an assumption average TEU-per-container factor, and SHALL report Draft_Shortfall_Ft, Containers_Lost, and TEU_Lost as labeled result fields with their provenance.
10. THE Calculation_Core SHALL NOT alter Sailing_Fuel, the cubic fuel curve, Journey_Time, or the tank-to-wake carbon-dioxide factor on the basis of draft; the draft adjustment SHALL affect only Loaded_TEU and the per-TEU figures derived from it.
11. THE Streamlit_Interface SHALL provide a Draft_Loss_Enabled toggle defaulting to off, and WHILE the toggle is on THE Streamlit_Interface SHALL provide a containers-lost-per-10cm slider seeded from the loaded estimate and SHALL display Draft_Shortfall_Ft, Containers_Lost, TEU_Lost, and the analyst-estimate and assumption disclosures alongside the affected results.
