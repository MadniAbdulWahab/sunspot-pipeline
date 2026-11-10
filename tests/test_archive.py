from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from sunspot_pipeline import archive as archive_mod
from sunspot_pipeline.archive import ArchiveExistsError, archive_run, list_archived_runs, verify_run


def tables(value=1.0):
    return {"t": pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "v": [value]})}


def manifest(run_id, started="2026-11-10T12:00:00Z", version="1.0.0"):
    return {"run_id": run_id, "started_at": started, "pipeline_version": version}


def tree_hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def test_archive_writes_parquet_csv_and_manifest(paths):
    folder = archive_run(paths, "1.0.0", "r1", tables(), {"report": {"ok": True}}, manifest("r1"))
    assert folder == paths.archive / "v1.0.0" / "r1"
    assert {p.name for p in folder.iterdir()} == {"t.parquet", "t.csv", "report.json", "manifest.json"}
    m = json.loads((folder / "manifest.json").read_text())
    for out in m["outputs"]:
        assert hashlib.sha256((folder / out["file"]).read_bytes()).hexdigest() == out["sha256"]
    assert pd.read_parquet(folder / "t.parquet")["v"].tolist() == [1.0]


def test_existing_run_is_never_overwritten(paths):
    folder = archive_run(paths, "1.0.0", "r1", tables(1.0), {}, manifest("r1"))
    before = tree_hashes(folder)

    with pytest.raises(ArchiveExistsError):
        archive_run(paths, "1.0.0", "r1", tables(999.0), {}, manifest("r1"))

    assert tree_hashes(folder) == before
    assert pd.read_parquet(folder / "t.parquet")["v"].tolist() == [1.0]
    assert not list(folder.parent.glob(".staging-*"))


def test_versions_live_side_by_side(paths):
    a = archive_run(paths, "1.0.0", "r1", tables(1.0), {}, manifest("r1", version="1.0.0"))
    b = archive_run(paths, "1.1.0", "r1", tables(2.0), {}, manifest("r1", version="1.1.0"))
    assert a != b and a.exists() and b.exists()
    assert [m["pipeline_version"] for m in list_archived_runs(paths)] in (
        ["1.0.0", "1.1.0"],
        ["1.1.0", "1.0.0"],
    )


def test_failure_mid_write_leaves_no_partial_run(paths, monkeypatch):
    def boom(path):
        raise OSError("disk full")

    monkeypatch.setattr(archive_mod, "sha256_file", boom)
    with pytest.raises(OSError):
        archive_run(paths, "1.0.0", "r1", tables(), {}, manifest("r1"))
    version_dir = paths.archive / "v1.0.0"
    assert list(version_dir.iterdir()) == []


def test_verify_detects_tampering(paths):
    folder = archive_run(paths, "1.0.0", "r1", tables(), {}, manifest("r1"))
    m = list_archived_runs(paths)[0]
    assert all(r["ok"] for r in verify_run(paths, m))
    (folder / "t.csv").write_text("date,v\n2020-01-01,5\n")
    bad = [r["file"] for r in verify_run(paths, m) if not r["ok"]]
    assert bad == ["t.csv"]
