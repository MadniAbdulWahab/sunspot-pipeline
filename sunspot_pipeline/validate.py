"""Row-level validation of the SILSO files.

Nothing is dropped here. Every row of the input comes out the other side with a set of
boolean flag_* columns, and the report says how many rows tripped each check.
Only a change in the file layout itself (wrong number of columns throughout) is fatal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from .config import DAILY, MISSING_SENTINEL, SMOOTHED, Source

SN_MAX = 1000.0  # generous plausibility bound; the highest daily value on record is about half this
YEAR_MIN = 1700
SMOOTHING_EDGE = 6  # SILSO leaves the first and last 6 months of the smoothed series empty

FLAG_COLUMNS = (
    "flag_schema",
    "flag_invalid_date",
    "flag_duplicate",
    "flag_out_of_range",
    "flag_missing",
    "flag_decimal_date",
    "flag_after_gap",
    "flag_no_obs",
    "flag_provisional",
)
# Rows with any of these flags are not used to compute derived values.
EXCLUDE_FLAGS = (
    "flag_schema",
    "flag_invalid_date",
    "flag_duplicate",
    "flag_out_of_range",
    "flag_missing",
)


class ValidationFatal(Exception):
    """The file cannot be interpreted at all (e.g. the layout changed upstream)."""


@dataclass
class ValidatedDataset:
    source: Source
    frame: pd.DataFrame
    report: dict


def _check(name: str, severity: str, mask: pd.Series, frame: pd.DataFrame, description: str):
    hits = frame.loc[mask]
    examples = []
    for _, row in hits.head(5).iterrows():
        ex = {"line_no": int(row["line_no"])}
        if pd.notna(row.get("date")):
            ex["date"] = row["date"].strftime("%Y-%m-%d")
        ex["raw"] = row["raw"]
        examples.append(ex)
    return {
        "check": name,
        "severity": severity,
        "count": int(mask.sum()),
        "description": description,
        "examples": examples,
    }


def parse(content: bytes, source: Source) -> pd.DataFrame:
    """Split the semicolon file into typed columns, keeping malformed rows."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFatal(f"{source.filename}: not valid UTF-8/ASCII text ({exc})") from exc

    rows = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue  # counted separately as blank_lines
        rows.append((line_no, line, [p.strip() for p in line.split(";")]))
    if not rows:
        raise ValidationFatal(f"{source.filename}: file is empty")

    n_expected = len(source.columns)
    field_counts = pd.Series([len(parts) for _, _, parts in rows])
    modal = int(field_counts.mode().iloc[0])
    if modal != n_expected:
        raise ValidationFatal(
            f"{source.filename}: expected {n_expected} semicolon-separated fields, "
            f"most rows have {modal}. The upstream layout may have changed."
        )

    good_shape = field_counts.to_numpy() == n_expected
    values = [
        parts if ok else [None] * n_expected for (_, _, parts), ok in zip(rows, good_shape, strict=True)
    ]
    raw_text = pd.DataFrame(values, columns=list(source.columns))
    frame = pd.DataFrame(
        {
            "line_no": [r[0] for r in rows],
            "raw": [r[1] for r in rows],
        }
    )
    bad_number = pd.Series(False, index=frame.index)
    for col in source.columns:
        numeric = pd.to_numeric(raw_text[col], errors="coerce")
        bad_number |= raw_text[col].notna() & numeric.isna()
        frame[col] = numeric.astype("float64")

    integral_cols = [c for c in (*source.date_parts, "n_obs", "definitive") if c in frame]
    not_integral = pd.Series(False, index=frame.index)
    for col in integral_cols:
        v = frame[col]
        not_integral |= v.notna() & (v != np.floor(v))

    frame["flag_schema"] = ~good_shape | bad_number.to_numpy() | not_integral.to_numpy()
    frame.attrs["blank_lines"] = len(text.splitlines()) - len(rows)
    return frame


def _build_dates(frame: pd.DataFrame, source: Source) -> pd.Series:
    ok = ~frame["flag_schema"]
    dates = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    if ok.any():
        sub = pd.DataFrame(
            {
                "year": frame.loc[ok, "year"],
                "month": frame.loc[ok, "month"],
                "day": frame.loc[ok, "day"] if "day" in source.date_parts else 1,
            }
        )
        dates.loc[ok] = pd.to_datetime(sub, errors="coerce")
    return dates


