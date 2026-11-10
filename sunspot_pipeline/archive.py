"""Write-once archive of pipeline outputs: archive/<version>/<run_id>/."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pandas as pd

from .config import Paths
from .ingest import sha256_file


class ArchiveExistsError(FileExistsError):
    """Raised instead of ever overwriting an archived run."""


def _write_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
        fh.write("\n")


def run_dir(paths: Paths, version: str, run_id: str) -> Path:
    return paths.archive / f"v{version}" / run_id


def archive_run(
    paths: Paths,
    version: str,
    run_id: str,
    tables: dict[str, pd.DataFrame],
    reports: dict[str, dict],
    manifest: dict,
) -> Path:
    """Write tables (Parquet + CSV) and JSON reports, then publish the folder in one rename.

    Files are first written to a hidden staging folder next to the target. Only when
    everything is on disk and hashed does the staging folder get renamed into place, so a
    crash halfway never leaves a half-written run that looks complete.
    """

    final = run_dir(paths, version, run_id)
    if final.exists():
        raise ArchiveExistsError(f"{final} already exists; archived runs are never overwritten")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.parent / f".staging-{run_id}"
    staging.mkdir(exist_ok=False)

    try:
        outputs = []
        for name, df in tables.items():
            for ext in ("parquet", "csv"):
                path = staging / f"{name}.{ext}"
                if ext == "parquet":
                    df.to_parquet(path, index=False)
                else:
                    df.to_csv(path, index=False, date_format="%Y-%m-%d")
                outputs.append(
                    {
                        "file": path.name,
                        "table": name,
                        "format": ext,
                        "rows": int(len(df)),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
        for name, data in reports.items():
            path = staging / f"{name}.json"
            _write_json(path, data)
            outputs.append(
                {
                    "file": path.name,
                    "format": "json",
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )

        full_manifest = {
            **manifest,
            "archive_path": final.relative_to(paths.root).as_posix(),
            "outputs": outputs,
        }
        _write_json(staging / "manifest.json", full_manifest)

        if final.exists():  # someone else got there while we were writing
            raise ArchiveExistsError(f"{final} appeared while writing; refusing to overwrite")
        os.rename(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def list_archived_runs(paths: Paths) -> list[dict]:
    """All archived manifests, newest first."""

    manifests = []
    for path in paths.archive.glob("v*/*/manifest.json"):
        if path.parent.name.startswith("."):
            continue
        manifests.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(manifests, key=lambda m: m["started_at"], reverse=True)


def verify_run(paths: Paths, manifest: dict) -> list[dict]:
    """Re-hash every archived file and compare with the manifest."""

    folder = paths.root / manifest["archive_path"]
    results = []
    for out in manifest["outputs"]:
        path = folder / out["file"]
        actual = sha256_file(path) if path.exists() else None
        results.append({"file": out["file"], "ok": actual == out["sha256"], "sha256": actual})
    return results
