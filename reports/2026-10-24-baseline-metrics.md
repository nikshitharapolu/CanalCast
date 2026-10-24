# CanalCast baseline metrics (before review fixes)

Generated on 2026-10-24 from the implementation merged in PR #1 (`main` @ `8d4b17e`), by calling `compare_od_pair` (`src/canalcast/comparison.py`) on Python 3.13.2. These numbers describe the current code, including the defects listed below. Regenerate them after Task 15 to compare.

Scenario tool — not a forecast.

## Inputs (the app's default controls)

| Input | Value | Basis |
|---|---|---|
| Speed | 18 kn (both routes) | App default; matches `default_speed_kn` (approximate) |
| Load factor | 0.85, giving 8,500 loaded TEU | `constants.csv` (assumption) |
| Bunker price | $876.5/t | `constants.csv` (sourced, 2026-10-06 average) |
| Fuel and CO₂ factor | HFO, 3.114 t CO₂ per t fuel | `emission_factors.csv` (sourced) |
| Fuel rate at 18 kn | 95.85 t/day | Derived: 175 × (18 / 22)³ |
| Canal duration | 12 h (both routes) | App default; no source recorded |
| Waiting duration | 0 days | App default; matches `canal_wait_days_default` (assumption) |
| Deadline | 30 days | App default |
| Priority / Suez | Fastest / available | App defaults |
| Canal state | Oct 2026 preset (49 ft, 33 slots/day) | `canal_states.csv` (context only) |

## Route results

| Route | Option | Journey (days) | Sailing fuel (t) | Total voyage fuel (t) | Fuel cost | Per loaded TEU | CO₂ (t) | Deadline | Selected |
|---|---|---|---|---|---|---|---|---|---|
| Shanghai → Boston | Panama | 25.5 | 2,393 | Unavailable | $2.10M | $246.7 | 7,450 | Meets deadline | ✓ |
|  | Suez | 28.9 | 2,723 | Unavailable | $2.39M | $280.8 | 8,478 | Meets deadline |  |
| Shanghai → New York | Panama | 25.1 | 2,360 | Unavailable | $2.07M | $243.4 | 7,351 | Meets deadline | ✓ |
|  | Suez | 29.2 | 2,747 | Unavailable | $2.41M | $283.2 | 8,554 | Meets deadline |  |
| Singapore → New York | Panama | 29.8 | 2,812 | Unavailable | $2.46M | $289.9 | 8,756 | Meets deadline |  |
|  | Suez | 24.0 | 2,255 | Unavailable | $1.98M | $232.6 | 7,023 | Meets deadline | ✓ |

Total voyage fuel is unavailable because the 12 h canal time has no canal fuel rate. The fuel cost, per-TEU, and CO₂ columns therefore cover sailing fuel only (finding 1).

## Findings in numbers

1. **Partial fuel shown as totals.** Setting canal time to 0 h leaves every fuel cost and CO₂ figure unchanged: True.
2. **Presets change no numbers.** "Normal reference" and "Oct 2026" give identical metrics on every route: True. This is by design, because draft and booking slots are context only.
3. **Waiting applies to both routes (finding 10).** Shanghai → New York with 0 vs 5 days of waiting: Panama 25.1 → 30.1 days, Suez 29.2 → 34.2 days. The gap doesn't change, so no Panama restriction setting can change the winner. Fixed by Task 15.7.
4. **Missing deadline gives a false message.** Deadline statuses: undetermined / undetermined. Message: "Neither route meets the deadline, so no selection was made. The closest option by journey time is panama."

## Expected after Task 15.7 (Panama-only waiting)

Derived from the route distances at 18 kn, with the same canal time on both routes.

| Route | Faster with no waiting | Break-even Panama waiting |
|---|---|---|
| Shanghai → Boston | Panama, by 3.44 days | Suez becomes faster once Panama waiting exceeds 3.44 days (82.6 h) |
| Shanghai → New York | Panama, by 4.03 days | Suez becomes faster once Panama waiting exceeds 4.03 days (96.7 h) |
| Singapore → New York | Suez, by 5.80 days | Suez is already faster; Panama waiting only widens the gap |

## Test metrics

| Test file | Tests |
|---|---|
| `tests/test_calculations.py` | 24 |
| `tests/test_loader.py` | 11 |
| `tests/test_no_io_boundary.py` | 10 |
| `tests/test_comparison.py` | 6 |
| `tests/test_draft_loss.py` | 6 |
| `tests/test_draft_loss_disclosure.py` | 4 |

Result: 61 passed in 1.12s. Code coverage wasn't measured (`pytest-cov` isn't installed). Python 3.11 hasn't been validated locally.

## Review summary

`semantic-review/2026-10-24-152025-pr-1.md` lists 9 findings: 3 high, 5 medium, and 1 low. This run adds finding 10 (waiting applied to both routes), tracked as Task 15.7.
