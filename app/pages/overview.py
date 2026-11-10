import pandas as pd
import streamlit as st

from app.charts import series_figure
from app.data import COLOURS, attribution_note, require_run

data = require_run()
manifest = data["manifest"]
quality = data["quality_report"]
recon = data["reconciliation_report"]

st.title("Sunspot numbers, checked and archived")
st.write(
    "This app runs a small data pipeline over the WDC-SILSO sunspot number series. It downloads "
    "the daily, monthly and 13-month smoothed files, validates every row, recomputes the monthly "
    "means and the smoothed series from the daily data, checks them against SILSO's published "
    "values and archives each run with checksums."
)

monthly = data["monthly_published_flagged"].dropna(subset=["value"])
smoothed = data["smoothed_published_flagged"].dropna(subset=["value"])
last_m = monthly.iloc[-1]
last_s = smoothed.iloc[-1]
comparisons = {c["comparison"]: c for c in recon["comparisons"]}

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    f"Monthly mean, {last_m['date']:%b %Y}",
    f"{last_m['value']:.1f}",
    help="Latest published monthly mean total sunspot number"
    + (" (provisional)" if last_m["flag_provisional"] else ""),
)
c2.metric(
    f"13-month smoothed, {last_s['date']:%b %Y}",
    f"{last_s['value']:.1f}",
    help="The smoothed series always ends 6 months before the monthly series.",
)
quality_icon = {
    "ok": ":material/check_circle:",
    "warnings": ":material/warning:",
    "errors": ":material/error:",
}
c3.metric("Data quality", quality["status"].upper(), help="Worst status over all checks in this run")
c4.metric(
    "Reconciliation",
    "PASS" if recon["passed"] else "FAIL",
    help="Derived values vs SILSO's published values, rounded half-up, tolerance 0.05",
)

st.subheader("Monthly mean and 13-month smoothed sunspot number")
first_prov = monthly.loc[monthly["flag_provisional"], "date"].min()
fig = series_figure(
    {
        "Monthly mean": {
            "x": monthly["date"],
            "y": monthly["value"],
            "colour": COLOURS["monthly"],
            "width": 1,
        },
        "13-month smoothed": {"x": smoothed["date"], "y": smoothed["value"], "colour": COLOURS["smoothed"]},
    },
    first_provisional=first_prov,
)
st.plotly_chart(fig, width="stretch")

st.subheader("This run")
m = comparisons["monthly_mean"]
s = comparisons["smoothed"]
left, right = st.columns(2)
with left:
    st.markdown(
        f"""
- **Run** `{manifest["run_id"]}` (pipeline v{manifest["pipeline_version"]})
- **Fetched** {pd.Timestamp(manifest["started_at"]):%Y-%m-%d %H:%M} UTC
- **Daily data** {manifest["data_range"]["daily"][0]} to {manifest["data_range"]["daily"][1]}
- **Monthly data** {manifest["data_range"]["monthly"][0][:7]} to {manifest["data_range"]["monthly"][1][:7]}
- **Quality** {quality_icon[quality["status"]]} {quality["status"]}
"""
    )
with right:
    st.markdown(
        f"""
- **Monthly means** from daily data: {m["exact_matches"]} of {m["n"]} months match SILSO exactly
  ({m["first_compared"]} to {m["last_compared"]}), {m["mismatches"]} mismatches.
- **Smoothed series**: {s["within_tolerance"]} of {s["n"]} months within 0.05,
  {s["rounding_ties"]} explained half-way rounding ties, {s["mismatches"]} mismatches.
- Not derivable: {", ".join(m["published_only_in_derived_range"]) or "none"}
  (no daily observations that month).
"""
    )

attribution_note()
