"""Regression checks for the route dataset (data/routes.csv).

Every comparable route needs a Panama row and a Suez row with positive
distances (Requirements 11.1, 13.4). The original three routes must keep their
generated distances, and each Panama row must actually route via Panama and each
Suez row via Suez, not around a cape.
"""

from __future__ import annotations

import csv
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "routes.csv"

ORIGINAL = {
    "shanghai_boston": (10783.5, 12271.1),
    "shanghai_new_york": (10638.9, 12380.2),
    "singapore_new_york": (12672.5, 10165.3),
}


def _rows():
    with DATA.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _by_route():
    out: dict[str, dict[str, dict]] = {}
    for r in _rows():
        out.setdefault(r["route_id"], {})[r["option"]] = r
    return out


def test_every_route_has_both_options_with_positive_distance():
    routes = _by_route()
    assert len(routes) >= 10
    for rid, opts in routes.items():
        assert set(opts) == {"panama", "suez"}, rid
        for opt, row in opts.items():
            assert float(row["distance_nm"]) > 0, (rid, opt)


def test_original_three_routes_are_unchanged():
    routes = _by_route()
    for rid, (pan, suez) in ORIGINAL.items():
        assert float(routes[rid]["panama"]["distance_nm"]) == pan
        assert float(routes[rid]["suez"]["distance_nm"]) == suez


def test_each_option_routes_via_its_own_canal_and_not_the_other():
    for rid, opts in _by_route().items():
        assert opts["panama"]["passages"] == "panama", rid
        suez_passages = opts["suez"]["passages"].split(";")
        assert "suez" in suez_passages and "panama" not in suez_passages, rid


def test_route_provenance_columns_are_complete_and_approximate():
    for r in _rows():
        assert r["status"] == "approximate", r["route_id"]
        assert r["source"].startswith("https://"), r["route_id"]
        assert r["retrieved_on"], r["route_id"]
        assert r["method"].startswith("searoute 1.4.3"), r["route_id"]