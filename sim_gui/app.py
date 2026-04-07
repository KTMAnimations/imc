"""
Streamlit GUI for the log-aggregated IMC Prosperity backtester.

Run from the repo root:

    streamlit run sim_gui/app.py

The app:
  - lets you upload or point at a trader `.py` file (must define `class Trader`
    with a `run(state)` method)
  - picks a market day from the logs discovered in the repo
  - lets you select which logs to aggregate into the passive liquidity menu
  - runs the simulation and displays final PnL, PnL curve, position history,
    and a trade list
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import traceback
from typing import Dict, List

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from simulator import (  # noqa: E402
    SimResult,
    Timeline,
    build_timeline,
    discover_logs,
    group_logs_by_day,
    load_trader_from_file,
    simulate,
)


# ---------------------------------------------------------------------------
# Page config + caching
# ---------------------------------------------------------------------------


st.set_page_config(
    page_title="Prosperity backtest sim",
    page_icon=None,
    layout="wide",
)


@st.cache_data(show_spinner=False)
def cached_discover_logs(repo_root: str) -> List[str]:
    return discover_logs(repo_root)


@st.cache_data(show_spinner=False)
def cached_group_by_day(log_paths: List[str]) -> Dict[int, List[str]]:
    return group_logs_by_day(log_paths)


@st.cache_resource(show_spinner=False)
def cached_build_timeline(key: str, log_paths: tuple) -> Timeline:
    # `key` is ignored by the function but forces cache-busting when it changes
    return build_timeline(list(log_paths))


# ---------------------------------------------------------------------------
# Sidebar: trader + logs
# ---------------------------------------------------------------------------


st.title("Prosperity Backtest Simulator")
st.caption(
    "Replays a Trader script against aggregated web-backtester logs. "
    "Uses real order book snapshots + a unioned passive-fill menu derived from "
    "every log in the repo for a given market day."
)

with st.sidebar:
    st.header("Trader")
    trader_source = st.radio(
        "Source",
        ["Upload file", "Path on disk"],
        horizontal=True,
    )

    trader_path: str | None = None
    if trader_source == "Upload file":
        uploaded = st.file_uploader(
            "Upload a .py file defining `class Trader`",
            type=["py"],
            key="trader_upload",
        )
        if uploaded is not None:
            tmp_dir = tempfile.mkdtemp(prefix="sim_gui_trader_")
            safe_name = os.path.basename(uploaded.name) or "trader.py"
            tmp_path = os.path.join(tmp_dir, safe_name)
            with open(tmp_path, "wb") as f:
                f.write(uploaded.getbuffer())
            trader_path = tmp_path
            st.caption(f"saved to `{tmp_path}`")
    else:
        default_path = os.path.join(REPO_ROOT, "overfit", "overfit_trader.py")
        typed = st.text_input("Path to trader .py", value=default_path)
        if typed and os.path.isfile(typed):
            trader_path = typed
        elif typed:
            st.error(f"file not found: {typed}")

    st.divider()
    st.header("Logs")

    all_logs = cached_discover_logs(REPO_ROOT)
    groups = cached_group_by_day(all_logs)
    if not groups:
        st.error("No parsable logs found under repo root.")
        st.stop()

    day_options = sorted(groups.keys())
    default_day = max(day_options, key=lambda k: len(groups[k]))
    day = st.selectbox(
        "Market day",
        day_options,
        index=day_options.index(default_day),
        format_func=lambda d: f"day {d} ({len(groups[d])} logs)",
    )

    day_logs = groups[day]
    rel_logs = [os.path.relpath(p, REPO_ROOT) for p in day_logs]
    selected_rel = st.multiselect(
        "Logs to aggregate",
        options=rel_logs,
        default=rel_logs,
        help=(
            "The order book is identical across these (all same day), but "
            "each log contributes its own observed passive fills. Aggregating "
            "more logs = richer passive-fill menu."
        ),
    )
    selected = [os.path.join(REPO_ROOT, p) for p in selected_rel]

    st.divider()
    run_clicked = st.button(
        "Run backtest", type="primary", use_container_width=True, disabled=not selected
    )


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------


if not run_clicked:
    st.info(
        "Configure a trader and logs in the sidebar, then click **Run backtest**."
    )
    if selected:
        with st.expander("Preview selected logs", expanded=False):
            st.write(f"{len(selected)} log(s) selected for day {day}")
            for p in selected_rel:
                st.code(p)
    st.stop()

if trader_path is None:
    st.error("No trader selected.")
    st.stop()


# Build timeline
cache_key = f"{day}|" + "|".join(sorted(selected))
try:
    with st.status("Aggregating logs...", expanded=False) as status:
        t0 = time.perf_counter()
        timeline = cached_build_timeline(cache_key, tuple(sorted(selected)))
        aggr_secs = time.perf_counter() - t0
        menu_rows = sum(
            len(v) for per in timeline.passive_menu.values() for v in per.values()
        )
        status.update(
            label=(
                f"Aggregated {timeline.log_count} log(s) in {aggr_secs:.2f}s — "
                f"{len(timeline.timestamps)} timestamps, "
                f"{menu_rows} passive menu entries"
            ),
            state="complete",
        )
except Exception:
    st.error("Failed to aggregate logs.")
    st.code(traceback.format_exc())
    st.stop()

# Load trader and simulate
try:
    with st.status("Loading trader + running simulation...", expanded=False) as status:
        t0 = time.perf_counter()
        trader = load_trader_from_file(trader_path)
        result: SimResult = simulate(trader, timeline)
        sim_secs = time.perf_counter() - t0
        status.update(
            label=f"Simulation finished in {sim_secs:.2f}s — {len(result.trades)} trades",
            state="complete" if result.error is None else "error",
        )
except Exception:
    st.error("Failed to load or run trader.")
    st.code(traceback.format_exc())
    st.stop()

if result.error:
    st.error("Trader errored mid-run — results below are partial.")
    with st.expander("Traceback", expanded=False):
        st.code(result.error)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


st.subheader("Final PnL")
products = sorted(result.final_pnl.keys())
cols = st.columns(len(products) + 1)
for i, prod in enumerate(products):
    cols[i].metric(prod, f"{result.final_pnl[prod]:.2f}")
cols[-1].metric("TOTAL", f"{result.total_pnl:.2f}")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def _pnl_chart(result: SimResult) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 4))
    ts = result.timestamps
    total_curve = [0.0] * len(ts) if ts else []
    for prod in sorted(result.pnl_history.keys()):
        series = result.pnl_history[prod]
        n = min(len(series), len(ts))
        ax.plot(ts[:n], series[:n], label=prod, linewidth=1.4)
        for i in range(n):
            total_curve[i] += series[i]
    if total_curve:
        ax.plot(
            ts[: len(total_curve)],
            total_curve,
            label="TOTAL",
            color="black",
            linewidth=1.8,
            linestyle="--",
        )
    ax.set_xlabel("timestamp")
    ax.set_ylabel("PnL (mark-to-market)")
    ax.axhline(0, color="grey", linewidth=0.6, alpha=0.6)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    return fig


def _position_chart(result: SimResult, position_limit: int = 80) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 3))
    ts = result.timestamps
    for prod in sorted(result.position_history.keys()):
        series = result.position_history[prod]
        n = min(len(series), len(ts))
        ax.plot(ts[:n], series[:n], label=prod, linewidth=1.2)
    ax.axhline(position_limit, color="red", linewidth=0.6, linestyle=":", alpha=0.6)
    ax.axhline(-position_limit, color="red", linewidth=0.6, linestyle=":", alpha=0.6)
    ax.axhline(0, color="grey", linewidth=0.6, alpha=0.6)
    ax.set_xlabel("timestamp")
    ax.set_ylabel("position")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    return fig


st.subheader("PnL over time")
st.pyplot(_pnl_chart(result), clear_figure=True)

st.subheader("Position over time")
st.pyplot(_position_chart(result), clear_figure=True)


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------


with st.expander(f"Trade log ({len(result.trades)} fills)", expanded=False):
    if result.trades:
        df = pd.DataFrame(
            [
                {
                    "ts": t.ts,
                    "product": t.product,
                    "side": "BUY" if t.qty > 0 else "SELL",
                    "price": t.price,
                    "qty": abs(t.qty),
                    "passive": t.passive,
                }
                for t in result.trades
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        st.download_button(
            "Download trades as CSV",
            data=csv_buf.getvalue(),
            file_name="trades.csv",
            mime="text/csv",
        )
    else:
        st.caption("no trades")


# ---------------------------------------------------------------------------
# Aggregation details
# ---------------------------------------------------------------------------


with st.expander("Aggregation details", expanded=False):
    st.write(f"**Day:** {day}")
    st.write(f"**Logs used:** {timeline.log_count}")
    st.write(f"**Timestamps:** {len(timeline.timestamps)}")
    st.write(f"**Products:** {timeline.products}")
    st.write(f"**Passive menu entries (unioned):** {menu_rows}")
    st.write("**Final mid prices:**")
    st.json(timeline.final_mids)
