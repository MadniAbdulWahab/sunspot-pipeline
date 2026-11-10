"""Derived products: monthly means from daily values and the 13-month smoothed series."""

from __future__ import annotations

import numpy as np
import pandas as pd

# SILSO "tapered boxcar": 13 months centred on the target month, weight 1 for the inner
# 11 months and 0.5 for the months at -6 and +6, normalised by 1/12.
SMOOTHING_WEIGHTS = np.array([0.5] + [1.0] * 11 + [0.5]) / 12.0
HALF_WINDOW = 6


def round_half_up(values: pd.Series | np.ndarray, decimals: int = 1) -> pd.Series | np.ndarray:
    """Round like SILSO does (x.x5 goes up), not like Python/numpy (half to even).

    The tiny epsilon stops values such as 0.15, which is stored as 0.1499999..., from
    rounding down. It is far below the published precision.
    """

    factor = 10.0**decimals
    scaled = np.asarray(values, dtype="float64") * factor
    rounded = np.sign(scaled) * np.floor(np.abs(scaled) + 0.5 + 1e-9) / factor
    if isinstance(values, pd.Series):
        return pd.Series(rounded, index=values.index, name=values.name)
    return rounded


def tapered_13_month(values: pd.Series) -> pd.Series:
    """13-month tapered running mean of a series indexed by consecutive month starts.

    A smoothed value needs all 13 months of input: if any of them is missing the result is
    NaN rather than a renormalised mean over fewer months. The first and last 6 months are
    always NaN, which matches the published SILSO file.
    """

    idx = values.index
    if len(idx) > 1:
        expected = pd.date_range(idx[0], idx[-1], freq="MS")
        if not idx.equals(expected):
            raise ValueError("tapered_13_month needs a complete, ordered monthly index")
    x = values.to_numpy(dtype="float64")
    out = np.full(len(x), np.nan)
    if len(x) >= len(SMOOTHING_WEIGHTS):
        # The weights are symmetric, so convolution and correlation are the same thing.
        # NaN anywhere in a window propagates to that window's result.
        out[HALF_WINDOW:-HALF_WINDOW] = np.convolve(x, SMOOTHING_WEIGHTS, mode="valid")
    return pd.Series(out, index=idx, name=values.name)


def derive_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Calendar-month means of the usable daily values.

    Days that are missing (-1) or flagged as bad are left out of the mean, and the number of
    days actually used is kept next to each value, so thin months are visible.
    """

    d = daily[daily["date"].notna()].copy()
    d["month_start"] = d["date"].dt.to_period("M").dt.to_timestamp()
    grouped = d.groupby("month_start")
    used = d[d["usable"]].groupby("month_start")

    full = pd.date_range(d["month_start"].min(), d["month_start"].max(), freq="MS")
    out = pd.DataFrame(index=pd.DatetimeIndex(full, name="date"))
    out["sn_mean_raw"] = used["value"].mean()
    out["n_days_used"] = used["value"].count()
    out["n_days_in_file"] = grouped.size()
    out["provisional_days"] = used["flag_provisional"].sum()
    out = out.fillna({"n_days_used": 0, "n_days_in_file": 0, "provisional_days": 0})
    out[["n_days_used", "n_days_in_file", "provisional_days"]] = out[
        ["n_days_used", "n_days_in_file", "provisional_days"]
    ].astype("int64")
    out["n_days_in_month"] = out.index.days_in_month
    out["sn_mean"] = round_half_up(out["sn_mean_raw"])
    out["provisional"] = out["provisional_days"] > 0
    out["flag_no_data"] = out["n_days_used"] == 0
    out["flag_partial_month"] = (out["n_days_used"] > 0) & (out["n_days_used"] < out["n_days_in_month"])
    return out.reset_index()


def derive_smoothed(monthly: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Apply the tapered 13-month mean to one monthly value column."""

    m = monthly.set_index("date").sort_index()
    smoothed_raw = tapered_13_month(m[value_col])
    out = pd.DataFrame(index=m.index)
    out["sn_smoothed_raw"] = smoothed_raw
    out["sn_smoothed"] = round_half_up(smoothed_raw)
    # A smoothed value counts as provisional if any month in its window is provisional.
    prov = m["provisional"].astype(float)
    out["provisional"] = prov.rolling(len(SMOOTHING_WEIGHTS), center=True, min_periods=1).max().astype(bool)
    return out.reset_index()


def published_monthly_series(monthly_frame: pd.DataFrame) -> pd.DataFrame:
    """SILSO's own monthly file reduced to date/value/provisional on a full monthly index."""

    m = monthly_frame[monthly_frame["date"].notna() & ~monthly_frame["flag_duplicate"]]
    m = m.set_index("date").sort_index()
    full = pd.date_range(m.index.min(), m.index.max(), freq="MS")
    out = pd.DataFrame(index=pd.DatetimeIndex(full, name="date"))
    out["sn"] = m["value"]
    out["provisional"] = m["flag_provisional"].reindex(full).fillna(False).astype(bool)
    return out.reset_index()
