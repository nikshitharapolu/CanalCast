"""Data_Loader: the ONLY module in CanalCast that performs file input/output.

This module reads the required CSV files from the local ``data/`` folder
*read-only*, validates the provenance of every Model_Input, and returns typed,
immutable domain records (:mod:`canalcast.models`). It makes NO network calls
(Requirement 1.7) and never writes to the source CSVs (Requirement 1.2, 1.4).

Tasks implemented here:

* **2.1** ``load_required`` — read routes, constants, canal_states,
  container_units, and emission_factors read-only from ``data/`` and build
  typed records. A missing/unreadable required file aborts with a
  :class:`LoaderError` naming the file and produces no partial data
  (Requirement 1.1, 1.2, 1.4, 1.8).
* **2.2** provenance validation on every Model_Input as records are built:
  reject records missing value/unit/rationale/status; reject a status outside
  the four-value vocabulary for typed core fields; reject a ``derived`` record
  lacking ``derived_from``/``method`` (Requirement 1.5, 1.9, 2.3, 2.4, 2.5,
  2.6).

* **2.3** ``load_optional`` — attempt to read each optional historical series
  read-only and record it as available (retaining provenance) or unavailable
  with a reason ("not found" / "could not be read"), NEVER raising so a
  missing/unreadable optional series can never block loading; and ``load_all``
  assembles :class:`~canalcast.models.LoadResult` from ``load_required`` plus
  ``load_optional`` (Requirement 1.7, 4.1, 4.2, 4.3).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .models import (
    CanalState,
    Constants,
    ContainerUnit,
    EmissionFactor,
    LoadResult,
    ODPair,
    OptionalSeries,
    ProvenancedValue,
    RequiredData,
    RouteOption,
    Status,
)

__all__ = [
    "LoaderError",
    "ValidationError",
    "load_required",
    "load_optional",
    "load_all",
]


# --- Error types -----------------------------------------------------------


class LoaderError(Exception):
    """A file-level or structural failure while loading required data.

    Raised when a required CSV file is missing or unreadable (Requirement 1.8),
    or when collected provenance-validation failures make the required data set
    impossible to build. When raised, NO partial Model_Input data is produced.

    Attributes:
        file: The file whose reading/validation failed, when applicable.
        errors: The collected :class:`ValidationError` details, when the failure
            is a batch of record-level provenance rejections.
    """

    def __init__(
        self,
        message: str,
        *,
        file: str | None = None,
        errors: tuple["ValidationError", ...] = (),
    ) -> None:
        super().__init__(message)
        self.file = file
        self.errors = errors


class ValidationError(Exception):
    """A single provenance-validation rejection for one Model_Input record.

    Carries the offending record identifier and the field at fault so the
    caller can report exactly which record and which field failed (Requirement
    1.9, 2.3, 2.4, 2.5, 2.6). The original record is preserved unchanged: this
    error only describes the problem, it never mutates the source data.

    Attributes:
        record_id: Identifier of the rejected record (e.g. a constants key, a
            ``route_id:option`` pair, a canal state name, a fuel type).
        field: The mandatory field that is absent or invalid.
        detail: Human-readable description, including any unrecognized value.
    """

    def __init__(self, record_id: str, field: str, detail: str) -> None:
        super().__init__(f"{record_id}: {field}: {detail}")
        self.record_id = record_id
        self.field = field
        self.detail = detail


# --- Status vocabulary -----------------------------------------------------

#: The four statuses permitted on a typed core Model_Input (Requirement 2.2).
_CORE_STATUSES = {s.value for s in Status}

#: Non-core CSV status strings that are mapped to the closest valid
#: :class:`Status` for *typed computational* fields, with the original string
#: preserved in the ``method`` note. Context-only keys keep their raw string.
_STATUS_ALIASES = {
    "secondary_source": Status.APPROXIMATE,
    "analyst_estimate": Status.APPROXIMATE,
}


# --- Small CSV helpers -----------------------------------------------------


def _read_csv(data_dir: Path, filename: str) -> pd.DataFrame:
    """Read one required CSV read-only, aborting with a naming error on failure.

    ``pandas.read_csv`` opens the file read-only and performs no write to it,
    satisfying Requirement 1.4. Any failure (missing file, parse error, empty
    file) is surfaced as a :class:`LoaderError` that names the file and produces
    no partial data (Requirement 1.8).
    """
    path = data_dir / filename
    if not path.is_file():
        raise LoaderError(
            f"Required data file is missing: {filename}", file=filename
        )
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - exercised via unit tests
        raise LoaderError(
            f"Required data file could not be read: {filename} ({exc})",
            file=filename,
        ) from exc
    if frame.empty:
        raise LoaderError(
            f"Required data file is empty: {filename}", file=filename
        )
    return frame


def _clean(value: Any) -> str:
    """Normalize a raw CSV cell to a trimmed string ("" for absent)."""
    if value is None:
        return ""
    text = str(value).strip()
    # pandas with keep_default_na=False yields "" for blanks, but guard anyway.
    if text.lower() in {"nan", "none"}:
        return ""
    return text


def _parse_date(value: str) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` retrieval date, or ``None`` when absent."""
    text = _clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_float(value: str) -> float | None:
    """Parse a numeric cell to ``float``, or ``None`` when not a plain number."""
    text = _clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# --- Provenance validation (Task 2.2) --------------------------------------


