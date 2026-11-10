"""Validation tests.

The inputs are real SILSO extracts. Where a test needs a broken file, the corruption is
done here in the test (duplicate a line, delete a line, overwrite one field) so it is
obvious which part is real and which part is the injected fault.
"""

from __future__ import annotations

import pytest
from conftest import FIXED_NOW, HISTORIC, RECENT, read_lines, to_bytes

from sunspot_pipeline.config import DAILY, MONTHLY, SMOOTHED
from sunspot_pipeline.validate import ValidationFatal, validate


def check(report: dict, name: str) -> dict:
    return next(c for c in report["checks"] if c["check"] == name)


def daily_lines(folder=HISTORIC):
    return read_lines(folder, DAILY.filename)


def test_real_historic_daily_is_clean_and_complete():
    lines = daily_lines()
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)

    assert v.report["status"] == "ok"
    assert len(v.frame) == len(lines)  # nothing dropped
    n_missing = sum(1 for ln in lines if ln.split(";")[4].strip() == "-1")
    assert check(v.report, "missing")["count"] == n_missing
    assert v.frame["flag_missing"].sum() == n_missing
    # February 1824 has no daily value at all: every day is flagged, none removed.
    feb = v.frame[(v.frame["year"] == 1824) & (v.frame["month"] == 2)]
    assert len(feb) == 29 and feb["flag_missing"].all() and not feb["usable"].any()
    assert v.report["gaps"] == []


def test_missing_rows_are_kept_but_not_usable():
    v = validate(to_bytes(daily_lines()), DAILY, now=FIXED_NOW)
    missing = v.frame[v.frame["flag_missing"]]
    assert len(missing) > 0
    assert missing["value"].isna().all()
    assert (missing["sn"] == -1).all()  # original value still there


def test_provisional_values_flagged_and_trailing():
    lines = daily_lines(RECENT)
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    n_prov = sum(1 for ln in lines if ln.endswith(";0"))
    assert n_prov > 0
    assert check(v.report, "provisional")["count"] == n_prov
    assert check(v.report, "provisional_not_trailing")["count"] == 0
    assert v.report["status"] == "ok"


def test_definitive_after_provisional_is_a_warning():
    lines = daily_lines()
    fields = lines[10].split(";")
    fields[-1] = "0"  # injected: mark an 1823 day as provisional
    lines[10] = ";".join(fields)
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    assert check(v.report, "provisional_not_trailing")["count"] > 0
    assert v.report["status"] == "warnings"


def test_smoothed_edges_are_expected_missing():
    v = validate(to_bytes(read_lines(RECENT, SMOOTHED.filename)), SMOOTHED, now=FIXED_NOW)
    # The extract ends at the latest month, so its last 6 smoothed values are -1 by definition.
    assert check(v.report, "missing_expected_edge")["count"] == 6
    assert check(v.report, "missing")["count"] == 0
    assert v.report["status"] == "ok"


def test_feb_1824_monthly_value_has_no_observations():
    v = validate(to_bytes(read_lines(HISTORIC, MONTHLY.filename)), MONTHLY, now=FIXED_NOW)
    hits = v.frame[v.frame["flag_no_obs"]]
    assert [d.strftime("%Y-%m") for d in hits["date"]] == ["1824-02"]
    assert v.frame["flag_no_obs"].sum() == check(v.report, "no_observations")["count"]


def test_duplicate_rows_are_all_flagged():
    lines = daily_lines()
    lines.insert(101, lines[100])  # injected duplicate
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    assert v.frame["flag_duplicate"].sum() == 2
    assert check(v.report, "duplicate")["count"] == 2
    assert len(v.frame) == len(lines)
    assert not v.frame.loc[v.frame["flag_duplicate"], "usable"].any()
    assert v.report["status"] == "errors"


def test_date_gap_detected_and_next_row_flagged():
    lines = daily_lines()
    removed = lines.pop(200)  # injected gap of one day
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    gap = check(v.report, "date_gaps")
    assert gap["count"] == 1
    y, m, d = removed.split(";")[:3]
    assert v.report["gaps"][0]["from"] == f"{y}-{m}-{d}"
    after = v.frame[v.frame["flag_after_gap"]]
    assert len(after) == 1 and after.iloc[0]["raw"] == lines[200]


def test_out_of_range_value_flagged_not_dropped():
    lines = daily_lines()
    fields = lines[50].split(";")
    fields[4] = "  -7"  # injected: negative sunspot number that is not the -1 sentinel
    lines[50] = ";".join(fields)
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    row = v.frame.iloc[50]
    assert row["flag_out_of_range"] and not row["usable"]
    assert check(v.report, "out_of_range")["count"] == 1
    assert len(v.frame) == len(lines)


def test_malformed_row_kept_with_schema_flag():
    lines = daily_lines()
    lines.insert(5, "1823;01;06;garbage")  # injected bad row
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    bad = v.frame[v.frame["flag_schema"]]
    assert len(bad) == 1 and bad.iloc[0]["line_no"] == 6
    assert check(v.report, "schema")["count"] == 1
    assert len(v.frame) == len(lines)


def test_unsorted_rows_warn():
    lines = daily_lines()
    lines[300], lines[301] = lines[301], lines[300]
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    assert check(v.report, "unsorted")["count"] == 1


def test_decimal_date_mismatch_warns():
    lines = daily_lines()
    fields = lines[400].split(";")
    fields[3] = "1999.500"  # injected: decimal date that belongs to another year
    lines[400] = ";".join(fields)
    v = validate(to_bytes(lines), DAILY, now=FIXED_NOW)
    assert check(v.report, "decimal_date")["count"] == 1


def test_layout_change_is_fatal():
    # The monthly file has 7 columns; reading it as the 8-column daily file must stop the run.
    with pytest.raises(ValidationFatal, match="expected 8"):
        validate(to_bytes(read_lines(HISTORIC, MONTHLY.filename)), DAILY, now=FIXED_NOW)


def test_empty_file_is_fatal():
    with pytest.raises(ValidationFatal):
        validate(b"\n\n", DAILY, now=FIXED_NOW)