def _gaps(dates: pd.Series, freq: str) -> list[dict]:
    present = pd.DatetimeIndex(dates.dropna().unique()).sort_values()
    if len(present) < 2:
        return []
    expected = pd.date_range(present[0], present[-1], freq=freq)
    missing = expected.difference(present)
    gaps = []
    if len(missing):
        # group consecutive missing periods into ranges
        step = pd.tseries.frequencies.to_offset(freq)
        start = prev = missing[0]
        for ts in missing[1:]:
            if ts != prev + step:
                gaps.append((start, prev))
                start = ts
            prev = ts
        gaps.append((start, prev))
    return [
        {
            "from": a.strftime("%Y-%m-%d"),
            "to": b.strftime("%Y-%m-%d"),
            "missing_periods": len(pd.date_range(a, b, freq=freq)),
        }
        for a, b in gaps
    ]


def _decimal_date_ok(frame: pd.DataFrame, source: Source) -> pd.Series:
    """The decimal_date column should fall inside the day/month it belongs to."""

    date = frame["date"]
    year_start = pd.to_datetime(frame["year"].astype("Int64").astype(str) + "-01-01", errors="coerce")
    year_len = (year_start + pd.DateOffset(years=1) - year_start).dt.days
    step = pd.Timedelta(days=1) if source is DAILY else pd.DateOffset(months=1)
    period_end = date + step
    lo = frame["year"] + (date - year_start).dt.days / year_len
    hi = frame["year"] + (period_end - year_start).dt.days / year_len
    tol = 0.0015  # the files round decimal_date to 3 decimals
    ok = (frame["decimal_date"] >= lo - tol) & (frame["decimal_date"] <= hi + tol)
    return ok | date.isna()