def _resolve_status(
    record_id: str,
    raw_status: str,
    *,
    strict: bool,
) -> tuple[Status, str | None]:
    """Resolve a raw CSV status string to a :class:`Status`.

    For typed core fields (``strict=True``) a status must be one of the four
    allowed values, or a known alias mapped to the closest valid status (with
    the original string returned as a note). An unrecognized, unmappable status
    is rejected with a :class:`ValidationError` naming the record and the
    offending value (Requirement 2.3).

    Returns:
        A ``(status, note)`` pair where ``note`` records the original string
        when an alias mapping was applied, else ``None``.
    """
    text = _clean(raw_status)
    if not text:
        raise ValidationError(record_id, "status", "status field is missing")
    if text in _CORE_STATUSES:
        return Status(text), None
    if strict and text in _STATUS_ALIASES:
        mapped = _STATUS_ALIASES[text]
        return mapped, f"original status '{text}' mapped to '{mapped.value}'"
    raise ValidationError(
        record_id, "status", f"unrecognized status value '{text}'"
    )


def _make_provenanced(
    record_id: str,
    *,
    value: float | str | None,
    unit: str,
    rationale: str,
    raw_status: str,
    retrieved_on: date | None = None,
    method: str | None = None,
    derived_from: tuple[str, ...] = (),
    derivation: str | None = None,
    strict_status: bool = True,
) -> ProvenancedValue:
    """Build a validated :class:`ProvenancedValue`, enforcing every rule.

    Enforces the full provenance contract on one Model_Input and rejects with a
    :class:`ValidationError` that names the record and offending field whenever
    a mandatory field is absent or invalid (Requirement 1.9, 2.3, 2.4, 2.5,
    2.6). The original record is never mutated.

    Rules enforced:
        * ``value`` present (non-empty) — Requirement 2.6.
        * ``unit`` present — Requirement 2.6.
        * ``rationale`` (source/assumption) present — Requirement 2.6.
        * ``status`` present and valid for the field — Requirement 2.3, 2.5.
        * ``derived`` status requires non-empty ``derived_from`` AND a non-empty
          derivation/method — Requirement 2.4.
    """
    unit_text = _clean(unit)
    rationale_text = _clean(rationale)

    value_absent = value is None or (isinstance(value, str) and not _clean(value))
    if value_absent:
        raise ValidationError(record_id, "value", "value field is missing")
    if not unit_text:
        raise ValidationError(record_id, "unit", "unit field is missing")
    if not rationale_text:
        raise ValidationError(
            record_id, "rationale", "source or assumption rationale is missing"
        )

    status, alias_note = _resolve_status(
        record_id, raw_status, strict=strict_status
    )

    # Merge any alias note into the method so the original string is retained.
    method_text = _clean(method) if method is not None else ""
    if alias_note:
        method_text = (
            f"{method_text}; {alias_note}" if method_text else alias_note
        )
    final_method = method_text or None

    if status is Status.DERIVED:
        derivation_text = _clean(derivation) if derivation else ""
        # Allow the method to stand in as the derivation description.
        if not derivation_text and final_method:
            derivation_text = final_method
        if not derived_from or not derivation_text:
            raise ValidationError(
                record_id,
                "derived_from/method",
                "a 'derived' input requires non-empty derived_from and a "
                "non-empty derivation/method",
            )
        derivation = derivation_text

    return ProvenancedValue(
        value=value if not isinstance(value, str) else _clean(value),
        unit=unit_text,
        rationale=rationale_text,
        status=status,
        retrieved_on=retrieved_on,
        method=final_method,
        derived_from=tuple(derived_from),
        derivation=derivation,
    )


