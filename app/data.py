"""Shared data access for the Streamlit pages. The app only reads archived runs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from sunspot_pipeline.archive import list_archived_runs
from sunspot_pipeline.config import ATTRIBUTION, LICENCE, Paths
from sunspot_pipeline.pipeline import run

PATHS = Paths.default()

TABLES = (
    "daily_flagged",
    "monthly_published_flagged",
    "smoothed_published_flagged",
    "monthly_derived",
    "smoothed_derived",
    "reconciliation",
)

# One fixed colour per quantity (validated categorical slots 1 and 2). Derived series reuse
# the colour of the published series they reproduce and are drawn dashed.
COLOURS = {
    "monthly": "#2a78d6",
    "smoothed": "#eb6834",
    "daily": "#9a9893",
    "good": "#0ca30c",
    "critical": "#d03b3b",
}


@st.cache_resource(show_spinner="No archived data yet - downloading from SILSO and running the pipeline...")
def bootstrap() -> str | None:
    """On a fresh deployment there is no archive yet, so build one. Runs once per process."""

    if list_archived_runs(PATHS):
        return None
    result = run(PATHS)
    return result.status


def archived_runs() -> list[dict]:
    return list_archived_runs(PATHS)


def run_records() -> list[dict]:
    if not PATHS.runs.exists():
        return []
    records = [json.loads(p.read_text(encoding="utf-8")) for p in PATHS.runs.glob("*.json")]
    return sorted(records, key=lambda r: r["started_at"], reverse=True)


@st.cache_data(show_spinner=False, max_entries=4)
def load_run(archive_path: str) -> dict:
    """Everything a page needs from one archived run. Cached by path: runs never change."""

    folder = PATHS.root / archive_path
    data = {name: pd.read_parquet(folder / f"{name}.parquet") for name in TABLES}
    for name in ("quality_report", "reconciliation_report", "manifest"):
        data[name] = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    return data


def selected_run() -> dict | None:
    """The run chosen in the sidebar (latest by default)."""

    runs = archived_runs()
    if not runs:
        return None
    chosen = st.session_state.get("run_id")  # owned by the sidebar selectbox
    manifest = next((r for r in runs if r["run_id"] == chosen), runs[0])
    return load_run(manifest["archive_path"])


def require_run() -> dict:
    data = selected_run()
    if data is None:
        st.warning("There is no archived run yet. Run `python -m sunspot_pipeline run` first.")
        st.stop()
    return data


def attribution_note() -> None:
    st.caption(
        f"{ATTRIBUTION}. Licence: {LICENCE}. Monthly means derived from daily values, the derived "
        "smoothed series and all quality flags were computed by this app and are not official SILSO products."
    )


def file_path(archive_path: str, filename: str) -> Path:
    return PATHS.root / archive_path / filename
