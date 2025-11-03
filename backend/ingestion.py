import asyncio
import json
import threading
from typing import Iterable, List

import websockets

from .storage import TickStore

BINANCE_WS = "wss://fstream.binance.com/ws/{stream}"


class IngestionService:
    """
    Manages background asyncio tasks to ingest Binance futures trade ticks
    for a set of symbols and persist to SQLite via TickStore.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.store = TickStore(db_path)
        self._symbols: List[str] = []
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()

    def start(self, symbols: Iterable[str]):
        syms = sorted({s.lower() for s in symbols})
        if syms == self._symbols and self.is_running:
            return
        self.stop()
        self._symbols = syms
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_thread, name="IngestionThread", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cancel_all_tasks(), self._loop).result(timeout=2)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None
        self._loop = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    async def _cancel_all_tasks(self):
        for task in asyncio.all_tasks(loop=self._loop):
            task.cancel()

    def _run_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run(self._symbols))
        finally:
            pending = asyncio.all_tasks(loop=self._loop)
            for t in pending:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()

    async def _run(self, symbols: List[str]):
        tasks = [asyncio.create_task(self._consume_symbol(sym)) for sym in symbols]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _consume_symbol(self, symbol: str):
        stream = f"{symbol}@trade"
        url = BINANCE_WS.format(stream=stream)
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=15, ping_timeout=20, close_timeout=5) as ws:
                    backoff = 1.0
                    async for msg in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            data = json.loads(msg)
                            ts_ms = int(data.get("E") or data.get("T") or 0)
                            price = float(data["p"]) if "p" in data else float(data.get("price", 0))
                            qty = float(data["q"]) if "q" in data else float(data.get("qty", 0))
                            sym = (data.get("s") or symbol).upper()
                            if ts_ms and price > 0 and qty >= 0:
                                self.store.insert_tick(ts_ms, sym, price, qty)
                        except Exception:
                            continue
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
