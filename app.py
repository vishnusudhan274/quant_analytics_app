"""
Quant Analytics Dashboard

Runnable: streamlit run app.py

Architecture & Design Rationale:
- Python-only stack: Streamlit frontend; background ingestion via websockets; SQLite + pandas for storage/resampling.
- Modularity: backend/ingestion.py (live data), backend/storage.py (persistence + resample), backend/analytics.py (quant functions), backend/alerts.py (rules).
- Storage choice: SQLite is simple, robust, local, and thread-safe enough with a small lock; pandas handles fast resampling.
- Live vs. Resampled: 1s resampling updates continuously; higher TF charts refresh on bar completion.

AI Usage Transparency:
- Project scaffolding and code were assisted by an AI tool per the prompt.
"""

import time
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
import plotly.graph_objs as go
import streamlit as st

from backend.ingestion import IngestionService
from backend.storage import TickStore
from backend.analytics import (
    ols_hedge_ratio,
    spread_series,
    rolling_zscore,
    rolling_corr,
    adf_test,
    simple_mr_backtest,
)
from backend.alerts import ZScoreAlert

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = str(DATA_DIR / "ticks.db")
DATA_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title="Quant Analytics Dashboard", layout="wide")

# Sidebar controls
st.sidebar.header("Controls")
SYMBOLS_ALL = [
    "btcusdt",
    "ethusdt",
    "bnbusdt",
    "xrpusdt",
    "adausdt",
]
sel_symbols: List[str] = st.sidebar.multiselect(
    "Select two symbols", SYMBOLS_ALL, default=["btcusdt", "ethusdt"], max_selections=2
)
if len(sel_symbols) != 2:
    st.warning("Please select exactly two symbols.")

timeframe = st.sidebar.selectbox("Timeframe", ["1s", "1m", "5m"], index=1)
lookback_min = st.sidebar.slider("Lookback (minutes)", 5, 240, 60)
window = st.sidebar.slider("Rolling window", 10, 500, 100)
reg_type = st.sidebar.selectbox("Regression", ["OLS"], index=0)
run_adf = st.sidebar.button("Run ADF test on spread")
alert_th = st.sidebar.slider("Z-score alert threshold", 0.5, 5.0, 2.0, 0.5)
live_update = st.sidebar.checkbox("Live update", value=True)

# Start ingestion singleton
if "ingestor" not in st.session_state:
    st.session_state["ingestor"] = IngestionService(DB_PATH)
if sel_symbols:
    st.session_state["ingestor"].start(sel_symbols)

store = st.session_state["ingestor"].store

# Data loading and resampling
col1, col2 = st.columns(2)
if len(sel_symbols) == 2:
    sym_a, sym_b = [s.upper() for s in sel_symbols]

    ohlc_a = store.resample_ohlcv(sym_a, timeframe, lookback_min)
    ohlc_b = store.resample_ohlcv(sym_b, timeframe, lookback_min)

    # Price charts
    with col1:
        st.subheader(f"{sym_a} {timeframe} OHLCV")
        if not ohlc_a.empty:
            fig_a = go.Figure(
                data=[
                    go.Candlestick(
                        x=ohlc_a.index,
                        open=ohlc_a["open"],
                        high=ohlc_a["high"],
                        low=ohlc_a["low"],
                        close=ohlc_a["close"],
                        name=sym_a,
                    )
                ]
            )
            st.plotly_chart(fig_a, use_container_width=True)
        else:
            st.info("Waiting for data...")

    with col2:
        st.subheader(f"{sym_b} {timeframe} OHLCV")
        if not ohlc_b.empty:
            fig_b = go.Figure(
                data=[
                    go.Candlestick(
                        x=ohlc_b.index,
                        open=ohlc_b["open"],
                        high=ohlc_b["high"],
                        low=ohlc_b["low"],
                        close=ohlc_b["close"],
                        name=sym_b,
                    )
                ]
            )
            st.plotly_chart(fig_b, use_container_width=True)
        else:
            st.info("Waiting for data...")

    # Core analytics
    close_a = ohlc_a["close"].copy()
    close_b = ohlc_b["close"].copy()

    hr = ols_hedge_ratio(close_a, close_b) if reg_type == "OLS" else 1.0
    spr = spread_series(close_a, close_b, hr)
    z = rolling_zscore(spr, window)
    rc = rolling_corr(close_a, close_b, window)

    # Spread & Z-score plot
    st.subheader("Spread and Rolling Z-score")
    fig_s = go.Figure()
    fig_s.add_trace(go.Scatter(x=spr.index, y=spr, name="Spread"))
    fig_s.add_trace(go.Scatter(x=z.index, y=z, name="Z-score", yaxis="y2"))
    fig_s.update_layout(
        yaxis=dict(title="Spread"),
        yaxis2=dict(title="Z-score", overlaying="y", side="right"),
        legend=dict(orientation="h"),
    )
    st.plotly_chart(fig_s, use_container_width=True)

    # Rolling correlation plot
    st.subheader("Rolling Correlation")
    fig_c = go.Figure()
    fig_c.add_trace(go.Scatter(x=rc.index, y=rc, name="Rolling Corr"))
    fig_c.update_layout(yaxis=dict(title="Corr [-1,1]"))
    st.plotly_chart(fig_c, use_container_width=True)

    # ADF test on demand
    if run_adf:
        stat, pval = adf_test(spr)
        st.info(f"ADF statistic: {stat:.4f} | p-value: {pval:.4f}")

    # Alerts
    alert = ZScoreAlert(threshold=alert_th)
    z_latest = float(z.dropna().iloc[-1]) if not z.dropna().empty else None
    msg = alert.check(z_latest)
    if msg:
        st.warning(msg)

    # Download processed data
    export_df = pd.DataFrame({
        f"{sym_a}_close": close_a,
        f"{sym_b}_close": close_b,
        "spread": spr,
        "zscore": z,
        "rolling_corr": rc,
    })
    export_csv = export_df.dropna(how="all").to_csv().encode("utf-8")
    st.download_button("Download analytics CSV", data=export_csv, file_name="analytics.csv", mime="text/csv")

    # Optional simple backtest
    with st.expander("Mini Mean-Reversion Backtest"):
        entry = st.slider("Entry Z", 1.0, 4.0, 2.0, 0.5)
        exit = st.slider("Exit Z", 0.0, 2.0, 0.0, 0.5)
        eq = simple_mr_backtest(z, entry=entry, exit=exit)
        if not eq.empty:
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=eq.index, y=eq["equity"], name="Equity"))
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("Not enough data to backtest yet.")

# Live refresh loop (opt-in)
if live_update:
    time.sleep(1)
    st.rerun()
