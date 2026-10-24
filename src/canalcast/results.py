"""Result structures for the CanalCast Calculation_Core.

This module defines the immutable result contract agreed in design before
implementation ("The Result Structure"). It is part of the pure
Calculation_Core: it performs NO file I/O and makes NO network calls, and it
imports no library that does either. It imports only from :mod:`.models` and the
standard library's typing/dataclasses facilities (a later boundary test scans
this file for forbidden imports).

Every numeric field carries its unit in the field name or in the per-option
``units`` map, and every field that may be absent is a
:class:`~canalcast.models.Unavailable` (via
:data:`~canalcast.models.ResultOrUnavailable`) rather than a substituted ``0``,
``None``, ``NaN``, or ``inf``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .models import NotModeled, ProvenancedValue, ResultOrUnavailable, Unavailable

#: Fixed label attached to the sailing-only partial estimates on
#: :class:`OptionResult`. Those figures exclude unresolved canal/waiting fuel, so
#: they are never voyage totals and are never used for selection or ranking.
SAILING_ONLY_LABEL = "Sailing-only estimate (excludes unresolved canal/waiting fuel)"


@dataclass(frozen=True)
class JourneyTimeBreakdown:
    """Journey-time components for a single routing option.

    Each component is numeric when its inputs are present and valid, otherwise an
    :class:`~canalcast.models.Unavailable` naming the offending input. The total
    :attr:`journey_time_h` is the sum of sailing, canal, and waiting time only
    when all three parts are present (Requirement 6.5).

    Attributes:
        sailing_time_h: Sailing time in hours, or ``Unavailable``.
        canal_duration_h: Canal transit duration in hours, or ``Unavailable``.
        waiting_duration_h: Waiting duration in hours, or ``Unavailable``.
        journey_time_h: Sum of the parts when all are present (Requirement 6.5),
            otherwise ``Unavailable`` naming the missing/invalid component.
    """

    sailing_time_h: ResultOrUnavailable[float]
    canal_duration_h: ResultOrUnavailable[float]
    waiting_duration_h: ResultOrUnavailable[float] | NotModeled
    journey_time_h: ResultOrUnavailable[float]  # sum when all parts present (Req 6.5)


@dataclass(frozen=True)
class FuelBreakdown:
    """Fuel-consumption components for a single routing option.

    Waiting and canal fuel are DISTINCT line items and are never folded into
    sailing fuel (Requirements 7.4, 7.5). When a line item's fuel rate is
    required but absent, that line item is an
    :class:`~canalcast.models.Unavailable`; the total is reported as a true
    "total" only when every component is resolved.

    Attributes:
        fuel_rate_t_per_day: Sailing fuel burn rate in tonnes per day, or
            ``Unavailable``.
        sailing_fuel_t: Fuel burned while sailing, in tonnes, or ``Unavailable``.
        waiting_fuel_t: Distinct waiting-fuel line item in tonnes, or
            ``Unavailable`` when a positive waiting duration has no rate
            (Requirements 7.4, 7.5).
        canal_fuel_t: Distinct canal-fuel line item in tonnes, or ``Unavailable``
            when a positive canal duration has no rate (Requirements 7.4, 7.5).
        total_voyage_fuel_t: Sum of the resolved fuel line items in tonnes, or
            ``Unavailable`` naming the missing components.
    """

    fuel_rate_t_per_day: ResultOrUnavailable[float]
    sailing_fuel_t: ResultOrUnavailable[float]
    waiting_fuel_t: ResultOrUnavailable[float]  # distinct line item (Req 7.4, 7.5)
    canal_fuel_t: ResultOrUnavailable[float]  # distinct line item (Req 7.4, 7.5)
    total_voyage_fuel_t: ResultOrUnavailable[float]


@dataclass(frozen=True)
class OptionResult:
    """The complete per-option result for one canal routing (Panama or Suez).

    Every numeric metric is accompanied by an explicit unit in :attr:`units`
    (Requirement 11.10) and by provenance for its inputs in
    :attr:`input_provenance` (Requirement 11.10). Canal-state maximum draft is
    carried only as CONTEXT via :attr:`draft_context_ft` together with the fixed
    :attr:`draft_not_modeled_disclosure`; draft never reduces TEU, cost, fuel, or
    CO2 in v1 (Requirements 10.1, 10.3, 10.4). The cost figure is always labeled
    "fuel cost" and never "total shipping cost" (Requirement 8.8), and the
    excluded cost/emission items are recorded in :attr:`exclusions`
    (Requirement 8.6).

    Note on field ordering: because frozen dataclass fields with defaults must
    follow all non-default fields, :attr:`cost_label` and
    :attr:`input_provenance` (both defaulted) are declared last even though the
    design lists ``input_provenance`` after them without a default.

    Attributes:
        option: Which canal this option routes through.
        route_id: Identifier of the owning OD pair.
        units: Explicit unit per metric name (Requirement 11.10).
        journey: Journey-time breakdown for this option.
        fuel: Fuel breakdown for this option.
        loaded_teu: Loaded payload in TEU, or ``Unavailable``.
        voyage_fuel_cost_usd: Voyage fuel cost in USD computed from RESOLVED
            total voyage fuel only (Requirement 8.1), or ``Unavailable`` naming
            the unresolved fuel component(s) — never a sailing-only figure.
        fuel_cost_per_teu_usd: Fuel cost per loaded TEU in USD, set to
            ``Unavailable(reason="loaded TEU is zero")`` when payload is zero
            (Requirement 8.4), and ``Unavailable`` whenever total voyage fuel
            is unresolved.
        co2_tank_to_wake_t: Tank-to-wake CO2 in tonnes — NOT lifecycle
            (Requirement 9.5) — from RESOLVED total voyage fuel only
            (Requirement 9.1), or ``Unavailable``.
        feasible: ``True``/``False`` when journey time is known
            (``journey_time_h <= deadline_h``); ``None`` if journey time is
            unavailable.
        deadline_status: One of ``"meets deadline"``, ``"misses deadline"``, or
            ``"undetermined"``.
        infeasible: ``True`` when ``loaded_teu == 0`` (Infeasible_Result,
            Requirement 11.9).
        infeasible_reason: Plain-language reason when infeasible, else ``None``.
        draft_context_ft: Canal-state maximum draft carried as CONTEXT only
            (Requirement 10.1).
        draft_not_modeled_disclosure: Fixed text stating draft cargo-capacity
            effects are not modeled in v1 (Requirement 10.4).
        exclusions: Cost/emission items excluded from this result — tolls,
            insurance, carrier surcharges, lifecycle emissions, draft cargo-loss
            (Requirement 8.6).
        cost_label: Always ``"fuel cost"``; never ``"total shipping cost"``
            (Requirement 8.8).
        input_provenance: Provenance for each input behind this option
            (Requirement 11.10).
        draft_loss_enabled: Whether the optional draft-based cargo-loss
            adjustment was applied to this option. ``False`` by default, which
            preserves exact v1 behavior and leaves the remaining draft-loss
            fields ``None`` (Requirement 20.9).
        draft_shortfall_ft: The draft shortfall in feet that drove the loss when
            draft loss is enabled, else ``None`` (``None`` when disabled, not
            applicable, or the loss could not be computed) (Requirement 20.9).
        containers_lost: Estimated containers lost to the draft shortfall when
            draft loss is enabled, else ``None`` (Requirement 20.9).
        teu_lost: TEU lost (``containers_lost`` times the average-TEU-per-
            container assumption) when draft loss is enabled, else ``None``
            (Requirement 20.9).
        draft_loss_disclosure: Fixed disclosure, present only when draft loss is
            enabled, stating the adjustment rests on an analyst-estimate
            containers-lost figure and an assumption average-TEU-per-container
            factor; ``None`` when disabled (Requirement 20.9).
        sailing_only_fuel_cost_usd: Sailing-only fuel cost in USD (sailing fuel
            x bunker price). Populated ONLY when total voyage fuel is
            unresolved but sailing fuel is resolved, else ``None``. A partial
            estimate, not a voyage total; never used for selection or ranking.
        sailing_only_co2_t: Sailing-only tank-to-wake CO2 in tonnes, under the
            same rule as :attr:`sailing_only_fuel_cost_usd`.
        sailing_only_label: :data:`SAILING_ONLY_LABEL` whenever the sailing-only
            fields are populated, else ``None``.
    """

    option: Literal["panama", "suez"]
    route_id: str
    units: Mapping[str, str]  # explicit unit per metric (Req 11.10)

    journey: JourneyTimeBreakdown
    fuel: FuelBreakdown
    loaded_teu: ResultOrUnavailable[float]
    voyage_fuel_cost_usd: ResultOrUnavailable[float]
    # Unavailable(reason="loaded TEU is zero") when payload 0 (Req 8.4):
    fuel_cost_per_teu_usd: ResultOrUnavailable[float]
    co2_tank_to_wake_t: ResultOrUnavailable[float]  # tank-to-wake, NOT lifecycle (Req 9.5)

    feasible: bool | None  # journey_time_h <= deadline_h; None if time unavailable
    deadline_status: str  # "meets deadline" | "misses deadline" | "undetermined"
    infeasible: bool  # True when loaded_teu == 0 (Req 11.9)
    infeasible_reason: str | None

    draft_context_ft: ProvenancedValue  # canal-state max draft as CONTEXT (Req 10.1)
    # fixed text: draft cargo-capacity effects not modeled in v1 (Req 10.4):
    draft_not_modeled_disclosure: str
    # tolls, insurance, carrier surcharges, lifecycle emissions, draft cargo-loss (Req 8.6):
    exclusions: tuple[str, ...]

    cost_label: str = "fuel cost"  # never "total shipping cost" (Req 8.8)
    # provenance for each input behind this option (Req 11.10):
    input_provenance: Mapping[str, ProvenancedValue] = field(default_factory=dict)

    # Optional draft-based cargo-loss adjustment (Requirement 20). All default
    # to the no-loss state so existing v1 construction is unaffected (Req 20.9):
    draft_loss_enabled: bool = False
    draft_shortfall_ft: float | None = None
    containers_lost: float | None = None
    teu_lost: float | None = None
    draft_loss_disclosure: str | None = None

    # Sailing-only partial estimates. Populated only when total voyage fuel is
    # unresolved but sailing fuel is resolved; they are NOT voyage totals, carry
    # SAILING_ONLY_LABEL, and selection/ranking never reads them. Defaults keep
    # existing construction unaffected.
    sailing_only_fuel_cost_usd: ResultOrUnavailable[float] | None = None
    sailing_only_co2_t: ResultOrUnavailable[float] | None = None
    sailing_only_label: str | None = None
    # When deadline_status is "undetermined": the inputs that caused it.
    deadline_undetermined_inputs: tuple[str, ...] = ()
    # Suez only: fixed text that Suez waiting is not modeled (Req 6.12, 15.2).
    waiting_not_modeled_disclosure: str | None = None


@dataclass(frozen=True)
class Selection:
    """The selection outcome across the compared options.

    When no option is feasible, :attr:`selected_option` is ``None`` and
    :attr:`closest_option` identifies the faster available route by minimum
    journey time (Requirement 11.5). The Panama final tie-break is a disclosed
    deterministic CONVENTION recorded in :attr:`tie_resolution` and
    :attr:`message`, not a claim of route superiority (Requirement 11.8).

    Attributes:
        selected_option: The chosen option, or ``None`` when none is feasible
            (Requirement 11.5).
        priority: The Selection_Priority metric used.
        no_feasible_option: ``True`` only when every available option has a
            resolved journey time and misses the deadline.
        closest_option: Faster available route in that case
            (Requirement 11.5), else ``None``.
        tie_resolution: Which tie step resolved the selection (Requirement 11.8),
            or ``None`` when no tie-break was needed.
        message: Plain-language description of the outcome.
    """

    selected_option: Literal["panama", "suez"] | None
    priority: str
    no_feasible_option: bool
    closest_option: Literal["panama", "suez"] | None
    tie_resolution: str | None
    message: str
    #: One of: selected, all_available_miss, feasibility_undetermined,
    #: priority_metric_unavailable, no_available_option, comparison_rejected.
    outcome: str = "selected"
    #: Per available option left uncompared: the missing/invalid inputs named.
    unresolved_inputs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonResult:
    """The complete comparison of Panama and Suez for one OD pair.

    An option absent or marked unavailable (e.g. Suez excluded by scenario
    assumption) is recorded in :attr:`excluded_options` with a reason in
    :attr:`exclusion_reasons` (Requirement 11.3). When the OD pair lacks a valid
    pair of distances the comparison cannot proceed and
    :attr:`comparison_error` carries a naming
    :class:`~canalcast.models.Unavailable` (Requirement 11.1). The fixed
    :attr:`disclaimer` makes the scenario-tool framing explicit.

    Attributes:
        od_pair_id: Identifier of the compared OD pair.
        panama: The Panama :class:`OptionResult`, or ``None``.
        suez: The Suez :class:`OptionResult`, or ``None``.
        excluded_options: Options excluded from selection, e.g. ``("suez",)``
            (Requirement 11.3).
        exclusion_reasons: Per-option plain-language exclusion reasons.
        selection: The :class:`Selection` outcome.
        comparison_error: ``Unavailable`` set when the OD pair lacks a valid pair
            of distances (Requirement 11.1), else ``None``.
        disclaimer: Fixed text ``"Scenario tool — not a forecast."``.
    """

    od_pair_id: str
    panama: OptionResult | None
    suez: OptionResult | None
    excluded_options: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]
    selection: Selection
    comparison_error: Unavailable | None  # set when OD_Pair lacks valid distances (Req 11.1)
    disclaimer: str = "Scenario tool — not a forecast."
