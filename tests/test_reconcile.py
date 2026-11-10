from __future__ import annotations

import pandas as pd

from sunspot_pipeline.reconcile import compare, is_rounding_tie


def series(values, start="2000-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_identical_series_pass():
    s = series([10.0, 20.5, 30.1])
    _, summary = compare("x", s, s.copy())
    assert summary["passed"] and summary["exact_matches"] == 3 and summary["mismatches"] == 0


def test_real_difference_fails():
    table, summary = compare("x", series([10.0, 20.8]), series([10.0, 20.5]))
    assert not summary["passed"]
    assert summary["mismatches"] == 1
    assert table.loc[1, "result"] == "mismatch"
    assert summary["differences"][0]["diff"] == 0.3


def test_difference_at_tolerance_boundary_passes():
    _, summary = compare("x", series([10.05]), series([10.0]))
    assert summary["passed"]


def test_one_unit_on_exact_tie_is_explained():
    # 284.55 rounds half-up to 284.6; SILSO published 284.5.
    table, summary = compare("x", series([284.6]), series([284.5]), derived_unrounded=series([284.55]))
    assert summary["passed"] and summary["rounding_ties"] == 1 and summary["mismatches"] == 0
    assert table.loc[0, "result"] == "rounding_tie"


def test_one_unit_without_tie_is_a_mismatch():
    _, summary = compare("x", series([284.6]), series([284.5]), derived_unrounded=series([284.57]))
    assert not summary["passed"] and summary["mismatches"] == 1


def test_tie_detection():
    assert list(is_rounding_tie(series([1.25, 1.24, 284.55, 0.05, 3.0]))) == [
        True,
        False,
        True,
        True,
        False,
    ]


def test_coverage_statuses():
    derived = series([1.0, None, 3.0])
    published = series([1.0, 2.0, None])
    table, summary = compare("x", derived.dropna(), published.dropna())
    assert list(table["status"]) == ["compared", "published_only", "derived_only"]
    assert summary["published_only_in_derived_range"] == ["2000-02"]
