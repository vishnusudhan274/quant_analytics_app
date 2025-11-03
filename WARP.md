# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Commands

### Setup
```powershell
# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```powershell
# Start the Streamlit dashboard
streamlit run app.py
```

### Testing
No formal test suite is currently configured. Manual testing is done through the Streamlit UI.

## Project Overview

This is a **Quant Analytics Dashboard** for real-time cryptocurrency pairs trading analysis. It streams live trade data from Binance Futures WebSocket API, computes statistical metrics for pairs trading strategies (spread, z-score, correlation, hedge ratios), and provides visualization and backtesting capabilities.

## Architecture

### Data Flow
1. **Ingestion** (`backend/ingestion.py`) → WebSocket connections pull live trade ticks from Binance Futures
2. **Storage** (`backend/storage.py`) → Ticks are persisted to SQLite (`data/ticks.db`) with thread-safe writes
3. **Analytics** (`backend/analytics.py`) → Resampled OHLCV data is computed on-demand; statistical functions calculate hedge ratios, spreads, z-scores
4. **Presentation** (`app.py`) → Streamlit dashboard displays charts and metrics with 1-second live updates

### Key Components

#### `backend/ingestion.py` - IngestionService
- Runs background asyncio tasks in a separate daemon thread to avoid blocking Streamlit
- Each symbol gets its own WebSocket connection to `wss://fstream.binance.com/ws/{symbol}@trade`
- Exponential backoff reconnection logic on failures
- Thread-safe lifecycle: `start()`, `stop()`, `is_running`
- **Important**: The service is a singleton stored in `st.session_state["ingestor"]`

#### `backend/storage.py` - TickStore
- SQLite schema: `ticks(ts_ms INTEGER, symbol TEXT, price REAL, qty REAL)`
- Index: `idx_ticks_symbol_ts` for efficient symbol+time queries
- Thread-safe operations via `threading.RLock()`
- `resample_ohlcv()` performs pandas resampling to 1s/1m/5m timeframes on lookback windows
- **Important**: All timestamps are stored in milliseconds (UTC), converted to timezone-naive datetime for pandas

#### `backend/analytics.py`
Stateless pure functions for quantitative analysis:
- `ols_hedge_ratio()`: Computes OLS regression slope (beta) between two price series
- `spread_series()`: Calculates `y - hedge_ratio * x`
- `rolling_zscore()`: Z-score normalization over rolling window
- `rolling_corr()`: Rolling correlation between two series
- `adf_test()`: Augmented Dickey-Fuller test for spread stationarity
- `simple_mr_backtest()`: Mean-reversion backtest assuming unit positions, zero costs

#### `backend/alerts.py`
- `ZScoreAlert`: Threshold-based alert system for z-score extremes
- Returns warning messages when |z| >= threshold

#### `app.py` - Main Dashboard
- **Streamlit session state management**: Ingestion service persists across reruns
- **Live update loop**: When enabled, `st.experimental_rerun()` triggers every 1 second
- **UI Structure**:
  - Sidebar: Symbol selection (exactly 2 required), timeframe, lookback, window size, regression type, alert threshold
  - Main area: Side-by-side candlestick charts, spread/z-score plot, rolling correlation plot
  - Expandable backtest section with configurable entry/exit z-score levels
  - CSV export of analytics data

### Important Patterns

#### Thread Safety
- SQLite connection uses `check_same_thread=False` with manual RLock for writes
- Ingestion runs in separate thread with asyncio event loop to prevent blocking Streamlit's main thread
- `st.session_state` persists the ingestion service across Streamlit reruns

#### State Management
- Ingestion service is lazily initialized and stored in `st.session_state["ingestor"]`
- Service automatically restarts if symbol selection changes
- Live update checkbox controls `st.experimental_rerun()` infinite loop

#### Data Resampling Strategy
- Raw ticks are always stored; OHLCV is computed on-demand per query
- Lookback windows are time-based (minutes), not bar-based
- Empty dataframes are handled gracefully with `st.info("Waiting for data...")`

#### WebSocket Error Handling
- No explicit logging; silent retries with exponential backoff (1s → 2s → 4s → ... → 30s max)
- Invalid messages are caught and skipped (`except Exception: continue`)
- Connection failures trigger reconnection attempts indefinitely until `stop_event` is set

## Code Conventions

### Module Structure
- `app.py`: UI-only, minimal business logic
- `backend/`: Pure functions and services with no Streamlit dependencies
- Separation allows backend modules to be imported independently (e.g., for future CLI tools or scheduled jobs)

### Naming
- Variables use snake_case: `sym_a`, `close_b`, `ohlc_a`
- Constants use UPPER_SNAKE_CASE: `BINANCE_WS`, `DATA_DIR`
- Type hints are used throughout

### Dependencies
- **Streamlit**: UI framework (note: uses `st.experimental_rerun()` which may be deprecated in future versions)
- **websockets**: Async WebSocket client for Binance API
- **pandas**: Time series manipulation and resampling
- **plotly**: Interactive charts (Candlestick, Scatter)
- **statsmodels**: ADF test for stationarity
- **numpy**: Numerical operations

## Data Persistence

### SQLite Database
- Location: `data/ticks.db`
- **Not version controlled** (excluded in .gitignore)
- Schema is auto-created on first run via `CREATE TABLE IF NOT EXISTS`
- No migrations system; schema changes require manual DB deletion or ALTER statements

### Directory Structure
```
.
├── app.py                 # Main Streamlit dashboard
├── backend/
│   ├── ingestion.py       # WebSocket data ingestion
│   ├── storage.py         # SQLite persistence + resampling
│   ├── analytics.py       # Statistical computations
│   └── alerts.py          # Alert logic
├── data/
│   └── ticks.db           # SQLite database (gitignored)
├── requirements.txt       # Python dependencies
└── README.md              # Basic usage instructions
```

## Limitations & Known Behaviors

### Performance
- Live update mode refreshes entire UI every second, which is CPU-intensive for large lookback windows
- SQLite reads are not optimized beyond basic indexing; very large datasets (millions of ticks) may slow down resampling

### Error Handling
- WebSocket errors are silently retried; no user-facing error messages for connection failures
- Invalid or missing data results in empty plots with "Waiting for data..." messages
- ADF test requires minimum 10 data points; returns NaN otherwise

### Stateless Design
- No user accounts or authentication
- No trade execution or broker integration
- All data is local; no cloud storage or multi-user support

## Development Notes

### Adding New Symbols
Update the `SYMBOLS_ALL` list in `app.py`. Binance Futures symbol format is lowercase (e.g., `btcusdt`).

### Adding New Timeframes
1. Add timeframe string to selectbox in `app.py`
2. Implement corresponding pandas frequency in `TickStore._tf_to_pandas_freq()` (e.g., `"15m"` → `"15T"`)

### Extending Analytics
Add new functions to `backend/analytics.py` following the pattern:
- Accept `pd.Series` inputs
- Return `pd.Series` or scalar outputs
- Handle NaN/empty data gracefully
- Use `align_series()` helper for time-aligning two series

### Debugging Ingestion
- Check if thread is running: `st.session_state["ingestor"].is_running`
- Verify WebSocket URL format: `wss://fstream.binance.com/ws/{symbol}@trade`
- Query raw ticks directly: `store.fetch_ticks([symbol], since_ms=...)`