# --- Record builders (Task 2.1) --------------------------------------------


def _build_route_option(row: pd.Series, errors: list[ValidationError]) -> RouteOption | None:
    """Build one :class:`RouteOption` from a routes.csv row.

    ``distance_nm`` becomes a :class:`ProvenancedValue` (status from the row,
    rationale from ``source``, ``retrieved_on`` parsed, ``method`` from the
    ``method`` column). A row lacking a distance yields ``distance_nm=None`` so
    the journey-time calculation is disabled downstream (Requirement 6.6).
    Provenance failures are collected rather than raised immediately.
    """
    route_id = _clean(row.get("route_id"))
    option = _clean(row.get("option"))
    record_id = f"routes[{route_id}:{option}]"

    distance = _parse_float(row.get("distance_nm"))
    distance_pv: ProvenancedValue | None = None
    if distance is not None:
        try:
            distance_pv = _make_provenanced(
                record_id,
                value=distance,
                unit="nm",
                rationale=row.get("source", ""),
                raw_status=row.get("status", ""),
                retrieved_on=_parse_date(row.get("retrieved_on", "")),
                method=_clean(row.get("method")) or None,
            )
        except ValidationError as err:
            errors.append(err)
            return None

    # Route-option provenance itself (status "approximate" for v1 distances).
    try:
        option_pv = _make_provenanced(
            f"{record_id}.provenance",
            value=option or route_id,
            unit="route_option",
            rationale=row.get("source", ""),
            raw_status=row.get("status", ""),
            retrieved_on=_parse_date(row.get("retrieved_on", "")),
            method=_clean(row.get("method")) or None,
        )
    except ValidationError as err:
        errors.append(err)
        return None

    return RouteOption(
        route_id=route_id,
        origin=_clean(row.get("origin")),
        destination=_clean(row.get("destination")),
        option=option,  # type: ignore[arg-type]
        distance_nm=distance_pv,
        origin_lon=_parse_float(row.get("origin_lon")) or 0.0,
        origin_lat=_parse_float(row.get("origin_lat")) or 0.0,
        destination_lon=_parse_float(row.get("destination_lon")) or 0.0,
        destination_lat=_parse_float(row.get("destination_lat")) or 0.0,
        passages=_clean(row.get("passages")),
        provenance=option_pv,
    )


def _build_od_pairs(
    frame: pd.DataFrame, errors: list[ValidationError]
) -> tuple[ODPair, ...]:
    """Group routes.csv rows by ``route_id`` into :class:`ODPair` records."""
    by_route: dict[str, dict[str, RouteOption]] = {}
    order: list[str] = []
    for _, row in frame.iterrows():
        route_id = _clean(row.get("route_id"))
        option = _clean(row.get("option"))
        if not route_id or option not in {"panama", "suez"}:
            errors.append(
                ValidationError(
                    f"routes[{route_id}:{option}]",
                    "option",
                    "route row must have a route_id and option in "
                    "{panama, suez}",
                )
            )
            continue
        built = _build_route_option(row, errors)
        if built is None:
            continue
        if route_id not in by_route:
            by_route[route_id] = {}
            order.append(route_id)
        by_route[route_id][option] = built

    pairs: list[ODPair] = []
    for route_id in order:
        options = by_route[route_id]
        panama = options.get("panama")
        suez = options.get("suez")
        sample = panama or suez
        pairs.append(
            ODPair(
                route_id=route_id,
                origin=sample.origin if sample else "",
                destination=sample.destination if sample else "",
                panama=panama,
                suez=suez,
            )
        )
    return tuple(pairs)


#: The computational constant keys the core consumes, each parsed to float and
#: carried as a named :class:`Constants` field. Everything else goes to context.
_COMPUTATIONAL_KEYS = {
    "ship_capacity_teu",
    "load_factor",
    "default_speed_kn",
    "base_speed_kn",
    "base_fuel_t_per_day",
    "speed_exponent",
    "bunker_price_usd_per_t",
    "reference_draft_ft",
    "canal_wait_days_default",
}