def validate(content: bytes, source: Source, now: datetime | None = None) -> ValidatedDataset:
    frame = parse(content, source)
    frame["date"] = _build_dates(frame, source)
    schema_ok = ~frame["flag_schema"]
    frame["flag_invalid_date"] = schema_ok & frame["date"].isna()

    has_date = frame["date"].notna()
    frame["flag_duplicate"] = has_date & frame["date"].duplicated(keep=False)

    sn, sd, nobs = frame["sn"], frame["sn_std"], frame["n_obs"]
    is_sentinel = sn == MISSING_SENTINEL
    this_year = (now or datetime.now(UTC)).year
    out_of_range = (
        (sn.notna() & ~is_sentinel & ((sn < 0) | (sn > SN_MAX)))
        | (sd.notna() & (sd < 0) & (sd != MISSING_SENTINEL))
        | (nobs.notna() & (nobs < 0) & (nobs != MISSING_SENTINEL))
        | (frame["definitive"].notna() & ~frame["definitive"].isin([0, 1]))
        | (frame["year"].notna() & ((frame["year"] < YEAR_MIN) | (frame["year"] > this_year + 1)))
    )
    frame["flag_out_of_range"] = schema_ok & out_of_range
    frame["flag_missing"] = schema_ok & (is_sentinel | sn.isna())
    frame["flag_decimal_date"] = schema_ok & ~_decimal_date_ok(frame, source)
    frame["flag_no_obs"] = schema_ok & (nobs == 0) & ~frame["flag_missing"]
    frame["flag_provisional"] = schema_ok & (frame["definitive"] == 0)

    freq = "D" if source is DAILY else "MS"
    gaps = _gaps(frame["date"], freq)
    after_gap_dates = {pd.Timestamp(g["to"]) + pd.tseries.frequencies.to_offset(freq) for g in gaps}
    frame["flag_after_gap"] = frame["date"].isin(after_gap_dates)

    running_max = frame["date"].cummax()
    unsorted = has_date & (frame["date"] < running_max.shift(1))

    # Provisional values should only ever be the most recent block of rows.
    prov_pos = np.flatnonzero(frame["flag_provisional"].to_numpy())
    if len(prov_pos):
        after_first = frame.index >= frame.index[prov_pos[0]]
        provisional_not_trailing = pd.Series(after_first, index=frame.index) & (frame["definitive"] == 1)
    else:
        provisional_not_trailing = pd.Series(False, index=frame.index)

    checks = [
        _check(
            "schema",
            "error",
            frame["flag_schema"],
            frame,
            "Row has the wrong number of fields or a non-numeric / non-integer value.",
        ),
        _check(
            "invalid_date",
            "error",
            frame["flag_invalid_date"],
            frame,
            "Year/month/day do not form a real calendar date.",
        ),
        _check(
            "duplicate",
            "error",
            frame["flag_duplicate"],
            frame,
            "More than one row for the same date (all copies flagged).",
        ),
        _check(
            "out_of_range",
            "error",
            frame["flag_out_of_range"],
            frame,
            f"Value outside plausible range (SN 0-{SN_MAX:g}, std/n_obs >= 0 or -1, "
            f"definitive in {{0,1}}, year {YEAR_MIN}-{this_year + 1}).",
        ),
        _check(
            "unsorted",
            "warning",
            unsorted,
            frame,
            "Row is earlier than a previous row (file not in date order).",
        ),
        _check(
            "decimal_date",
            "warning",
            frame["flag_decimal_date"],
            frame,
            "decimal_date column does not fall inside the row's own day/month.",
        ),
        _check(
            "provisional_not_trailing",
            "warning",
            provisional_not_trailing,
            frame,
            "A definitive row appears after the first provisional row.",
        ),
        _check(
            "no_observations",
            "info",
            frame["flag_no_obs"],
            frame,
            "Value present but n_obs is 0 (not backed by observations, e.g. interpolated).",
        ),
        _check(
            "provisional",
            "info",
            frame["flag_provisional"],
            frame,
            "Value is provisional (definitive = 0) and may still be revised by SILSO.",
        ),
    ]

    missing = frame["flag_missing"]
    if source is SMOOTHED:
        order = frame.loc[has_date, "date"].sort_values().unique()
        edge_dates = set(order[:SMOOTHING_EDGE]) | set(order[-SMOOTHING_EDGE:])
        edge = frame["date"].isin(edge_dates)
        checks.append(
            _check(
                "missing_expected_edge",
                "info",
                missing & edge,
                frame,
                "No smoothed value in the first/last 6 months (expected, by definition).",
            )
        )
        checks.append(
            _check(
                "missing",
                "warning",
                missing & ~edge,
                frame,
                "Smoothed value missing (-1) away from the series edges.",
            )
        )
    elif source is DAILY:
        checks.append(
            _check(
                "missing",
                "info",
                missing,
                frame,
                "No daily value (-1). Common in the 19th century, when observations were sparse.",
            )
        )
    else:
        checks.append(_check("missing", "warning", missing, frame, "Monthly value missing (-1)."))

    gap_count = sum(g["missing_periods"] for g in gaps)
    checks.append(
        {
            "check": "date_gaps",
            "severity": "warning",
            "count": gap_count,
            "description": f"Calendar {'days' if freq == 'D' else 'months'} absent from the file "
            "between its first and last row. The row after each gap is flagged.",
            "examples": gaps[:5],
        }
    )
    checks.append(
        {
            "check": "blank_lines",
            "severity": "info",
            "count": int(frame.attrs.get("blank_lines", 0)),
            "description": "Empty lines in the file (ignored).",
            "examples": [],
        }
    )

    if any(c["severity"] == "error" and c["count"] for c in checks):
        status = "errors"
    elif any(c["severity"] == "warning" and c["count"] for c in checks):
        status = "warnings"
    else:
        status = "ok"

    frame["usable"] = ~frame[list(EXCLUDE_FLAGS)].any(axis=1)
    frame["value"] = frame["sn"].where(frame["usable"])
    dated = frame["date"].dropna()
    report = {
        "dataset": source.key,
        "file": source.filename,
        "rows": len(frame),
        "first_date": dated.min().strftime("%Y-%m-%d") if len(dated) else None,
        "last_date": dated.max().strftime("%Y-%m-%d") if len(dated) else None,
        "usable_rows": int(frame["usable"].sum()),
        "status": status,
        "checks": checks,
        "gaps": gaps,
        "flag_counts": {c: int(frame[c].sum()) for c in FLAG_COLUMNS},
    }
    return ValidatedDataset(source=source, frame=frame, report=report)


def cross_checks(monthly: ValidatedDataset, smoothed: ValidatedDataset) -> list[dict]:
    """Checks that need more than one file."""

    m = set(monthly.frame["date"].dropna())
    s = set(smoothed.frame["date"].dropna())
    only_m = sorted(m - s)
    only_s = sorted(s - m)
    return [
        {
            "check": "monthly_vs_smoothed_months",
            "severity": "warning",
            "count": len(only_m) + len(only_s),
            "description": "Months present in only one of the monthly and smoothed files.",
            "examples": [d.strftime("%Y-%m") for d in (only_m + only_s)[:5]],
        }
    ]


def overall_status(reports: list[dict], extra_checks: list[dict]) -> str:
    statuses = {r["status"] for r in reports}
    if "errors" in statuses:
        return "errors"
    if "warnings" in statuses or any(c["count"] for c in extra_checks):
        return "warnings"
    return "ok"
