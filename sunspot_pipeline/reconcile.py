"""Compare derived values with SILSO's published series."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PUBLISHED_DECIMALS, RECONCILE_TOLERANCE

EPS = 1e-9


def is_rounding_tie(unrounded: pd.Series, decimals: int = PUBLISHED_DECIMALS) -> pd.Series:
    """True where the unrounded value sits exactly half-way between two published values.

    Such a value can legitimately round either way depending on floating-point noise in
    whichever code did the rounding, so a one-unit difference there is explained.
    """

    scaled = unrounded * 10**decimals
    return (scaled - np.floor(scaled) - 0.5).abs() < 1e-6


def compare(
    name: str,
    derived: pd.Series,
    published: pd.Series,
    provisional: pd.Series | None = None,
    derived_unrounded: pd.Series | None = None,
    tolerance: float = RECONCILE_TOLERANCE,
    decimals: int = PUBLISHED_DECIMALS,
) -> tuple[pd.DataFrame, dict]:
    """Line two date-indexed series up and report where they disagree.

    Every date in either series gets a row with a status:
      compared        both values present
      derived_only    we have a value, SILSO does not (e.g. smoothing edges)
      published_only  SILSO has a value we could not derive (no daily data that month)
      both_missing    neither side has a value

    A compared row passes if |derived - published| <= tolerance. A row that fails only
    because its unrounded value is an exact half-way tie, and is off by exactly one unit of
    the published precision, is counted as an explained rounding tie, not a failure.
    """

    idx = derived.index.union(published.index)
    table = pd.DataFrame(index=pd.DatetimeIndex(idx, name="date"))
    table["derived"] = derived.reindex(idx)
    table["published"] = published.reindex(idx)
    table["derived_unrounded"] = derived_unrounded.reindex(idx) if derived_unrounded is not None else np.nan
    table["diff"] = table["derived"] - table["published"]
    table["abs_diff"] = table["diff"].abs()
    if provisional is not None:
        table["provisional"] = provisional.reindex(idx).fillna(False).astype(bool)
    else:
        table["provisional"] = False

    d_ok, p_ok = table["derived"].notna(), table["published"].notna()
    table["status"] = np.select(
        [d_ok & p_ok, d_ok & ~p_ok, ~d_ok & p_ok],
        ["compared", "derived_only", "published_only"],
        default="both_missing",
    )
    both = d_ok & p_ok
    within = table["abs_diff"] <= tolerance + EPS
    one_unit = (table["abs_diff"] - 10**-decimals).abs() < EPS
    tie = is_rounding_tie(table["derived_unrounded"]) & one_unit & ~within
    table["within_tolerance"] = within.where(both)
    table["rounding_tie"] = tie.where(both)
    table["result"] = np.select(
        [~both, within, tie], ["not_compared", "match", "rounding_tie"], default="mismatch"
    )

    cmp = table[both]

    def _stats(sub: pd.DataFrame) -> dict:
        if sub.empty:
            return {"n": 0}
        return {
            "n": int(len(sub)),
            "exact_matches": int((sub["abs_diff"] < EPS).sum()),
            "within_tolerance": int((sub["result"] == "match").sum()),
            "rounding_ties": int((sub["result"] == "rounding_tie").sum()),
            "mismatches": int((sub["result"] == "mismatch").sum()),
            "max_abs_diff": round(float(sub["abs_diff"].max()), 6),
            "mean_abs_diff": round(float(sub["abs_diff"].mean()), 6),
        }

    stats = _stats(cmp)
    first, last = (cmp.index.min(), cmp.index.max()) if len(cmp) else (None, None)
    start = derived.index.min() if len(derived) else None
    worst = cmp[cmp["result"] != "match"].sort_values("abs_diff", ascending=False)
    summary = {
        "comparison": name,
        "tolerance": tolerance,
        "first_compared": first.strftime("%Y-%m") if first is not None else None,
        "last_compared": last.strftime("%Y-%m") if last is not None else None,
        **stats,
        "passed": bool(len(cmp) > 0 and stats.get("mismatches", 0) == 0),
        "definitive": _stats(cmp[~cmp["provisional"]]),
        "provisional": _stats(cmp[cmp["provisional"]]),
        "status_counts": {k: int(v) for k, v in table["status"].value_counts().items()},
        "published_only_in_derived_range": [
            d.strftime("%Y-%m")
            for d in table.index[
                (table["status"] == "published_only") & (start is not None) & (table.index >= start)
            ]
        ],
        "differences": [
            {
                "date": d.strftime("%Y-%m"),
                "derived": float(r["derived"]),
                "derived_unrounded": None
                if pd.isna(r["derived_unrounded"])
                else round(float(r["derived_unrounded"]), 6),
                "published": float(r["published"]),
                "diff": round(float(r["diff"]), 6),
                "result": r["result"],
            }
            for d, r in worst.head(50).iterrows()
        ],
    }
    table.insert(0, "comparison", name)
    return table.reset_index(), summary