def _build_constants(
    frame: pd.DataFrame, errors: list[ValidationError]
) -> Constants | None:
    """Build the typed :class:`Constants` from constants.csv.

    Only the computational keys in :data:`_COMPUTATIONAL_KEYS` are parsed to
    float and validated strictly (status must resolve to the four-value
    vocabulary, aliases permitted). Range/context keys (e.g. ``"34-36"``) and
    all other rows are kept permissively as ``str`` context values and are NOT
    subject to the strict status rule. ``containers_lost_per_10cm_draft_cut``
    goes to context only (Requirement 10.2).
    """
    computational: dict[str, ProvenancedValue] = {}
    context: dict[str, ProvenancedValue] = {}

    for _, row in frame.iterrows():
        key = _clean(row.get("key"))
        if not key:
            errors.append(
                ValidationError("constants[<blank>]", "key", "key is missing")
            )
            continue
        record_id = f"constants[{key}]"
        raw_value = _clean(row.get("value"))
        unit = row.get("unit", "")
        rationale = row.get("source", "")
        raw_status = row.get("status", "")
        notes = _clean(row.get("notes"))

        if key in _COMPUTATIONAL_KEYS:
            parsed = _parse_float(raw_value)
            if parsed is None:
                errors.append(
                    ValidationError(
                        record_id,
                        "value",
                        f"computational key must be numeric, got '{raw_value}'",
                    )
                )
                continue
            # speed_exponent carries status 'derived': populate derived_from and
            # derivation from the source/notes so it satisfies Requirement 2.4.
            derived_from: tuple[str, ...] = ()
            derivation: str | None = None
            if _clean(raw_status) == Status.DERIVED.value:
                derived_from = ("base_fuel_t_per_day", "base_speed_kn")
                derivation = _clean(rationale) or notes or None
            try:
                computational[key] = _make_provenanced(
                    record_id,
                    value=parsed,
                    unit=unit,
                    rationale=rationale,
                    raw_status=raw_status,
                    method=notes or None,
                    derived_from=derived_from,
                    derivation=derivation,
                    strict_status=True,
                )
            except ValidationError as err:
                errors.append(err)
        else:
            # Context-only key: permissive. Keep raw string value; don't enforce
            # the four-value status rule. Still require value/unit/rationale to
            # be present so the record is meaningfully provenanced.
            context[key] = _make_context_value(
                record_id,
                raw_value=raw_value,
                unit=unit,
                rationale=rationale,
                raw_status=raw_status,
                notes=notes,
                errors=errors,
            )

    if errors:
        # Defer raising until all constants validated so the caller can report
        # every offending record at once.
        return None

    missing = sorted(_COMPUTATIONAL_KEYS - computational.keys())
    if missing:
        for key in missing:
            errors.append(
                ValidationError(
                    f"constants[{key}]", "value", "required computational key is absent"
                )
            )
        return None

    return Constants(
        ship_capacity_teu=computational["ship_capacity_teu"],
        load_factor=computational["load_factor"],
        default_speed_kn=computational["default_speed_kn"],
        base_speed_kn=computational["base_speed_kn"],
        base_fuel_t_per_day=computational["base_fuel_t_per_day"],
        speed_exponent=computational["speed_exponent"],
        bunker_price_usd_per_t=computational["bunker_price_usd_per_t"],
        reference_draft_ft=computational["reference_draft_ft"],
        canal_wait_days_default=computational["canal_wait_days_default"],
        context=context,
    )


def _make_context_value(
    record_id: str,
    *,
    raw_value: str,
    unit: Any,
    rationale: Any,
    raw_status: Any,
    notes: str,
    errors: list[ValidationError],
) -> ProvenancedValue:
    """Build a permissive context :class:`ProvenancedValue` (non-core key).

    Context keys are exempt from the four-value status rule: a non-core status
    string is retained verbatim as a note and the status is recorded as
    ``approximate`` so the typed field is well-formed. Value/unit/rationale must
    still be present (Requirement 2.6); a missing one is collected as an error.
    """
    status_text = _clean(raw_status)
    if status_text in _CORE_STATUSES:
        status = Status(status_text)
        method = notes or None
    else:
        status = Status.APPROXIMATE
        note = f"context status '{status_text or 'absent'}'"
        method = f"{notes}; {note}" if notes else note

    unit_text = _clean(unit)
    rationale_text = _clean(rationale)
    if not raw_value:
        errors.append(ValidationError(record_id, "value", "value field is missing"))
    if not unit_text:
        errors.append(ValidationError(record_id, "unit", "unit field is missing"))
    if not rationale_text:
        errors.append(
            ValidationError(record_id, "rationale", "rationale is missing")
        )

    return ProvenancedValue(
        value=raw_value,
        unit=unit_text,
        rationale=rationale_text,
        status=status,
        method=method,
    )


