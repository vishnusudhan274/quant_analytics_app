# Quant Analytics Dashboard

Run:

1. Install Python 3.10+ and dependencies:
   - `pip install -r requirements.txt`
2. Start the app:
   - `streamlit run app.py`

Notes:
- Connects to Binance Futures trade streams for selected symbols and computes OHLCV, Z-score, rolling correlation, hedge ratio, and optional ADF.
- Data is stored locally in `data/ticks.db` (SQLite).
- Live updates occur each second when enabled.
