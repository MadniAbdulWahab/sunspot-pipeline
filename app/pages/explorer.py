from datetime import date

import pandas as pd
import streamlit as st

from app.charts import diff_figure, series_figure
from app.data import COLOURS, attribution_note, require_run

data = require_run()

st.title("Explorer")

daily = data["daily_flagged"]
monthly_pub = data["monthly_published_flagged"]
smoothed_pub = data["smoothed_published_flagged"]
monthly_der = data["monthly_derived"]
smoothed_der = data["smoothed_derived"]

SERIES = {
    "Daily": lambda: {
        "x": daily["date"],
        "y": daily["value"],
        "colour": COLOURS["daily"],
        "width": 1,
        "gl": True,
        "opacity": 0.6,
    },
    "Monthly mean (SILSO)": lambda: {
        "x": monthly_pub["date"],
        "y": monthly_pub["value"],
        "colour": COLOURS["monthly"],
    },
    "Monthly mean (derived from daily)": lambda: {
        "x": monthly_der["date"],
        "y": monthly_der["sn_mean"],
        "colour": COLOURS["monthly"],
        "dash": "dot",
    },
    "13-month smoothed (SILSO)": lambda: {
        "x": smoothed_pub["date"],
        "y": smoothed_pub["value"],
        "colour": COLOURS["smoothed"],
    },
    "13-month smoothed (derived)": lambda: {
        "x": smoothed_der["date"],
        "y": smoothed_der["sn_smoothed"],
        "colour": COLOURS["smoothed"],
        "dash": "dot",
    },
}

first = monthly_pub["date"].min().date()
last = daily["date"].max().date()

c1, c2 = st.columns([2, 3])
with c1:
    span = st.date_input(
        "Date range",
        value=(max(first, date(last.year - 25, 1, 1)), last),
        min_value=first,
        max_value=last,
        format="YYYY-MM-DD",
    )
with c2:
    chosen = st.multiselect(
        "Series",
        list(SERIES),
        default=["Monthly mean (SILSO)", "13-month smoothed (SILSO)", "13-month smoothed (derived)"],
    )

if not isinstance(span, tuple) or len(span) != 2:
    st.info("Pick an end date to finish the range.")
    st.stop()
start, end = (pd.Timestamp(d) for d in span)
if (end - start).days > 365 * 60 and "Daily" in chosen:
    st.caption("Tip: daily values are dense; a shorter range makes them easier to read.")


def clip(s: dict) -> dict:
    x = pd.Series(s["x"]).reset_index(drop=True)
    y = pd.Series(s["y"]).reset_index(drop=True)
    keep = (x >= start) & (x <= end)
    return {**s, "x": x[keep], "y": y[keep]}


series = {name: clip(SERIES[name]()) for name in chosen}
first_prov = monthly_pub.loc[monthly_pub["flag_provisional"], "date"].min()
st.plotly_chart(series_figure(series, first_provisional=first_prov), width="stretch")
st.caption(
    "Dotted lines are my own values recomputed from the daily data; they sit on top of SILSO's "
    "lines almost everywhere. The shaded band marks provisional values."
)

st.subheader("Derived minus published")
recon = data["reconciliation"]
names = {
    "Monthly mean": "monthly_mean",
    "13-month smoothed": "smoothed",
    "Smoothing formula on SILSO's monthly values": "smoothed_formula_on_published_monthly",
}
which = st.segmented_control("Comparison", list(names), default="13-month smoothed")
which = which or "13-month smoothed"
table = recon[
    (recon["comparison"] == names[which])
    & (recon["status"] == "compared")
    & (recon["date"] >= start)
    & (recon["date"] <= end)
]
st.plotly_chart(diff_figure(table), width="stretch")
st.caption(
    "Dotted lines show the ±0.05 tolerance. Orange points are half-way ties: the unrounded value "
    "ends exactly in 5 at the second decimal and SILSO rounded it the other way."
)

with st.expander("Data in this range"):
    wide = pd.concat(
        {name: pd.Series(s["y"].to_numpy(), index=s["x"].to_numpy()) for name, s in series.items()},
        axis=1,
    ).sort_index()
    wide.index.name = "date"
    st.dataframe(wide, width="stretch", height=300)
    st.download_button(
        "Download (CSV)",
        wide.to_csv(date_format="%Y-%m-%d").encode(),
        file_name=f"sunspots_{start:%Y%m%d}_{end:%Y%m%d}.csv",
        mime="text/csv",
    )

attribution_note()
