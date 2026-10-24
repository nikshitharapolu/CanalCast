"""Pure calculation functions for the CanalCast Calculation_Core.

This module is part of the pure Calculation_Core. It performs NO file I/O and
makes NO network calls, and it imports no library that does either. It imports
only from :mod:`canalcast.models` and the standard-library ``math``/``typing``
modules. A boundary test (Task 8.1) scans this module for forbidden imports.

Every function is fully type-hinted and returns ``ResultOrUnavailable[float]``
(i.e. ``float | Unavailable``) or, for the container conversion, ``int |
Unavailable``. A value that cannot be produced is ALWAYS an :class:`Unavailable`
carrying a human-readable reason and the names of the missing or invalid inputs
-- never ``0``, ``None``, ``NaN``, or ``inf`` (Requirements 3.2, 3.3).

Covers Requirements 5.3, 5.4, 6.1-6.8, 7.1-7.6, 8.1-8.8, 9.1-9.5.
"""

from __future__ import annotations

import math
from typing import Union

from .models import (
    ContainerUnit,  # noqa: F401  (domain type referenced in docs / signatures)
    DraftLoss,
    EmissionFactor,
    ProvenancedValue,
    ResultOrUnavailable,
    Status,  # noqa: F401  (re-exported for callers via *; part of core vocabulary)
    Unavailable,
)


