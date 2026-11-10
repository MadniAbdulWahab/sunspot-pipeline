from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import FIXED_NOW, HISTORIC, RECENT

from sunspot_pipeline.config import DAILY, MONTHLY, SMOOTHED
from sunspot_pipeline.process import (
    SMOOTHING_WEIGHTS,
    derive_monthly,
    derive_smoothed,
    published_monthly_series,
    round_half_up,
    tapered_13_month,
)
from sunspot_pipeline.reconcile import compare
from sunspot_pipeline.validate import validate


def load(folder, source):
    return validate((folder / source.filename).read_bytes(), source, now=FIXED_NOW)


def months(n, start="2000-01-01"):
    return pd.date_range(start, periods=n, freq="MS")


# --- smoothing formula ---


def test_weights_match_silso_definition():
    assert len(SMOOTHING_WEIGHTS) == 13
    assert SMOOTHING_WEIGHTS.sum() == pytest.approx(1.0)
    assert SMOOTHING_WEIGHTS[0] == SMOOTHING_WEIGHTS[-1] == pytest.approx(0.5 / 12)
    assert np.allclose(SMOOTHING_WEIGHTS[1:-1], 1 / 12)


def test_constant_series_stays_constant_and_edges_empty():
    s = pd.Series(42.0, index=months(30))
    out = tapered_13_month(s)
    assert out.iloc[:6].isna().all() and out.iloc[-6:].isna().all()
    assert np.allclose(out.iloc[6:-6], 42.0)


def test_single_spike_is_spread_with_tapered_weights():
    s = pd.Series(0.0, index=months(25))
    s.iloc[12] = 12.0
    out = tapered_13_month(s)
    # each output month sees the spike with the weight it has in that month's window
    assert out.iloc[12] == pytest.approx(1.0)
    assert out.iloc[6] == pytest.approx(0.5) and out.iloc[18] == pytest.approx(0.5)
    assert out.iloc[7:18].sum() == pytest.approx(11.0)


def test_missing_month_blanks_every_window_that_contains_it():
    s = pd.Series(10.0, index=months(40))
    s.iloc[20] = np.nan
    out = tapered_13_month(s)
    assert out.iloc[14:27].isna().all()
    assert out.iloc[13] == pytest.approx(10.0) and out.iloc[27] == pytest.approx(10.0)


def test_smoothing_rejects_incomplete_month_index():
    s = pd.Series(1.0, index=months(20).delete(5))
    with pytest.raises(ValueError):
        tapered_13_month(s)


def test_round_half_up_differs_from_numpy_on_ties():
    values = pd.Series([32.25, 129.25, 0.15, 2.35, 7.04, 7.06])
    assert list(round_half_up(values)) == [32.3, 129.3, 0.2, 2.4, 7.0, 7.1]
    assert np.round(32.25, 1) == 32.2  # numpy/Python round half to even


def test_formula_reproduces_published_smoothed_values():
    """Smoothing SILSO's own monthly extract must give SILSO's smoothed values."""

    for folder in (HISTORIC, RECENT):
        monthly = published_monthly_series(load(folder, MONTHLY).frame)
        smoothed = derive_smoothed(monthly.rename(columns={"sn": "pub"}), "pub").set_index("date")
        published = load(folder, SMOOTHED).frame.set_index("date")["value"].dropna()
        _, summary = compare(
            "t", smoothed["sn_smoothed"].dropna(), published, derived_unrounded=smoothed["sn_smoothed_raw"]
        )
        assert summary["n"] > 0
        assert summary["mismatches"] == 0, summary["differences"]


# --- monthly means from daily values ---


def test_monthly_means_from_daily_match_published():
    derived = derive_monthly(load(HISTORIC, DAILY).frame).set_index("date")
    published = load(HISTORIC, MONTHLY).frame.set_index("date")["value"]

    assert len(derived) == 36
    feb_1824 = derived.loc["1824-02-01"]
    assert feb_1824["flag_no_data"] and np.isnan(feb_1824["sn_mean"])
    assert derived.loc["1824-04-01", "sn_mean"] == 32.3  # mean is exactly 32.25, SILSO rounds up

    ok = derived["sn_mean"].notna()
    diff = (derived.loc[ok, "sn_mean"] - published[ok.index[ok]]).abs()
    assert diff.max() < 1e-9


def test_monthly_counts_days_used():
    derived = derive_monthly(load(HISTORIC, DAILY).frame).set_index("date")
    jan_1823 = derived.loc["1823-01-01"]
    assert jan_1823["n_days_in_file"] == 31
    assert 0 < jan_1823["n_days_used"] <= 31
    assert jan_1823["flag_partial_month"] == (jan_1823["n_days_used"] < 31)


def test_recent_months_marked_provisional():
    daily = load(RECENT, DAILY)
    derived = derive_monthly(daily.frame)
    prov_months = set(daily.frame.loc[daily.frame["flag_provisional"], "date"].dt.to_period("M"))
    flagged = set(derived.loc[derived["provisional"], "date"].dt.to_period("M"))
    assert flagged == prov_months and len(flagged) > 0
