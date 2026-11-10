"""Entry point: streamlit run streamlit_app.py"""

import streamlit as st

from app.data import archived_runs, bootstrap

st.set_page_config(page_title="Sunspot pipeline", page_icon=":sunny:", layout="wide")

try:
    status = bootstrap()
except Exception as exc:  # network down on a fresh deploy, SILSO unreachable, ...
    st.error(f"Could not build the first archived run: {exc}")
    st.stop()
if status == "failed":
    st.error("The first pipeline run failed validation. See the Runs & archive page for the error.")

runs = archived_runs()
with st.sidebar:
    if runs:
        ids = [r["run_id"] for r in runs]
        # After a new run is archived, jump to it; otherwise keep the user's choice if it still exists.
        if st.session_state.pop("select_latest", False) or st.session_state.get("run_id") not in ids:
            st.session_state["run_id"] = ids[0]
        st.selectbox(
            "Archived run",
            ids,
            key="run_id",
            help="Every page shows this run. The newest run is selected by default.",
        )

pages = st.navigation(
    [
        st.Page("app/pages/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page(
            "app/pages/quality.py", title="Data quality", icon=":material/fact_check:", url_path="quality"
        ),
        st.Page("app/pages/explorer.py", title="Explorer", icon=":material/show_chart:", url_path="explorer"),
        st.Page("app/pages/runs.py", title="Runs & archive", icon=":material/inventory_2:", url_path="runs"),
    ]
)
pages.run()