def _is_finite_number(x: object) -> bool:
    """Return True when ``x`` is a real, finite number (not NaN/inf)."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


# ---------------------------------------------------------------------------
# Task 4.1 -- time functions (Requirements 6.1-6.8)
# ---------------------------------------------------------------------------


def sailing_time_hours(
    distance_nm: float | None, speed_kn: float | None
) -> ResultOrUnavailable[float]:
    """Sailing time in hours for a leg of ``distance_nm`` at ``speed_kn``.

    Sailing time is ``distance_nm / speed_kn`` when distance is present and
    non-negative and speed is present and strictly positive. A missing distance
    or missing/invalid speed disables the calculation and yields an
    :class:`Unavailable` naming the offending input (Requirements 6.1, 6.6,
    6.7). ``distance_nm == 0`` is valid and returns ``0.0``.
    """
    if distance_nm is None:
        return Unavailable(
            reason="sailing time requires distance, which is an unresolved input",
            missing_inputs=("distance_nm",),
        )
    if speed_kn is None:
        return Unavailable(
            reason="sailing time requires speed, which is an unresolved input",
            missing_inputs=("speed_kn",),
        )
    if not _is_finite_number(distance_nm) or distance_nm < 0:
        return Unavailable(
            reason="sailing time requires a non-negative distance; distance_nm is invalid",
            invalid_inputs=("distance_nm",),
        )
    if not _is_finite_number(speed_kn) or speed_kn <= 0:
        return Unavailable(
            reason="sailing time requires a positive speed; speed_kn is invalid",
            invalid_inputs=("speed_kn",),
        )
    return float(distance_nm) / float(speed_kn)


def journey_time_hours(
    sailing_h: Union[float, Unavailable, None],
    canal_duration_h: Union[float, Unavailable, None],
    waiting_duration_h: Union[float, Unavailable, None],
) -> ResultOrUnavailable[float]:
    """Total journey time = sailing + canal + waiting (hours).

    All three durations are explicit inputs. Waiting time is derived solely from
    its own explicit input and is NEVER inferred from a booking-slot limit
    (Requirements 6.3, 6.4). When every component is present and ``>= 0`` the
    result is their sum (Requirement 6.5). If the sailing component is itself
    unavailable, or any duration is missing/negative, the journey time is
    disabled and an :class:`Unavailable` naming the offending input is returned
    (Requirement 6.8).
    """
    if isinstance(sailing_h, Unavailable):
        return Unavailable(
            reason="journey time requires sailing time, which is unavailable",
            missing_inputs=("sailing_h",),
        )
    if sailing_h is None:
        return Unavailable(
            reason="journey time requires sailing time, which is an unresolved input",
            missing_inputs=("sailing_h",),
        )
    if not _is_finite_number(sailing_h) or sailing_h < 0:
        return Unavailable(
            reason="journey time requires a non-negative sailing time; sailing_h is invalid",
            invalid_inputs=("sailing_h",),
        )

    if isinstance(canal_duration_h, Unavailable):
        return Unavailable(
            reason="journey time requires canal_duration, which is unavailable",
            missing_inputs=("canal_duration_h",),
        )
    if canal_duration_h is None:
        return Unavailable(
            reason="journey time requires canal_duration, which is an unresolved input",
            missing_inputs=("canal_duration_h",),
        )
    if not _is_finite_number(canal_duration_h) or canal_duration_h < 0:
        return Unavailable(
            reason="journey time requires a non-negative canal_duration; it is invalid",
            invalid_inputs=("canal_duration_h",),
        )

    if isinstance(waiting_duration_h, Unavailable):
        return Unavailable(
            reason="journey time requires waiting_duration, which is unavailable",
            missing_inputs=("waiting_duration_h",),
        )
    if waiting_duration_h is None:
        return Unavailable(
            reason="journey time requires waiting_duration, which is an unresolved input",
            missing_inputs=("waiting_duration_h",),
        )
    if not _is_finite_number(waiting_duration_h) or waiting_duration_h < 0:
        return Unavailable(
            reason="journey time requires a non-negative waiting_duration; it is invalid",
            invalid_inputs=("waiting_duration_h",),
        )

    return float(sailing_h) + float(canal_duration_h) + float(waiting_duration_h)


# ---------------------------------------------------------------------------
# Task 4.2 -- fuel functions (Requirements 7.1-7.6)
# ---------------------------------------------------------------------------


def fuel_rate_t_per_day(
    speed_kn: float | None,
    base_fuel_t_per_day: float | None,
    base_speed_kn: float | None,
    speed_exponent: float | None,
) -> ResultOrUnavailable[float]:
    """Fuel burn (t/day) from the cubic curve ``base_fuel * (speed/base_speed)^exp``.

    The rate is driven exclusively by the loaded curve constants; there is no
    alternate ship profile (Requirements 7.1, 7.2, 7.6). A missing input, a
    non-positive ``speed_kn``, or a non-positive ``base_speed_kn`` disables the
    calculation and yields an :class:`Unavailable` naming the offending input.
    """
    missing: list[str] = []
    if speed_kn is None:
        missing.append("speed_kn")
    if base_fuel_t_per_day is None:
        missing.append("base_fuel_t_per_day")
    if base_speed_kn is None:
        missing.append("base_speed_kn")
    if speed_exponent is None:
        missing.append("speed_exponent")
    if missing:
        return Unavailable(
            reason="fuel rate requires base-curve constants, which are unresolved inputs",
            missing_inputs=tuple(missing),
        )

    invalid: list[str] = []
    if not _is_finite_number(speed_kn) or speed_kn <= 0:
        invalid.append("speed_kn")
    if not _is_finite_number(base_speed_kn) or base_speed_kn <= 0:
        invalid.append("base_speed_kn")
    if not _is_finite_number(base_fuel_t_per_day) or base_fuel_t_per_day < 0:
        invalid.append("base_fuel_t_per_day")
    if not _is_finite_number(speed_exponent):
        invalid.append("speed_exponent")
    if invalid:
        return Unavailable(
            reason="fuel rate requires positive speeds and valid curve constants; some are invalid",
            invalid_inputs=tuple(invalid),
        )

    return float(base_fuel_t_per_day) * (float(speed_kn) / float(base_speed_kn)) ** float(
        speed_exponent
    )


def sailing_fuel_t(
    fuel_rate_t_per_day: Union[float, Unavailable],
    sailing_time_hours: Union[float, Unavailable],
) -> ResultOrUnavailable[float]:
    """Sailing fuel (tonnes) = rate (t/day) x sailing days.

    ``sailing_time_hours`` is converted from hours to days (``/24``) because the
    rate is per DAY (Requirement 7.3). An :class:`Unavailable` in either input
    propagates.
    """
    if isinstance(fuel_rate_t_per_day, Unavailable):
        return Unavailable(
            reason="sailing fuel requires a fuel rate, which is unavailable",
            missing_inputs=("fuel_rate_t_per_day",),
        )
    if isinstance(sailing_time_hours, Unavailable):
        return Unavailable(
            reason="sailing fuel requires sailing time, which is unavailable",
            missing_inputs=("sailing_time_hours",),
        )
    if not _is_finite_number(fuel_rate_t_per_day) or fuel_rate_t_per_day < 0:
        return Unavailable(
            reason="sailing fuel requires a non-negative fuel rate; it is invalid",
            invalid_inputs=("fuel_rate_t_per_day",),
        )
    if not _is_finite_number(sailing_time_hours) or sailing_time_hours < 0:
        return Unavailable(
            reason="sailing fuel requires a non-negative sailing time; it is invalid",
            invalid_inputs=("sailing_time_hours",),
        )
    return float(fuel_rate_t_per_day) * (float(sailing_time_hours) / 24.0)


def line_item_fuel_t(
    duration_h: float | None,
    fuel_rate_t_per_day: Union[ProvenancedValue, float, None],
    *,
    item_name: str,
) -> ResultOrUnavailable[float]:
    """Fuel (tonnes) for a single line item (waiting or canal) over ``duration_h``.

    The identical rule is applied to BOTH the waiting and canal line items
    (Requirements 7.4, 7.5):

    * ``duration_h`` missing or negative -> :class:`Unavailable` naming the
      duration.
    * ``duration_h == 0`` -> ``0.0`` (zero duration means zero fuel, ALWAYS
      resolvable, even when the fuel rate is absent).
    * ``duration_h > 0`` with an absent rate -> :class:`Unavailable` naming the
      unresolved fuel-rate input.
    * ``duration_h > 0`` with a present rate -> ``rate * duration_days``. A
      :class:`ProvenancedValue` rate is read via ``float(rate.value)``.

    These line items are reported distinctly and are never folded into sailing
    fuel.
    """
    duration_key = f"{item_name}_duration_h"
    if duration_h is None:
        return Unavailable(
            reason=f"{item_name} fuel requires {item_name} duration, which is an unresolved input",
            missing_inputs=(duration_key,),
        )
    if not _is_finite_number(duration_h) or duration_h < 0:
        return Unavailable(
            reason=f"{item_name} fuel requires a non-negative {item_name} duration; it is invalid",
            invalid_inputs=(duration_key,),
        )

    # Zero duration is always resolvable to zero fuel, even without a rate.
    if duration_h == 0:
        return 0.0

    rate_key = f"{item_name}_fuel_t_per_day"
    if fuel_rate_t_per_day is None:
        return Unavailable(
            reason=f"{item_name} fuel rate is an unresolved input",
            missing_inputs=(rate_key,),
        )

    rate_value = (
        fuel_rate_t_per_day.value
        if isinstance(fuel_rate_t_per_day, ProvenancedValue)
        else fuel_rate_t_per_day
    )
    if not _is_finite_number(rate_value) or float(rate_value) < 0:
        return Unavailable(
            reason=f"{item_name} fuel requires a non-negative fuel rate; it is invalid",
            invalid_inputs=(rate_key,),
        )

    return float(rate_value) * (float(duration_h) / 24.0)


def waiting_fuel_t(
    duration_h: float | None,
    fuel_rate_t_per_day: Union[ProvenancedValue, float, None],
) -> ResultOrUnavailable[float]:
    """Waiting-line-item fuel (tonnes); thin wrapper over :func:`line_item_fuel_t`."""
    return line_item_fuel_t(duration_h, fuel_rate_t_per_day, item_name="waiting")


def canal_fuel_t(
    duration_h: float | None,
    fuel_rate_t_per_day: Union[ProvenancedValue, float, None],
) -> ResultOrUnavailable[float]:
    """Canal-line-item fuel (tonnes); thin wrapper over :func:`line_item_fuel_t`."""
    return line_item_fuel_t(duration_h, fuel_rate_t_per_day, item_name="canal")


def total_voyage_fuel_t(
    sailing_fuel: Union[float, Unavailable],
    waiting_fuel: Union[float, Unavailable],
    canal_fuel: Union[float, Unavailable],
) -> ResultOrUnavailable[float]:
    """Total voyage fuel (tonnes) = sailing + waiting + canal.

    The sum is a TRUE total only when all three components are resolved floats
    (Requirement 7.4). If any component is an :class:`Unavailable`, the total is
    unavailable and names every unresolved component -- the caller (comparison)
    is responsible for labelling a sailing-only figure as a partial estimate.
    """
    components = (
        ("sailing_fuel", sailing_fuel),
        ("waiting_fuel", waiting_fuel),
        ("canal_fuel", canal_fuel),
    )
    missing = tuple(name for name, value in components if isinstance(value, Unavailable))
    if missing:
        return Unavailable(
            reason="total requires all fuel components; some are unresolved",
            missing_inputs=missing,
        )

    invalid = tuple(
        name
        for name, value in components
        if not _is_finite_number(value) or float(value) < 0  # type: ignore[arg-type]
    )
    if invalid:
        return Unavailable(
            reason="total requires non-negative fuel components; some are invalid",
            invalid_inputs=invalid,
        )

    return float(sailing_fuel) + float(waiting_fuel) + float(canal_fuel)


# ---------------------------------------------------------------------------
# Task 4.3 -- cost and TEU functions (Requirements 8.1-8.8)
# ---------------------------------------------------------------------------


def voyage_fuel_cost_usd(
    total_fuel_t: Union[float, Unavailable],
    bunker_price_usd_per_t: float | None,
) -> ResultOrUnavailable[float]:
    """Voyage fuel cost (USD) = total fuel (t) x bunker price (USD/t).

    This is a FUEL cost only (never a total shipping cost); tolls, insurance,
    and surcharges are excluded and recorded elsewhere (Requirements 8.1, 8.7,
    8.8). An :class:`Unavailable` total propagates; a missing or negative bunker
    price disables the calculation.
    """
    if isinstance(total_fuel_t, Unavailable):
        return Unavailable(
            reason="fuel cost requires total voyage fuel, which is unavailable",
            missing_inputs=("total_fuel_t",),
        )
    if not _is_finite_number(total_fuel_t) or total_fuel_t < 0:
        return Unavailable(
            reason="fuel cost requires a non-negative total fuel; it is invalid",
            invalid_inputs=("total_fuel_t",),
        )
    if bunker_price_usd_per_t is None:
        return Unavailable(
            reason="fuel cost requires a bunker price, which is an unresolved input",
            missing_inputs=("bunker_price_usd_per_t",),
        )
    if not _is_finite_number(bunker_price_usd_per_t) or bunker_price_usd_per_t < 0:
        return Unavailable(
            reason="fuel cost requires a non-negative bunker price; it is invalid",
            invalid_inputs=("bunker_price_usd_per_t",),
        )
    return float(total_fuel_t) * float(bunker_price_usd_per_t)


def loaded_teu(
    capacity_teu: float | None, load_factor: float | None
) -> ResultOrUnavailable[float]:
    """Loaded TEU = capacity x load factor, for load factor in [0, 1].

    A missing capacity or load factor disables the calculation; a load factor
    outside ``[0, 1]`` is invalid (Requirements 8.2, 8.5).
    """
    missing: list[str] = []
    if capacity_teu is None:
        missing.append("capacity_teu")
    if load_factor is None:
        missing.append("load_factor")
    if missing:
        return Unavailable(
            reason="loaded TEU requires capacity and load factor, which are unresolved inputs",
            missing_inputs=tuple(missing),
        )

    if not _is_finite_number(capacity_teu) or capacity_teu < 0:
        return Unavailable(
            reason="loaded TEU requires a non-negative capacity; capacity_teu is invalid",
            invalid_inputs=("capacity_teu",),
        )
    if not _is_finite_number(load_factor) or load_factor < 0 or load_factor > 1:
        return Unavailable(
            reason="loaded TEU requires a load factor in [0, 1]; load_factor is invalid",
            invalid_inputs=("load_factor",),
        )
    return float(capacity_teu) * float(load_factor)


def fuel_cost_per_teu_usd(
    voyage_fuel_cost_usd: Union[float, Unavailable],
    loaded_teu: Union[float, Unavailable],
) -> ResultOrUnavailable[float]:
    """Fuel cost per TEU (USD/TEU) = voyage fuel cost / loaded TEU.

    When loaded TEU is zero the per-TEU cost is undefined and returned as an
    :class:`Unavailable` -- never ``0`` or an invented value (Requirements 8.3,
    8.4). An :class:`Unavailable` in either input propagates.
    """
    if isinstance(voyage_fuel_cost_usd, Unavailable):
        return Unavailable(
            reason="fuel cost per TEU requires the voyage fuel cost, which is unavailable",
            missing_inputs=("voyage_fuel_cost_usd",),
        )
    if isinstance(loaded_teu, Unavailable):
        return Unavailable(
            reason="fuel cost per TEU requires loaded TEU, which is unavailable",
            missing_inputs=("loaded_teu",),
        )
    if not _is_finite_number(voyage_fuel_cost_usd) or voyage_fuel_cost_usd < 0:
        return Unavailable(
            reason="fuel cost per TEU requires a non-negative voyage fuel cost; it is invalid",
            invalid_inputs=("voyage_fuel_cost_usd",),
        )
    if not _is_finite_number(loaded_teu) or loaded_teu < 0:
        return Unavailable(
            reason="fuel cost per TEU requires a non-negative loaded TEU; it is invalid",
            invalid_inputs=("loaded_teu",),
        )
    if loaded_teu == 0:
        return Unavailable(
            reason="loaded TEU is zero, so fuel cost per TEU is undefined",
            invalid_inputs=("loaded_teu",),
        )
    return float(voyage_fuel_cost_usd) / float(loaded_teu)


# ---------------------------------------------------------------------------
# Task 4.4 -- CO2 and container conversion (Requirements 5.3, 5.4, 9.1-9.5)
# ---------------------------------------------------------------------------


def co2_tank_to_wake_t(
    total_fuel_t: Union[float, Unavailable],
    factor: EmissionFactor | None,
    selected_fuel_type: str,
) -> ResultOrUnavailable[float]:
    """Tank-to-wake CO2 (tonnes) = total fuel x emission factor.

    This is a TANK-TO-WAKE, fuel-combustion CO2 figure ONLY -- it is NOT a
    lifecycle / well-to-wake value (Requirement 9.5). The emission factor must
    be present and its ``fuel_type`` must EXACTLY match ``selected_fuel_type``;
    a missing factor or a type mismatch disables the calculation (Requirements
    9.2, 9.3, 9.4). An :class:`Unavailable` total propagates.
    """
    if factor is None:
        return Unavailable(
            reason="no emission factor for selected fuel type",
            missing_inputs=("emission_factor",),
        )
    if factor.fuel_type != selected_fuel_type:
        return Unavailable(
            reason=(
                "emission factor fuel type "
                f"'{factor.fuel_type}' does not match selected fuel type "
                f"'{selected_fuel_type}'"
            ),
            invalid_inputs=("selected_fuel_type",),
        )
    if isinstance(total_fuel_t, Unavailable):
        return Unavailable(
            reason="CO2 requires total voyage fuel, which is unavailable",
            missing_inputs=("total_fuel_t",),
        )
    if not _is_finite_number(total_fuel_t) or total_fuel_t < 0:
        return Unavailable(
            reason="CO2 requires a non-negative total fuel; it is invalid",
            invalid_inputs=("total_fuel_t",),
        )
    return float(total_fuel_t) * float(factor.co2_t_per_fuel_t.value)


def teu_for_container(container_type: str) -> ResultOrUnavailable[int]:
    """Exact TEU conversion for a container type: 20ft -> 1, 40ft -> 2.

    The conversion is exact (Requirement 5.3). Any unsupported type disables
    only this conversion and yields an :class:`Unavailable` naming the offending
    type -- other quantities are unaffected (Requirement 5.4).
    """
    if container_type == "20ft":
        return 1
    if container_type == "40ft":
        return 2
    return Unavailable(
        reason=f"unsupported container type '{container_type}'",
        invalid_inputs=("container_type",),
    )


# ---------------------------------------------------------------------------
# Task 14.2 -- optional draft-based cargo-loss modeling (Requirements 20.1-20.7, 20.10)
# ---------------------------------------------------------------------------


def draft_cargo_loss(
    option: str,
    canal_state_max_draft_ft: float | None,
    reference_draft_ft: float | None,
    containers_lost_per_10cm: float | None,
    avg_teu_per_container: float | None,
    *,
    enabled: bool,
) -> DraftLoss | Unavailable:
    """Draft-based cargo-loss figures for one routing option (Requirement 20).

    This version-2 adjustment is DISABLED by default and, when off, preserves
    exact v1 behavior: draft remains pure context and never reduces cargo
    (Requirement 20.1). It is a Panama-only effect; the Suez option is never
    draft-reduced on the basis of the Panama Canal draft (Requirement 20.7).

    Provenance: the inputs rest on an ANALYST-ESTIMATE containers-lost-per-10cm
    figure (``containers_lost_per_10cm``) and an ASSUMPTION average
    TEU-per-container factor (``avg_teu_per_container``); the caller records this
    provenance on the labeled result fields (Requirements 20.5, 20.6, 20.9).

    This function produces ONLY the loss figures. It never touches sailing fuel,
    the cubic fuel curve, journey time, or the tank-to-wake CO2 factor; those
    are unaffected by draft (Requirement 20.10). It never raises for expected
    bad input: a missing/non-finite required input (while enabled on Panama)
    yields an :class:`Unavailable` naming it, and a nonsense negative estimate or
    factor yields an :class:`Unavailable` naming the invalid input -- never a
    substituted or negative loss.

    Rules (Requirements 20.1-20.7, 20.10):

    * ``enabled is False`` or ``option != "panama"`` -> ``DraftLoss(0, 0, 0)``.
    * ``shortfall_ft = reference_draft_ft - canal_state_max_draft_ft``; clamped to
      ``DraftLoss(0, 0, 0)`` when ``<= 0`` (Requirements 20.2, 20.3).
    * ``ten_cm_units = shortfall_ft * 30.48 / 10.0`` (1 ft = 30.48 cm).
    * ``containers_lost = ten_cm_units * containers_lost_per_10cm`` (Req 20.4).
    * ``teu_lost = containers_lost * avg_teu_per_container`` (Req 20.6).
    """
    # Off, or Suez: no draft-based loss at all (Requirements 20.1, 20.7).
    if not enabled or option != "panama":
        return DraftLoss(0.0, 0.0, 0.0)

    # Panama with draft loss enabled: every figure rests on these inputs.
    required = (
        ("reference_draft_ft", reference_draft_ft),
        ("canal_state_max_draft_ft", canal_state_max_draft_ft),
        ("containers_lost_per_10cm", containers_lost_per_10cm),
        ("avg_teu_per_container", avg_teu_per_container),
    )
    missing = tuple(
        name for name, value in required if value is None or not _is_finite_number(value)
    )
    if missing:
        return Unavailable(
            reason=(
                "draft-based cargo loss requires reference_draft_ft, "
                "canal_state_max_draft_ft, containers_lost_per_10cm, and "
                "avg_teu_per_container; some are unresolved inputs"
            ),
            missing_inputs=missing,
        )

    # Guard against nonsense sliders: a negative estimate or factor is invalid.
    invalid = tuple(
        name
        for name, value in (
            ("containers_lost_per_10cm", containers_lost_per_10cm),
            ("avg_teu_per_container", avg_teu_per_container),
        )
        if float(value) < 0  # type: ignore[arg-type]
    )
    if invalid:
        return Unavailable(
            reason=(
                "draft-based cargo loss requires a non-negative "
                "containers_lost_per_10cm estimate and avg_teu_per_container "
                "factor; some are invalid"
            ),
            invalid_inputs=invalid,
        )

    shortfall_ft = float(reference_draft_ft) - float(canal_state_max_draft_ft)  # type: ignore[arg-type]
    if shortfall_ft <= 0:
        # Draft meets or exceeds reference: no loss (Requirement 20.3).
        return DraftLoss(0.0, 0.0, 0.0)

    ten_cm_units = shortfall_ft * 30.48 / 10.0  # 1 ft = 30.48 cm
    containers_lost = ten_cm_units * float(containers_lost_per_10cm)  # type: ignore[arg-type]
    teu_lost = containers_lost * float(avg_teu_per_container)  # type: ignore[arg-type]
    return DraftLoss(shortfall_ft, containers_lost, teu_lost)
