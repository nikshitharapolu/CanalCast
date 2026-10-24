CanalCast is a scenario simulator for Panama Canal restrictions under El Niño, not a forecast.
Python code computes every number; any LLM text only explains computed results.
Every input has a source and a status (sourced | approximate | assumption | derived).
Never invent a number: if one is missing, add a TODO row with status=assumption and show it in the UI Assumptions panel.
Never show shipping-line names or logos anywhere; use Carrier A/B/C.
Costs are per TEU. Tolls are out of scope and the UI says so.
No network calls at runtime except the cached data fetch, which must fall back gracefully.