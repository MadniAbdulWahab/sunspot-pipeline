"""Plotly figures shared by the pages."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.data import COLOURS


def base_layout(fig: go.Figure, y_title: str, height: int = 460) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        yaxis_title=y_title,
    )
    fig.update_xaxes(showgrid=False, showspikes=True, spikemode="across", spikethickness=1)
    fig.update_yaxes(gridwidth=1, zeroline=False, rangemode="tozero")
    return fig


def add_line(fig, x, y, name, colour, dash="solid", width=2, gl=False, opacity=1.0):
    trace = go.Scattergl if gl else go.Scatter
    fig.add_trace(
        trace(
            x=x,
            y=y,
            name=name,
            mode="lines",
            line=dict(color=colour, width=width, dash=dash),
            opacity=opacity,
            hovertemplate="%{y:.1f}",
            connectgaps=False,
        )
    )


def mark_provisional(fig: go.Figure, first_provisional: pd.Timestamp | None, x_end) -> None:
    if first_provisional is None or pd.isna(first_provisional):
        return
    fig.add_vrect(
        x0=first_provisional,
        x1=x_end,
        fillcolor="#9a9893",
        opacity=0.12,
        line_width=0,
        annotation_text="provisional",
        annotation_position="top left",
    )


def series_figure(series: dict[str, dict], first_provisional=None, height: int = 460) -> go.Figure:
    """series: name -> {x, y, colour, dash, gl}"""

    fig = go.Figure()
    x_end = None
    for name, s in series.items():
        add_line(
            fig,
            s["x"],
            s["y"],
            name,
            s["colour"],
            dash=s.get("dash", "solid"),
            width=s.get("width", 2),
            gl=s.get("gl", False),
            opacity=s.get("opacity", 1.0),
        )
        if len(s["x"]):
            last = pd.Series(s["x"]).max()
            x_end = last if x_end is None else max(x_end, last)
    if x_end is not None:
        mark_provisional(fig, first_provisional, x_end)
    return base_layout(fig, "Sunspot number", height)


def diff_figure(table: pd.DataFrame) -> go.Figure:
    """Derived minus published, one point per compared month, coloured by result."""

    fig = go.Figure()
    styles = {
        "match": ("Within tolerance", COLOURS["monthly"]),
        "rounding_tie": ("Rounding tie", COLOURS["smoothed"]),
        "mismatch": ("Mismatch", COLOURS["critical"]),
    }
    for result, (label, colour) in styles.items():
        sub = table[table["result"] == result]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scattergl(
                x=sub["date"],
                y=sub["diff"],
                name=f"{label} ({len(sub)})",
                mode="markers",
                marker=dict(color=colour, size=8 if result != "match" else 5),
                customdata=sub[["derived", "published", "derived_unrounded"]].to_numpy(),
                hovertemplate=(
                    "%{x|%Y-%m}<br>derived %{customdata[0]:.1f} "
                    "(unrounded %{customdata[2]:.4f})<br>published %{customdata[1]:.1f}"
                    "<br>diff %{y:+.2f}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0.05, line_dash="dot", line_width=1, line_color="#9a9893")
    fig.add_hline(y=-0.05, line_dash="dot", line_width=1, line_color="#9a9893")
    fig = base_layout(fig, "Derived − published", 300)
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(rangemode="normal", zeroline=True)
    return fig
