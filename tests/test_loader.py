"""Unit tests for the CanalCast Data_Loader (Task 2.4).

These cover the loader's branch behavior with small, synthetic CSVs written into
``tmp_path`` (the real ``data/`` folder is read-only and never modified):

* Required-file-missing abort — a missing required file aborts with a
  :class:`LoaderError` naming the file, and no partial data is produced
  (Requirements 1.8).
* Each provenance-rejection branch — a constant missing its unit, missing its
  source/rationale, carrying an unrecognized status, and a ``derived`` input
  lacking its derivation each raise with a :class:`ValidationError` naming the
  offending record and field (Requirements 1.9, 2.3, 2.4).
* Optional-series availability — available (with provenance retained), not
  found, and could-not-be-read, with :func:`load_optional` never raising
  (Requirements 4.2, 4.3).
* ``load_all`` over the real ``data/`` folder returns the expected
  :class:`LoadResult`.

Requirements: 1.8, 1.9, 2.3, 2.4, 4.2, 4.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.canalcast.loader import (
    LoaderError,
    ValidationError,
    load_all,
    load_optional,
    load_required,
)
from src.canalcast.models import Status

# The real data directory, resolved relative to the workspace root. Used only
# for read-only "available" / load_all assertions; never written to.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


# --- Valid-CSV helper -------------------------------------------------------
#
# These builders produce the SMALLEST required CSV set that ``load_required``
# accepts. Each corruption test starts from this valid set and corrupts exactly
# one file/row so the test targets a single branch.

# All nine computational constant keys, validly provenanced. ``speed_exponent``
# is ``derived`` with a source rationale so the loader can populate its
# derived_from/derivation and satisfy the derived-input rule (Requirement 2.4).
_VALID_CONSTANTS_ROWS = (
    # key, value, unit, source, status, notes
    ("ship_capacity_teu", "10000", "TEU", "assumption rationale", "assumption", ""),
    ("load_factor", "0.85", "fraction", "assumption rationale", "assumption", ""),
    ("default_speed_kn", "18", "knots", "Transport Geography", "approximate", ""),
    ("base_speed_kn", "22", "knots", "maritimepage.com", "approximate", ""),
    ("base_fuel_t_per_day", "175", "t/day", "maritimepage.com", "approximate", ""),
    (
        "speed_exponent",
        "3",
        "-",
        "derived: cubic law fits two sourced points",
        "derived",
        "cubic law",
    ),
    ("bunker_price_usd_per_t", "876.5", "USD/t", "Ship & Bunker", "sourced", ""),
    ("reference_draft_ft", "50.0", "ft", "ACP", "sourced", ""),
    ("canal_wait_days_default", "0", "days", "no sourced value", "assumption", ""),
)


def _write_csv(path: Path, header: str, rows: tuple[tuple[str, ...], ...]) -> None:
    """Write a minimal CSV (header + rows) with naive comma joining.

    The synthetic cells here contain no commas or quotes, so plain joining is
    sufficient and keeps the fixtures readable.
    """
    lines = [header]
    lines.extend(",".join(cell for cell in row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_valid_required(data_dir: Path) -> None:
    """Write the smallest valid set of all five required CSVs into ``data_dir``.

    * ``routes.csv`` — one ``route_id`` with a panama row and a suez row.
    * ``constants.csv`` — all nine computational keys, validly provenanced.
    * ``canal_states.csv`` — one state.
    * ``container_units.csv`` — the 20ft/40ft units.
    * ``emission_factors.csv`` — one fuel factor.

    Loading this set with ``load_required`` succeeds and produces no errors.
    """
    data_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        data_dir / "routes.csv",
        "route_id,origin,destination,option,distance_nm,origin_lon,origin_lat,"
        "destination_lon,destination_lat,passages,source,status,retrieved_on,"
        "method,notes",
        (
            (
                "r1", "Shanghai", "Boston", "panama", "10783.5", "121.8", "31.2",
                "-70.95", "42.35", "panama", "searoute", "approximate",
                "2026-10-24", "shortest route", "note",
            ),
            (
                "r1", "Shanghai", "Boston", "suez", "12271.1", "121.8", "31.2",
                "-70.95", "42.35", "suez", "searoute", "approximate",
                "2026-10-24", "shortest route", "note",
            ),
        ),
    )

    _write_csv(
        data_dir / "constants.csv",
        "key,value,unit,source,status,notes",
        _VALID_CONSTANTS_ROWS,
    )

    _write_csv(
        data_dir / "canal_states.csv",
        "state,max_draft_ft,daily_slots,period,source,status,notes",
        (
            (
                "normal_reference", "50.0", "36", "design capacity",
                "ACP summaries", "sourced", "use 36",
            ),
        ),
    )

    _write_csv(
        data_dir / "container_units.csv",
        "container_type,teu_per_container,source,status,retrieved_on,notes",
        (
            ("20ft", "1", "https://www.bts.gov", "sourced", "2026-10-24", "TEU"),
            ("40ft", "2", "https://www.bts.gov", "sourced", "2026-10-24", "FEU"),
        ),
    )

    _write_csv(
        data_dir / "emission_factors.csv",
        "fuel_type,co2_t_per_fuel_t,scope,unit,source,status,retrieved_on,notes",
        (
            (
                "HFO", "3.114", "tank_to_wake_CO2_only", "t_CO2/t_fuel",
                "https://imo.org", "sourced", "2026-10-24", "IMO MEPC",
            ),
        ),
    )


def _constants_rows_with(key: str, **overrides: str) -> tuple[tuple[str, ...], ...]:
    """Return the valid constants rows with one ``key`` row field overridden.

    ``overrides`` maps a column name (value/unit/source/status/notes) to its new
    value for the row whose constants key equals ``key``. Used to corrupt a
    single constant for the provenance-rejection tests.
    """
    columns = ("key", "value", "unit", "source", "status", "notes")
    out: list[tuple[str, ...]] = []
    for row in _VALID_CONSTANTS_ROWS:
        record = dict(zip(columns, row))
        if record["key"] == key:
            record.update(overrides)
        out.append(tuple(record[col] for col in columns))
    return tuple(out)


def _find_error(exc: LoaderError, *, field: str) -> ValidationError:
    """Return the first collected ValidationError whose field contains ``field``.

    Fails the test if no matching error was collected, surfacing the actual set
    of errors to make a mismatch easy to diagnose.
    """
    matches = [e for e in exc.errors if field in e.field]
    assert matches, (
        f"no ValidationError with field containing {field!r}; "
        f"got {[(e.record_id, e.field) for e in exc.errors]}"
    )
    return matches[0]


# --- 1. Required-file-missing abort (Requirement 1.8) -----------------------


def test_load_required_empty_dir_names_first_missing_file(tmp_path: Path) -> None:
    """A dir with no CSVs aborts with a LoaderError naming a missing file."""
    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = excinfo.value
    # routes.csv is read first, so it is the file named as missing.
    assert err.file == "routes.csv"
    assert "routes.csv" in str(err)
    assert "missing" in str(err).lower()


def test_load_required_one_missing_file_names_that_file(tmp_path: Path) -> None:
    """A dir with 4 of 5 required files aborts naming the specific missing one."""
    write_valid_required(tmp_path)
    # Remove exactly one required file (container_units.csv): 4 of 5 remain.
    (tmp_path / "container_units.csv").unlink()

    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = excinfo.value
    assert err.file == "container_units.csv"
    assert "container_units.csv" in str(err)
    # No ValidationError batch — this is a file-level abort before record build.
    assert err.errors == ()


def test_valid_required_set_loads_without_error(tmp_path: Path) -> None:
    """The valid-CSV helper produces a set that load_required accepts."""
    write_valid_required(tmp_path)
    required = load_required(tmp_path)

    assert len(required.od_pairs) == 1
    pair = required.od_pairs[0]
    assert pair.route_id == "r1"
    assert pair.panama is not None
    assert pair.suez is not None
    # speed_exponent came in as 'derived' and carries its derivation provenance.
    assert required.constants.speed_exponent.status is Status.DERIVED
    assert required.constants.speed_exponent.derived_from
    assert required.constants.speed_exponent.derivation


# --- 2. Provenance-rejection branches (Requirements 1.9, 2.3, 2.4) ----------


def test_constant_missing_unit_rejected(tmp_path: Path) -> None:
    """A computational constant missing its unit is rejected naming unit."""
    write_valid_required(tmp_path)
    _write_csv(
        tmp_path / "constants.csv",
        "key,value,unit,source,status,notes",
        _constants_rows_with("bunker_price_usd_per_t", unit=""),
    )

    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = _find_error(excinfo.value, field="unit")
    assert "bunker_price_usd_per_t" in err.record_id


def test_constant_missing_source_rationale_rejected(tmp_path: Path) -> None:
    """A computational constant missing its source/rationale is rejected."""
    write_valid_required(tmp_path)
    _write_csv(
        tmp_path / "constants.csv",
        "key,value,unit,source,status,notes",
        _constants_rows_with("bunker_price_usd_per_t", source=""),
    )

    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = _find_error(excinfo.value, field="rationale")
    assert "bunker_price_usd_per_t" in err.record_id


def test_constant_unrecognized_status_rejected(tmp_path: Path) -> None:
    """A computational constant with a bogus (non-alias) status is rejected.

    The error names the status field and echoes the unrecognized value
    (Requirement 2.3).
    """
    write_valid_required(tmp_path)
    _write_csv(
        tmp_path / "constants.csv",
        "key,value,unit,source,status,notes",
        _constants_rows_with("bunker_price_usd_per_t", status="bogus"),
    )

    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = _find_error(excinfo.value, field="status")
    assert "bunker_price_usd_per_t" in err.record_id
    assert "bogus" in err.detail


def test_derived_input_missing_derivation_rejected(tmp_path: Path) -> None:
    """A 'derived' input lacking derived_from/derivation is rejected (Req 2.4).

    Exercised via an emission-factor row: the emission builder passes no
    derived_from/derivation, so a 'derived' status row with a present source
    isolates the derived-input rule cleanly.
    """
    write_valid_required(tmp_path)
    _write_csv(
        tmp_path / "emission_factors.csv",
        "fuel_type,co2_t_per_fuel_t,scope,unit,source,status,retrieved_on,notes",
        (
            (
                "HFO", "3.114", "tank_to_wake_CO2_only", "t_CO2/t_fuel",
                "https://imo.org", "derived", "2026-10-24", "",
            ),
        ),
    )

    with pytest.raises(LoaderError) as excinfo:
        load_required(tmp_path)
    err = _find_error(excinfo.value, field="derived_from")
    assert "HFO" in err.record_id
    assert err.detail


# --- 3. Optional-series branches (Requirements 4.2, 4.3) --------------------


def test_load_optional_available_from_real_data() -> None:
    """Over the real data/ dir, every known series is available with rows."""
    series = load_optional(DATA_DIR)

    assert series, "expected at least one known optional series"
    for name, record in series.items():
        assert record.available is True, f"{name} should be available"
        assert record.reason is None
        assert record.rows, f"{name} should have populated rows"

    # Series with a 'source' column retain provenance (Requirement 4.1).
    oni = series["oni"]
    assert oni.provenance is not None
    assert oni.provenance.rationale  # a source URL was retained


def test_load_optional_not_found(tmp_path: Path) -> None:
    """An empty dir yields each known series unavailable with 'not found'."""
    series = load_optional(tmp_path)

    assert series
    for name, record in series.items():
        assert record.available is False, f"{name} should be unavailable"
        assert record.reason == "not found", f"{name} reason mismatch"
        assert record.rows == ()


def test_load_optional_unreadable_does_not_raise(tmp_path: Path) -> None:
    """An empty oni.csv makes that series 'could not be read'; no raise."""
    # Write an empty file: present but unreadable (parse yields empty frame).
    (tmp_path / "oni.csv").write_text("", encoding="utf-8")

    # load_optional must NOT raise on an unreadable optional series.
    series = load_optional(tmp_path)

    oni = series["oni"]
    assert oni.available is False
    assert oni.reason == "could not be read"
    assert oni.rows == ()
    # Other series in the empty dir remain simply "not found".
    assert series["roni"].reason == "not found"


# --- 4. load_all over the real data/ folder ---------------------------------


def test_load_all_real_data_has_three_od_pairs_and_all_series() -> None:
    """load_all(data/) returns 3 OD pairs and every optional series available."""
    result = load_all(DATA_DIR)

    assert len(result.required.od_pairs) == 3
    assert result.optional
    for name, record in result.optional.items():
        assert record.available is True, f"{name} should be available"
        assert record.reason is None
