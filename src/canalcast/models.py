"""Typed domain models and provenance for the CanalCast Calculation_Core.

This module is part of the pure Calculation_Core. It performs NO file I/O and
makes NO network calls, and it imports no library that does either. Every type
is fully type-hinted and immutable.

Missing *required* values are modeled with ``Optional[...] = None``; they are
never defaulted to zero (Requirement 1.6 / design "Status and provenance").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal, Mapping, TypeVar, Union

T = TypeVar("T")


class Status(str, Enum):
    """Provenance status of a :class:`ProvenancedValue`.

    The four values are the only statuses the Data_Loader accepts; any other
    string is rejected (Requirement 2.4 / design "Status and provenance").
    """

    SOURCED = "sourced"
    APPROXIMATE = "approximate"
    ASSUMPTION = "assumption"
    DERIVED = "derived"


@dataclass(frozen=True)
class ProvenancedValue:
    """A single value carried together with its provenance.

    Attributes:
        value: The value itself. ``str`` is permitted for non-numeric or range
            context values (e.g. ``"34-36"``); numeric computational values are
            carried as ``float``.
        unit: Unit of the value (Requirement 2.1).
        rationale: Source URL or assumption rationale (Requirement 2.1).
        status: Provenance status (Requirement 2.2).
        retrieved_on: Date the value was retrieved, retained when present
            (Requirement 1.6).
        method: Method/derivation note, retained when present (Requirement 1.6).
        derived_from: Identifiers this value was derived from. Required to be
            non-empty WHEN ``status == Status.DERIVED`` (Requirement 2.4);
            validation is enforced by the Data_Loader, not here.
        derivation: Human-readable derivation. Required to be non-empty WHEN
            ``status == Status.DERIVED`` (Requirement 2.4).
    """

    value: float | str
    unit: str
    rationale: str
    status: Status
    retrieved_on: date | None = None
    method: str | None = None
    derived_from: tuple[str, ...] = field(default_factory=tuple)
    derivation: str | None = None


@dataclass(frozen=True)
class Unavailable:
    """An explicit stand-in for a value that could not be produced.

    This is the single, consistent missing/invalid pattern used across the
    Calculation_Core (Requirements 3.2, 3.3 / design "The missing/unavailable
    pattern"). A value that cannot be produced is ALWAYS an ``Unavailable``
    carrying a human-readable reason and the names of the missing or invalid
    inputs — never ``0``, ``None`` alone, ``NaN``, or ``inf``.

    Attributes:
        reason: Human-readable explanation of why the value is unavailable.
        missing_inputs: Names of required inputs that were absent.
        invalid_inputs: Names of inputs that were present but invalid (e.g. a
            non-positive speed).
    """

    reason: str
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    invalid_inputs: tuple[str, ...] = field(default_factory=tuple)


# Alias used across calculation signatures: a function either returns the
# computed value of type ``T`` or an :class:`Unavailable` explaining why it
# could not (design "The missing/unavailable pattern").
ResultOrUnavailable = Union[T, Unavailable]


@dataclass(frozen=True)
class RouteOption:
    """One canal-routing option (Panama or Suez) for an origin-destination pair.

    Attributes:
        route_id: Identifier of the owning OD pair.
        origin: Origin port/location label.
        destination: Destination port/location label.
        option: Which canal this option routes through.
        distance_nm: Great-circle/route distance in nautical miles with
            provenance, or ``None`` when absent. When ``None`` the journey-time
            calculation for this option is disabled (Requirement 6.6).
        origin_lon: Origin longitude (context for display only).
        origin_lat: Origin latitude (context for display only).
        destination_lon: Destination longitude (context for display only).
        destination_lat: Destination latitude (context for display only).
        passages: Context label listing the passages, e.g.
            ``"babalmandab;gibraltar;malacca;suez"``.
        provenance: Provenance of the route option itself (status
            ``approximate`` for v1 route distances).
    """

    route_id: str
    origin: str
    destination: str
    option: Literal["panama", "suez"]
    distance_nm: ProvenancedValue | None
    origin_lon: float
    origin_lat: float
    destination_lon: float
    destination_lat: float
    passages: str
    provenance: ProvenancedValue


@dataclass(frozen=True)
class ODPair:
    """An origin-destination pair holding its Panama and Suez route options.

    Attributes:
        route_id: Identifier of the OD pair.
        origin: Origin port/location label.
        destination: Destination port/location label.
        panama: The Panama :class:`RouteOption`, or ``None`` if absent.
        suez: The Suez :class:`RouteOption`, or ``None`` if absent.
    """

    route_id: str
    origin: str
    destination: str
    panama: RouteOption | None
    suez: RouteOption | None


@dataclass(frozen=True)
class EmissionFactor:
    """Tank-to-wake carbon-dioxide emission factor for a single fuel type.

    Attributes:
        fuel_type: Fuel identifier, e.g. ``"HFO"``, ``"LFO"``, ``"MDO"``.
        co2_t_per_fuel_t: Tonnes of CO2 per tonne of fuel with provenance
            (status ``sourced``).
        scope: Emission scope label, e.g. ``"tank_to_wake_CO2_only"``.
        unit: Unit label, e.g. ``"t_CO2/t_fuel"``.
    """

    fuel_type: str
    co2_t_per_fuel_t: ProvenancedValue
    scope: str
    unit: str


@dataclass(frozen=True)
class CanalState:
    """A named Panama Canal operating state used as scenario context.

    Attributes:
        state: State identifier, e.g. ``"normal_reference"``,
            ``"current_oct2026"``.
        max_draft_ft: Maximum draft in feet with provenance. CONTEXT only in v1;
            it never reduces TEU, cost, fuel, or CO2 (Requirement 10).
        daily_slots: Booking-slot limit with provenance. This is a booking-slot
            limit, NOT an actual transit count (Requirement 5.1).
        period: Human-readable period label for the state.
        provenance: Provenance of the canal state record itself.
    """

    state: str
    max_draft_ft: ProvenancedValue
    daily_slots: ProvenancedValue
    period: str
    provenance: ProvenancedValue


@dataclass(frozen=True)
class ContainerUnit:
    """A container type and its exact TEU conversion factor.

    Attributes:
        container_type: Either ``"20ft"`` or ``"40ft"``.
        teu_per_container: Exactly ``1`` for a 20ft container and ``2`` for a
            40ft container (Requirement 5.3).
        provenance: Provenance of the container-unit record.
    """

    container_type: Literal["20ft", "40ft"]
    teu_per_container: int
    provenance: ProvenancedValue


@dataclass(frozen=True)
class Constants:
    """Computational constants the Calculation_Core consumes, with provenance.

    Every field is a :class:`ProvenancedValue`. The computational keys below are
    parsed to ``float`` by the loader; range/context constants (e.g. ``"34-36"``)
    are kept as ``str`` inside :attr:`ProvenancedValue.value` and live in
    :attr:`context`. ``containers_lost_per_10cm_draft_cut`` is loaded only into
    :attr:`context` and is never read by the core in v1 (Requirement 10.2).

    Attributes:
        ship_capacity_teu: Ship capacity in TEU (assumption).
        load_factor: Fraction of capacity loaded in [0, 1] (assumption).
        default_speed_kn: Default sailing speed in knots (approximate).
        base_speed_kn: Reference speed for the cubic fuel curve (knots).
        base_fuel_t_per_day: Reference fuel burn at base speed (t/day).
        speed_exponent: Exponent of the cubic fuel curve (derived).
        bunker_price_usd_per_t: Bunker price in USD per tonne (sourced).
        reference_draft_ft: Reference draft in feet (sourced, context).
        canal_wait_days_default: Default waiting TIME in days (assumption).
        waiting_fuel_t_per_day: Fuel rate while waiting (t/day), or ``None`` when
            absent from constants — an unresolved input (Requirement 7.5).
        canal_fuel_t_per_day: Fuel rate during canal operation (t/day), or
            ``None`` when absent — an unresolved input (Requirement 7.5).
        context: Raw context values (ranges, gatun levels, lost-containers
            estimate) retained but NOT used by the core in v1.
    """

    ship_capacity_teu: ProvenancedValue
    load_factor: ProvenancedValue
    default_speed_kn: ProvenancedValue
    base_speed_kn: ProvenancedValue
    base_fuel_t_per_day: ProvenancedValue
    speed_exponent: ProvenancedValue
    bunker_price_usd_per_t: ProvenancedValue
    reference_draft_ft: ProvenancedValue
    canal_wait_days_default: ProvenancedValue
    waiting_fuel_t_per_day: ProvenancedValue | None = None
    canal_fuel_t_per_day: ProvenancedValue | None = None
    context: dict[str, ProvenancedValue] = field(default_factory=dict)


@dataclass(frozen=True)
class OptionalSeries:
    """Availability record for one optional historical series.

    Optional series (ONI, RONI, canal events, transits, ...) never block the
    core comparison (Requirement 4). An absent or unreadable series is recorded
    as unavailable with a reason and loading continues (Requirements 4.2, 4.3).

    Attributes:
        name: Series identifier, e.g. ``"oni"``, ``"roni"``, ``"canal_events"``.
        available: Whether the series was loaded successfully.
        reason: Why the series is unavailable, e.g. ``"not found"`` or
            ``"could not be read"``; ``None`` when available.
        rows: The series rows, populated only when available.
        provenance: Provenance of the series when available, else ``None``.
    """

    name: str
    available: bool
    reason: str | None
    rows: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    provenance: ProvenancedValue | None = None


@dataclass(frozen=True)
class RequiredData:
    """The required, successfully loaded records referenced by LoadResult.

    Produced by the loader's ``load_required`` and held by :class:`LoadResult`.
    A missing/unreadable required file aborts loading before this is produced,
    so these fields are always fully populated (Requirement 1.8).

    Attributes:
        od_pairs: The loaded origin-destination pairs.
        constants: The loaded computational constants.
        canal_states: The loaded canal operating states.
        container_units: The loaded container-unit conversions.
        emission_factors: The loaded emission factors.
    """

    od_pairs: tuple[ODPair, ...]
    constants: Constants
    canal_states: tuple[CanalState, ...]
    container_units: tuple[ContainerUnit, ...]
    emission_factors: tuple[EmissionFactor, ...]


@dataclass(frozen=True)
class LoadResult:
    """The complete result of loading required and optional data.

    Attributes:
        required: The required, validated records (:class:`RequiredData`).
        optional: One entry per optional series, available or not.
    """

    required: RequiredData
    optional: Mapping[str, OptionalSeries]


@dataclass(frozen=True)
class Scenario:
    """A user-chosen (or preset) scenario over which the core computes results.

    Required inputs that are absent are represented as ``None`` and disable the
    dependent calculation rather than being defaulted to zero.

    Attributes:
        od_pair_id: Identifier of the OD pair to compare.
        speed_kn: Sailing speed in knots, or ``None`` if absent.
        load_factor: Fraction of capacity loaded in [0, 1], or ``None``.
        bunker_price_usd_per_t: Bunker price in USD per tonne, or ``None``.
        canal_duration_h: Canal transit duration in hours, or ``None``.
        waiting_duration_h: Waiting duration in hours from explicit input
            (default 0 by assumption), or ``None`` (Requirements 6.2, 6.3).
        deadline_h: Deadline in hours, or ``None``.
        suez_available: Explicit scenario assumption whether Suez is available
            (Requirement 11.2).
        selection_priority: The active selection metric.
        fuel_type: Selects the matching :class:`EmissionFactor`.
        canal_state: The canal operating state; draft shown as CONTEXT
            (Requirement 10).
    """

    od_pair_id: str
    speed_kn: float | None
    load_factor: float | None
    bunker_price_usd_per_t: float | None
    canal_duration_h: float | None
    waiting_duration_h: float | None
    deadline_h: float | None
    suez_available: bool
    selection_priority: Literal["fastest", "lowest_cost_per_teu", "lowest_co2"]
    fuel_type: str
    canal_state: CanalState
