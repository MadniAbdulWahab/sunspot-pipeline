"""Ingest and end-to-end run tests, against a fake fetcher serving real fixture files."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest
from conftest import FIXED_NOW, HISTORIC, RECENT, FakeFetcher, read_lines, to_bytes

from sunspot_pipeline import __version__
from sunspot_pipeline.config import DAILY, SOURCES
from sunspot_pipeline.ingest import find_completed_run
from sunspot_pipeline.pipeline import run


def records(paths):
    return sorted(
        (json.loads(p.read_text()) for p in paths.runs.glob("*.json")),
        key=lambda r: r["started_at"],
    )


def archived(paths):
    return sorted(p.parent for p in paths.archive.glob("v*/*/manifest.json"))


def test_first_run_records_url_time_and_hash(paths):
    result = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    assert result.status == "completed"

    inputs = {i["key"]: i for i in result.record["inputs"]}
    for source in SOURCES:
        entry = inputs[source.key]
        expected = hashlib.sha256((HISTORIC / source.filename).read_bytes()).hexdigest()
        assert entry["url"] == source.url
        assert entry["sha256"] == expected
        assert entry["fetched_at"].endswith("Z")
        # raw snapshot is byte-identical to what was fetched
        snap = paths.root / result.record["raw_snapshot"] / source.filename
        assert hashlib.sha256(snap.read_bytes()).hexdigest() == expected

    manifest = json.loads((result.archive_path / "manifest.json").read_text())
    assert manifest["inputs"] == result.record["inputs"]
    assert "WDC-SILSO" in manifest["attribution"]


def test_unchanged_input_is_skipped(paths):
    first = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    second = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW + timedelta(hours=1))

    assert second.status == "skipped"
    assert second.record["previous_run_id"] == first.run_id
    assert len(archived(paths)) == 1
    assert len(list(paths.raw.iterdir())) == 1  # no second raw snapshot either
    assert [r["status"] for r in records(paths)] == ["completed", "skipped"]


def test_changed_input_creates_new_run(paths):
    run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    later = run(paths, fetcher=FakeFetcher(RECENT), now=FIXED_NOW + timedelta(days=1))
    assert later.status == "completed"
    assert len(archived(paths)) == 2


def test_force_reruns_without_overwriting(paths):
    first = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    forced = run(paths, fetcher=FakeFetcher(HISTORIC), force=True, now=FIXED_NOW + timedelta(minutes=5))
    assert forced.status == "completed" and forced.run_id != first.run_id
    assert len(archived(paths)) == 2


def test_new_pipeline_version_does_not_reuse_old_run(paths):
    first = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    fp = first.record["input_fingerprint"]
    assert find_completed_run(paths, __version__, fp)["run_id"] == first.run_id
    assert find_completed_run(paths, "99.0.0", fp) is None


def test_fatal_validation_fails_run_without_archive(paths):
    bad_daily = to_bytes([";".join(ln.split(";")[:5]) for ln in read_lines(HISTORIC, DAILY.filename)])
    result = run(paths, fetcher=FakeFetcher(HISTORIC, {"daily": bad_daily}), now=FIXED_NOW)
    assert result.status == "failed"
    assert "expected 8" in result.record["error"]
    assert archived(paths) == []
    assert (paths.root / result.record["raw_snapshot"]).is_dir()  # keep the evidence
    # a failed run is not a reason to skip the next one
    retry = run(
        paths, fetcher=FakeFetcher(HISTORIC, {"daily": bad_daily}), now=FIXED_NOW + timedelta(hours=1)
    )
    assert retry.status == "failed"


def test_download_error_leaves_nothing_behind(paths):
    def broken(source):
        raise ConnectionError("SILSO unreachable")

    with pytest.raises(ConnectionError):
        run(paths, fetcher=broken, now=FIXED_NOW)
    assert not paths.archive.exists() and not paths.raw.exists()


def test_end_to_end_reconciliation_on_historic_extract(paths):
    result = run(paths, fetcher=FakeFetcher(HISTORIC), now=FIXED_NOW)
    report = json.loads((result.archive_path / "reconciliation_report.json").read_text())
    by_name = {c["comparison"]: c for c in report["comparisons"]}

    monthly = by_name["monthly_mean"]
    assert monthly["n"] == 35  # 36 months minus Feb 1824
    assert monthly["exact_matches"] == 35
    assert monthly["published_only_in_derived_range"] == ["1824-02"]
    assert report["passed"]
    quality = json.loads((result.archive_path / "quality_report.json").read_text())
    assert quality["status"] == "ok"