def _build_canal_states(
    frame: pd.DataFrame, errors: list[ValidationError]
) -> tuple[CanalState, ...]:
    """Build :class:`CanalState` records from canal_states.csv.

    ``max_draft_ft`` and ``daily_slots`` are kept as :class:`ProvenancedValue`
    (value may be a range ``str``). Both are booking-context/draft-context only.
    """
    states: list[CanalState] = []
    for _, row in frame.iterrows():
        state = _clean(row.get("state"))
        record_id = f"canal_states[{state}]"
        rationale = row.get("source", "")
        raw_status = row.get("status", "")
        notes = _clean(row.get("notes")) or None

        draft_raw = _clean(row.get("max_draft_ft"))
        slots_raw = _clean(row.get("daily_slots"))
        draft_val: float | str | None = _parse_float(draft_raw)
        if draft_val is None:
            draft_val = draft_raw or None
        slots_val: float | str | None = _parse_float(slots_raw)
        if slots_val is None:
            slots_val = slots_raw or None

        try:
            max_draft = _make_provenanced(
                f"{record_id}.max_draft_ft",
                value=draft_val,
                unit="ft",
                rationale=rationale,
                raw_status=raw_status,
                method=notes,
            )
            daily_slots = _make_provenanced(
                f"{record_id}.daily_slots",
                value=slots_val,
                unit="slots/day",
                rationale=rationale,
                raw_status=raw_status,
                method=notes,
            )
            provenance = _make_provenanced(
                f"{record_id}.provenance",
                value=state,
                unit="canal_state",
                rationale=rationale,
                raw_status=raw_status,
                method=notes,
            )
        except ValidationError as err:
            errors.append(err)
            continue

        states.append(
            CanalState(
                state=state,
                max_draft_ft=max_draft,
                daily_slots=daily_slots,
                period=_clean(row.get("period")),
                provenance=provenance,
            )
        )
    return tuple(states)


def _build_container_units(
    frame: pd.DataFrame, errors: list[ValidationError]
) -> tuple[ContainerUnit, ...]:
    """Build :class:`ContainerUnit` records from container_units.csv."""
    units: list[ContainerUnit] = []
    for _, row in frame.iterrows():
        container_type = _clean(row.get("container_type"))
        record_id = f"container_units[{container_type}]"
        teu = _parse_float(row.get("teu_per_container"))
        if teu is None:
            errors.append(
                ValidationError(
                    record_id, "teu_per_container", "teu_per_container is missing"
                )
            )
            continue
        try:
            provenance = _make_provenanced(
                f"{record_id}.provenance",
                value=int(teu),
                unit="TEU/container",
                rationale=row.get("source", ""),
                raw_status=row.get("status", ""),
                retrieved_on=_parse_date(row.get("retrieved_on", "")),
                method=_clean(row.get("notes")) or None,
            )
        except ValidationError as err:
            errors.append(err)
            continue
        units.append(
            ContainerUnit(
                container_type=container_type,  # type: ignore[arg-type]
                teu_per_container=int(teu),
                provenance=provenance,
            )
        )
    return tuple(units)


def _build_emission_factors(
    frame: pd.DataFrame, errors: list[ValidationError]
) -> tuple[EmissionFactor, ...]:
    """Build :class:`EmissionFactor` records from emission_factors.csv."""
    factors: list[EmissionFactor] = []
    for _, row in frame.iterrows():
        fuel_type = _clean(row.get("fuel_type"))
        record_id = f"emission_factors[{fuel_type}]"
        co2 = _parse_float(row.get("co2_t_per_fuel_t"))
        unit = _clean(row.get("unit"))
        try:
            co2_pv = _make_provenanced(
                record_id,
                value=co2,
                unit=unit,
                rationale=row.get("source", ""),
                raw_status=row.get("status", ""),
                retrieved_on=_parse_date(row.get("retrieved_on", "")),
                method=_clean(row.get("notes")) or None,
            )
        except ValidationError as err:
            errors.append(err)
            continue
        factors.append(
            EmissionFactor(
                fuel_type=fuel_type,
                co2_t_per_fuel_t=co2_pv,
                scope=_clean(row.get("scope")),
                unit=unit,
            )
        )
    return tuple(factors)


