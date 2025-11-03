import sqlite3
import threading
from typing import List, Optional
import pandas as pd
from datetime import datetime, timedelta, timezone


class TickStore:
    """
    SQLite-backed tick storage with thread-safe reads/writes.
    Table schema: ticks(ts_ms INTEGER, symbol TEXT, price REAL, qty REAL)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ticks (
                ts_ms INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, ts_ms)")
        self._conn.commit()

    def insert_tick(self, ts_ms: int, symbol: str, price: float, qty: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO ticks(ts_ms, symbol, price, qty) VALUES (?, ?, ?, ?)",
                (int(ts_ms), symbol.upper(), float(price), float(qty)),
            )
            self._conn.commit()

    def fetch_ticks(self, symbols: List[str], since_ms: Optional[int] = None) -> pd.DataFrame:
        syms = [s.upper() for s in symbols]
        placeholders = ",".join(["?"] * len(syms))
        params: List[object] = syms[:]
        q = f"SELECT ts_ms, symbol, price, qty FROM ticks WHERE symbol IN ({placeholders})"
        if since_ms is not None:
            q += " AND ts_ms >= ?"
            params.append(int(since_ms))
        q += " ORDER BY ts_ms ASC"
        with self._lock:
            df = pd.read_sql_query(q, self._conn, params=params)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_convert(None)
        df.set_index("ts", inplace=True)
        return df[["symbol", "price", "qty", "ts_ms"]]

    @staticmethod
    def _tf_to_pandas_freq(tf: str) -> str:
        tf = tf.lower()
        if tf in ("1s", "1sec", "1second"):
            return "1s"
        if tf in ("1m", "1min", "1minute"):
            return "1min"
        if tf in ("5m", "5min", "5minutes"):
            return "5min"
        raise ValueError(f"Unsupported timeframe: {tf}")

    def resample_ohlcv(self, symbol: str, timeframe: str, lookback_minutes: int = 60) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        since = int((now - timedelta(minutes=lookback_minutes)).timestamp() * 1000)
        df = self.fetch_ticks([symbol], since_ms=since)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])  # empty
        sdf = df[df["symbol"] == symbol.upper()][["price", "qty"]].copy()
        freq = self._tf_to_pandas_freq(timeframe)
        ohlc = sdf["price"].resample(freq).ohlc()
        vol = sdf["qty"].resample(freq).sum().rename("volume")
        out = pd.concat([ohlc, vol], axis=1).dropna(how="all")
        return out
