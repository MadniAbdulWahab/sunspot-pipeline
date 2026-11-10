import io
import zipfile

import pandas as pd
import streamlit as st

from app.data import PATHS, archived_runs, attribution_note, file_path, run_records
from sunspot_pipeline.archive import verify_run
from sunspot_pipeline.pipeline import run

st.title("Runs & archive")

if flash := st.session_state.pop("flash", None):
    getattr(st, flash[0])(flash[1])

with st.container(border=True):
    left, right = st.columns([3, 1])
    left.markdown(
        "**Run the pipeline now.** It downloads the three files again and compares their SHA-256 "
        "hashes with the last archived run. If nothing changed, the run is logged as *skipped* "
        "and nothing new is archived."
    )
    if right.button("Run pipeline", type="primary", width="stretch"):
        with st.spinner("Downloading from SILSO..."):
            try:
                result = run(PATHS)
            except Exception as exc:
                st.error(f"Run failed: {exc}")
            else:
                if result.status == "completed":
                    st.session_state["select_latest"] = True
                    st.session_state["flash"] = ("success", f"New run archived: {result.run_id}")
                elif result.status == "skipped":
                    prev = result.record["previous_run_id"]
                    st.session_state["flash"] = ("info", f"Inputs unchanged since {prev}; nothing archived.")
                else:
                    st.session_state["flash"] = (
                        "error",
                        f"Run {result.run_id} failed: {result.record.get('error')}",
                    )
                st.rerun()

st.subheader("Run log")
records = run_records()
if records:
    log = pd.DataFrame(
        [
            {
                "run_id": r["run_id"],
                "status": r["status"],
                "started (UTC)": r["started_at"],
                "inputs": r["input_fingerprint"][:12],
                "quality": r.get("quality_status", "-"),
                "reconciled": {True: "pass", False: "FAIL"}.get(r.get("reconciliation_passed"), "-"),
                "archive / note": r.get("archive_path") or r.get("error"),
            }
            for r in records
        ]
    )
    st.dataframe(log, hide_index=True, width="stretch")
else:
    st.info("No runs recorded yet.")

runs = archived_runs()
if not runs:
    st.stop()

st.subheader("Archived run")
run_id = st.session_state.get("run_id", runs[0]["run_id"])
manifest = next((m for m in runs if m["run_id"] == run_id), runs[0])
run_id = manifest["run_id"]
st.markdown(f"Showing `{run_id}` (change it in the sidebar).")
st.caption(f"Folder: `{manifest['archive_path']}` · raw snapshot: `{manifest['raw_snapshot']}`")

st.markdown("**Inputs**")
st.dataframe(
    pd.DataFrame(manifest["inputs"])[["key", "url", "fetched_at", "sha256", "bytes", "last_modified"]],
    hide_index=True,
    width="stretch",
)

st.markdown("**Outputs**")
outputs = pd.DataFrame(manifest["outputs"])
st.dataframe(outputs[["file", "format", "rows", "bytes", "sha256"]], hide_index=True, width="stretch")

c1, c2, c3 = st.columns([2, 1, 1])
filename = c1.selectbox("File to download", [o["file"] for o in manifest["outputs"]] + ["manifest.json"])
c2.download_button(
    "Download file",
    data=file_path(manifest["archive_path"], filename).read_bytes(),
    file_name=filename,
    width="stretch",
)


@st.cache_data(show_spinner="Zipping...", max_entries=2)
def zipped(archive_path: str) -> bytes:
    buf = io.BytesIO()
    folder = PATHS.root / archive_path
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(folder.iterdir()):
            zf.write(p, arcname=f"{folder.name}/{p.name}")
    return buf.getvalue()


if c3.toggle("Prepare zip of whole run"):
    c3.download_button(
        "Download zip",
        data=zipped(manifest["archive_path"]),
        file_name=f"{run_id}.zip",
        mime="application/zip",
        width="stretch",
    )

if st.button("Verify checksums"):
    results = pd.DataFrame(verify_run(PATHS, manifest))
    if results["ok"].all():
        st.success(f"All {len(results)} files match the SHA-256 in the manifest.")
    else:
        st.error("Some files do not match their manifest checksum.")
    st.dataframe(results, hide_index=True, width="stretch")

with st.expander("Full manifest"):
    st.json(manifest, expanded=False)

attribution_note()