# --- Public entry point (Task 2.1) -----------------------------------------


def load_required(data_dir: Path) -> RequiredData:
    """Load and validate all required CanalCast data from ``data_dir``.

    Reads routes, constants, canal_states, container_units, and
    emission_factors read-only, builds typed records, and validates the
    provenance of every Model_Input as each record is built (Tasks 2.1 & 2.2).

    Args:
        data_dir: Directory holding the required CSV files (typically
            ``Path("data")``).

    Returns:
        A fully populated :class:`RequiredData`.

    Raises:
        LoaderError: If a required file is missing/unreadable (naming the file,
            Requirement 1.8), or if any provenance validation fails. In the
            latter case every offending record is reported together and NO
            partial Model_Input data is produced (Requirement 1.9, 2.3-2.6).
    """
    data_dir = Path(data_dir)

    # Read every required file first; a missing/unreadable file aborts here
    # (naming the file) BEFORE any Model_Input data is built (Requirement 1.8).
    routes_df = _read_csv(data_dir, "routes.csv")
    constants_df = _read_csv(data_dir, "constants.csv")
    canal_states_df = _read_csv(data_dir, "canal_states.csv")
    container_units_df = _read_csv(data_dir, "container_units.csv")
    emission_factors_df = _read_csv(data_dir, "emission_factors.csv")

    errors: list[ValidationError] = []

    od_pairs = _build_od_pairs(routes_df, errors)
    constants = _build_constants(constants_df, errors)
    canal_states = _build_canal_states(canal_states_df, errors)
    container_units = _build_container_units(container_units_df, errors)
    emission_factors = _build_emission_factors(emission_factors_df, errors)

    if errors:
        # Collect and raise all provenance rejections; produce no partial data.
        detail = "; ".join(str(e) for e in errors)
        raise LoaderError(
            f"Provenance validation failed for {len(errors)} record(s): {detail}",
            errors=tuple(errors),
        )

    assert constants is not None  # guaranteed when errors is empty

    return RequiredData(
        od_pairs=od_pairs,
        constants=constants,
        canal_states=canal_states,
        container_units=container_units,
        emission_factors=emission_factors,
    )


# --- Optional-series loading (Task 2.3) ------------------------------------

#: The canonical optional historical series CanalCast knows about. Each name
#: maps to ``<name>.csv`` in the data folder. These never block loading: a
#: missing or unreadable series is recorded as unavailable and loading
#: continues (Requirement 4.2, 4.3).
_OPTIONAL_SERIES: tuple[str, ...] = (
    "canal_events",
    "transits",
    "oni",
    "roni",
    "enso_context",
    "surcharges",
)


def _read_optional_csv(data_dir: Path, filename: str) -> pd.DataFrame | None:
    """Read one optional CSV read-only WITHOUT aborting on absence.

    Unlike :func:`_read_csv` (which raises :class:`LoaderError` for a missing or
    unreadable required file), this helper is non-raising by contract: an
    optional series must never block loading (Requirement 4.2, 4.3). It reads
    the file read-only and makes NO network call (Requirement 1.7).

    Returns:
        * The parsed :class:`~pandas.DataFrame` when the file exists and is
          readable and non-empty.
        * ``None`` when the file does not exist (caller records "not found").

    Raises:
        Exception: Propagated to the caller ONLY for a present-but-unreadable
            file (parse error / empty), which the caller translates into a
            "could not be read" unavailable record. The caller catches every
            exception, so this never escapes :func:`load_optional`.
    """
    path = data_dir / filename
    if not path.is_file():
        return None
    # read-only open; no write to the source CSV (Requirement 1.4), no network.
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if frame.empty:
        raise ValueError(f"optional series file is empty: {filename}")
    return frame


