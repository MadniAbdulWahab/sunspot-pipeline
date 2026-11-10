"""End-to-end run: ingest -> validate -> process -> reconcile -> archive."""

from __future__ import annotations

import json
import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .archive import archive_run
from .config import (
    ATTRIBUTION,
    CHANGES_NOTE,
    DAILY,
    LICENCE,
    MONTHLY,
    SMOOTHED,
    SOURCES,
    Paths,
)
from .ingest import (
    Fetcher,
    fetch_all,
    find_completed_run,
    http_fetcher,
    input_fingerprint,
    isoformat,
    make_run_id,
    save_raw_snapshot,
    utc_now,
)
from .process import derive_monthly, derive_smoothed, published_monthly_series, round_half_up
from .reconcile import compare
from .validate import FLAG_COLUMNS, ValidationFatal, cross_checks, overall_status, validate

log = logging.getLogger(__name__)

# The smoothed series is built from the rounded monthly means, the same way SILSO
# smooths its own published (1-decimal) monthly values.
SMOOTH_INPUT_COLUMN = "sn_mean"


@dataclass
class RunResult:
    run_id: str
    status: str  # completed | skipped | failed
    record: dict
    archive_path: Path | None = None


def _environment() -> dict:
    env = {
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "platform": platform.platform(),
    }
    try:
        env["git_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        env["git_commit"] = None
    return env


def _write_record(paths: Paths, record: dict) -> None:
    paths.runs.mkdir(parents=True, exist_ok=True)
    with (paths.runs / f"{record['run_id']}.json").open("x", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, default=str)
        fh.write("\n")


def _flag_table(frame: pd.DataFrame, extra: tuple[str, ...]) -> pd.DataFrame:
    cols = ["date", "line_no", *extra, "value", "usable", *FLAG_COLUMNS]
    out = frame[cols].copy()
    out["quality_flags"] = out[list(FLAG_COLUMNS)].apply(
        lambda r: ";".join(c.removeprefix("flag_") for c, v in r.items() if v), axis=1
    )
    return out


def run(
    paths: Paths | None = None,
    fetcher: Fetcher | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> RunResult:
    paths = paths or Paths.default()
    fetcher = fetcher or http_fetcher()
    started = now or utc_now()

    files = fetch_all(SOURCES, fetcher)
    fingerprint = input_fingerprint(files)
    run_id = make_run_id(started, fingerprint)
    record = {
        "run_id": run_id,
        "pipeline_version": __version__,
        "started_at": isoformat(started),
        "input_fingerprint": fingerprint,
        "inputs": [f.manifest_entry() for f in files],
        "environment": _environment(),
    }

    previous = find_completed_run(paths, __version__, fingerprint)
    if previous and not force:
        record.update(
            status="skipped",
            reason="inputs unchanged since an archived run of this pipeline version",
            previous_run_id=previous["run_id"],
            archive_path=previous["archive_path"],
            finished_at=isoformat(utc_now()),
        )
        _write_record(paths, record)
        log.info("inputs unchanged (matches %s); nothing to do", previous["run_id"])
        return RunResult(run_id, "skipped", record)

    raw_dir = save_raw_snapshot(paths, run_id, files)
    record["raw_snapshot"] = raw_dir.relative_to(paths.root).as_posix()
    content = {f.source.key: f.content for f in files}

    try:
        validated = {s.key: validate(content[s.key], s, now=started) for s in SOURCES}
    except ValidationFatal as exc:
        record.update(status="failed", error=str(exc), finished_at=isoformat(utc_now()))
        _write_record(paths, record)
        log.error("validation failed: %s", exc)
        return RunResult(run_id, "failed", record)

    daily, monthly, smoothed = (validated[s.key] for s in (DAILY, MONTHLY, SMOOTHED))
    extra = cross_checks(monthly, smoothed)
    quality_report = {
        "run_id": run_id,
        "status": overall_status([v.report for v in validated.values()], extra),
        "datasets": [v.report for v in validated.values()],
        "cross_checks": extra,
    }

    # --- process ---
    monthly_derived = derive_monthly(daily.frame)
    smoothed_derived = derive_smoothed(monthly_derived, SMOOTH_INPUT_COLUMN)
    pub_monthly = published_monthly_series(monthly.frame)
    smoothed_check = derive_smoothed(pub_monthly.rename(columns={"sn": "sn_pub"}), "sn_pub")

    # --- reconcile ---
    pub_m = pub_monthly.set_index("date")
    pub_s = smoothed.frame[~smoothed.frame["flag_duplicate"]].set_index("date")["value"].dropna()
    md = monthly_derived.set_index("date")
    sd = smoothed_derived.set_index("date")
    sc = smoothed_check.set_index("date")
    comparisons = [
        compare(
            "monthly_mean",
            md["sn_mean"].dropna(),
            pub_m["sn"].dropna(),
            md["provisional"],
            md["sn_mean_raw"],
        ),
        compare(
            "smoothed",
            sd["sn_smoothed"].dropna(),
            pub_s,
            sd["provisional"],
            sd["sn_smoothed_raw"],
        ),
        # Same formula applied to SILSO's own monthly file: isolates the smoothing step
        # from my monthly-mean step.
        compare(
            "smoothed_formula_on_published_monthly",
            sc["sn_smoothed"].dropna(),
            pub_s,
            sc["provisional"],
            sc["sn_smoothed_raw"],
        ),
    ]
    rec_summaries = [summary for _, summary in comparisons]
    reconciliation = pd.concat([table for table, _ in comparisons], ignore_index=True)
    reconciliation_report = {
        "run_id": run_id,
        "rounding": "derived values rounded half-up to 1 decimal before comparing; "
        "a 0.1 difference on an exact half-way tie is reported as a rounding tie",
        "passed": all(s["passed"] for s in rec_summaries),
        "comparisons": list(rec_summaries),
    }

    # --- archive ---
    out_tables = {
        "daily_flagged": _flag_table(
            daily.frame, ("year", "month", "day", "decimal_date", "sn", "sn_std", "n_obs", "definitive")
        ),
        "monthly_published_flagged": _flag_table(
            monthly.frame, ("year", "month", "decimal_date", "sn", "sn_std", "n_obs", "definitive")
        ),
        "smoothed_published_flagged": _flag_table(
            smoothed.frame, ("year", "month", "decimal_date", "sn", "sn_std", "n_obs", "definitive")
        ),
        "monthly_derived": monthly_derived,
        "smoothed_derived": smoothed_derived,
        "reconciliation": reconciliation,
    }
    finished = utc_now()
    manifest = {
        **record,
        "status": "completed",
        "finished_at": isoformat(finished),
        "raw_snapshot": record["raw_snapshot"],
        "quality_status": quality_report["status"],
        "reconciliation_passed": reconciliation_report["passed"],
        "data_range": {
            "daily": [daily.report["first_date"], daily.report["last_date"]],
            "monthly": [monthly.report["first_date"], monthly.report["last_date"]],
            "smoothed": [smoothed.report["first_date"], smoothed.report["last_date"]],
        },
        "attribution": ATTRIBUTION,
        "data_licence": LICENCE,
        "changes": CHANGES_NOTE,
    }
    archive_path = archive_run(
        paths,
        __version__,
        run_id,
        out_tables,
        {"quality_report": quality_report, "reconciliation_report": reconciliation_report},
        manifest,
    )
    record.update(
        status="completed",
        finished_at=manifest["finished_at"],
        archive_path=archive_path.relative_to(paths.root).as_posix(),
        quality_status=quality_report["status"],
        reconciliation_passed=reconciliation_report["passed"],
    )
    _write_record(paths, record)
    log.info("run %s archived to %s", run_id, archive_path)
    return RunResult(run_id, "completed", record, archive_path)


__all__ = ["RunResult", "run", "round_half_up"]
