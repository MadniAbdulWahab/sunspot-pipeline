import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.charts import base_layout
from app.data import COLOURS, attribution_note, require_run
from sunspot_pipeline.validate import FLAG_COLUMNS

data = require_run()
quality = data["quality_report"]

st.title("Data quality")
st.write(
    "Every row of every input file is kept. Problems are recorded as flags on the row and "
    "counted below; rows with a blocking flag (schema, invalid date, duplicate, out of range, "
    "missing) are left out of the derived values but stay in the archived tables."
)

STATUS = {
    "ok": (":material/check_circle:", "OK"),
    "warnings": (":material/warning:", "Warnings"),
    "errors": (":material/error:", "Errors"),
}
icon, label = STATUS[quality["status"]]
st.markdown(f"**Overall status:** {icon} {label} &nbsp;·&nbsp; run `{quality['run_id']}`")

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
DATASET_TABLE = {
    "daily": "daily_flagged",
    "monthly": "monthly_published_flagged",
    "smoothed": "smoothed_published_flagged",
}

tabs = st.tabs([f"{d['dataset'].title()} ({d['status']})" for d in quality["datasets"]] + ["Cross-file"])
for tab, report in zip(tabs, quality["datasets"], strict=False):
    with tab:
        a, b, c, d = st.columns(4)
        a.metric("Rows", f"{report['rows']:,}")
        b.metric("Usable rows", f"{report['usable_rows']:,}")
        c.metric("First date", report["first_date"])
        d.metric("Last date", report["last_date"])

        checks = pd.DataFrame(report["checks"]).sort_values(
            ["severity", "count"], key=lambda s: s.map(SEVERITY_ORDER) if s.name == "severity" else -s
        )
        checks["result"] = [
            ("FAIL" if sev == "error" else "WARN" if sev == "warning" else "note") if n else "pass"
            for sev, n in zip(checks["severity"], checks["count"], strict=True)
        ]
        st.dataframe(
            checks[["check", "severity", "result", "count", "description"]],
            hide_index=True,
            width="stretch",
            column_config={"description": st.column_config.TextColumn(width="large")},
        )
        with st.expander("Examples of flagged rows (first 5 per check)"):
            for chk in report["checks"]:
                if chk["count"] and chk["examples"]:
                    st.markdown(f"**{chk['check']}** ({chk['count']:,})")
                    st.dataframe(pd.DataFrame(chk["examples"]), hide_index=True)
        if report["gaps"]:
            st.markdown("**Date gaps**")
            st.dataframe(pd.DataFrame(report["gaps"]), hide_index=True)

with tabs[-1]:
    st.dataframe(pd.DataFrame(quality["cross_checks"]), hide_index=True, width="stretch")

st.subheader("Daily coverage by year")
st.caption(
    "Share of calendar days with a usable daily value. Before about 1850 many days have no "
    "observation, so monthly means from those years rest on fewer days."
)
daily = data["daily_flagged"]
cov = (
    daily.assign(year=daily["date"].dt.year)
    .groupby("year")
    .agg(days=("usable", "size"), usable=("usable", "sum"))
    .assign(share=lambda t: t["usable"] / t["days"] * 100)
    .reset_index()
)
fig = go.Figure(
    go.Bar(
        x=cov["year"],
        y=cov["share"],
        marker=dict(color=COLOURS["monthly"]),
        customdata=cov[["usable", "days"]].to_numpy(),
        hovertemplate="%{x}: %{y:.1f}% (%{customdata[0]} of %{customdata[1]} days)<extra></extra>",
        name="Coverage",
    )
)
fig = base_layout(fig, "Days with a value (%)", 280)
fig.update_layout(hovermode="closest", showlegend=False)
fig.update_yaxes(range=[0, 100])
st.plotly_chart(fig, width="stretch")

st.subheader("Browse flagged rows")
col1, col2 = st.columns([1, 2])
dataset = col1.selectbox("File", list(DATASET_TABLE))
table = data[DATASET_TABLE[dataset]]
present = [f for f in FLAG_COLUMNS if table[f].any()]
flags = col2.multiselect(
    "Show rows with any of these flags",
    present,
    default=[f for f in present if f != "flag_missing"][:2] or present[:1],
    format_func=lambda f: f.removeprefix("flag_"),
)
rows = table[table[flags].any(axis=1)] if flags else table.iloc[0:0]
st.caption(f"{len(rows):,} rows")
st.dataframe(
    rows.drop(columns=list(FLAG_COLUMNS)),
    hide_index=True,
    width="stretch",
    height=320,
    column_config={"date": st.column_config.DateColumn(format="YYYY-MM-DD")},
)
st.download_button(
    "Download these rows (CSV)",
    rows.to_csv(index=False).encode(),
    file_name=f"{dataset}_flagged_rows.csv",
    mime="text/csv",
    disabled=rows.empty,
)

attribution_note()