def _series_provenance(name: str, frame: pd.DataFrame) -> ProvenancedValue | None:
    """Summarize an available series' source as a :class:`ProvenancedValue`.

    Retains the series' provenance (Requirement 4.1) when a ``source`` column is
    present, taking the first non-empty source/status/retrieved_on as the
    representative provenance of the series. Returns ``None`` when the series has
    no ``source`` column so no provenance can be summarized.
    """
    if "source" not in frame.columns:
        return None

    source = ""
    raw_status = ""
    retrieved = ""
    for _, row in frame.iterrows():
        candidate = _clean(row.get("source"))
        if candidate:
            source = candidate
            raw_status = _clean(row.get("status"))
            retrieved = _clean(row.get("retrieved_on"))
            break

    if not source:
        return None

    status = Status(raw_status) if raw_status in _CORE_STATUSES else Status.SOURCED
    note = None if raw_status in _CORE_STATUSES else (
        f"series status '{raw_status}'" if raw_status else None
    )
    return ProvenancedValue(
        value=name,
        unit="series",
        rationale=source,
        status=status,
        retrieved_on=_parse_date(retrieved),
        method=note,
    )


def _rows_of(frame: pd.DataFrame) -> tuple[dict[str, object], ...]:
    """Convert a series frame to an immutable tuple of row dicts.

    Each cell is normalized to a trimmed ``str`` (``""`` for blanks) so the rows
    have the expected ``tuple[Mapping[str, object], ...]`` shape consumed by
    :class:`~canalcast.models.OptionalSeries`.
    """
    columns = list(frame.columns)
    rows: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        rows.append({col: _clean(row.get(col)) for col in columns})
    return tuple(rows)


def load_optional(data_dir: Path) -> dict[str, OptionalSeries]:
    """Load every known optional historical series, never blocking on failure.

    For each name in :data:`_OPTIONAL_SERIES` the matching ``<name>.csv`` is
    read read-only. The outcome is recorded per series and loading ALWAYS
    continues to the next series; this function never raises on an optional
    series and makes NO network call (Requirement 1.7, 4.2, 4.3):

    * Present and readable: ``available=True``, ``reason=None``, ``rows`` is a
      tuple of row dicts, ``provenance`` summarizes the source when a ``source``
      column exists else ``None`` (Requirement 4.1).
    * Absent: ``available=False``, ``reason="not found"``, ``rows=()``
      (Requirement 4.2).
    * Present but unreadable (parse error / empty): ``available=False``,
      ``reason="could not be read"``, ``rows=()`` (Requirement 4.3).

    Args:
        data_dir: Directory holding the optional CSV files (typically
            ``Path("data")``).

    Returns:
        A mapping from series name to its :class:`OptionalSeries` record, with
        one entry per name in :data:`_OPTIONAL_SERIES`.
    """
    data_dir = Path(data_dir)
    result: dict[str, OptionalSeries] = {}

    for name in _OPTIONAL_SERIES:
        filename = f"{name}.csv"
        try:
            frame = _read_optional_csv(data_dir, filename)
        except Exception:
            # Present but unreadable (parse error / empty): record and continue.
            result[name] = OptionalSeries(
                name=name,
                available=False,
                reason="could not be read",
                rows=(),
            )
            continue

        if frame is None:
            # Absent: record "not found" and continue to the next series.
            result[name] = OptionalSeries(
                name=name,
                available=False,
                reason="not found",
                rows=(),
            )
            continue

        result[name] = OptionalSeries(
            name=name,
            available=True,
            reason=None,
            rows=_rows_of(frame),
            provenance=_series_provenance(name, frame),
        )

    return result


# --- Public entry point (Task 2.3) -----------------------------------------


def load_all(data_dir: Path) -> LoadResult:
    """Load required data then optional series into a single :class:`LoadResult`.

    Calls :func:`load_required` first — a missing/unreadable required file or a
    provenance failure correctly propagates as a :class:`LoaderError` and
    produces no partial data (Requirement 1.8). Then calls :func:`load_optional`,
    which never raises, and assembles the combined result. No network call is
    made anywhere (Requirement 1.7).

    Args:
        data_dir: Directory holding the CSV files (typically ``Path("data")``).

    Returns:
        A :class:`LoadResult` pairing the validated :class:`RequiredData` with
        the per-series :class:`OptionalSeries` availability records.

    Raises:
        LoaderError: Propagated from :func:`load_required` on a required-file or
            provenance problem.
    """
    data_dir = Path(data_dir)
    required = load_required(data_dir)
    optional = load_optional(data_dir)
    return LoadResult(required=required, optional=optional)
