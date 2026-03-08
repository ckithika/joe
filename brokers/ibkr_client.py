import logging

import pandas as pd

from brokers.base import BaseBroker

logger = logging.getLogger(__name__)


class IBKRClient(BaseBroker):
    """Read-only IBKR paper trading client for research."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1, timeout: int = 30):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self.ib = None
        self._connected = False

    def connect(self) -> bool:
        try:
            from ib_insync import IB

            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            logger.info("Connected to IBKR at %s:%s", self.host, self.port)
            return True
        except Exception as e:
            logger.warning("IBKR connection failed: %s", e)
            self._connected = False
            return False

    def disconnect(self):
        if self.ib and self._connected:
            self.ib.disconnect()
            self._connected = False
            logger.info("Disconnected from IBKR")

    @property
    def connected(self) -> bool:
        return self._connected and self.ib is not None

    def get_historical_bars(self, symbol: str, duration: str = "50 D", bar_size: str = "1 day") -> pd.DataFrame | None:
        if not self.connected:
            logger.warning("IBKR not connected, cannot fetch %s", symbol)
            return None
        try:
            from ib_insync import Index, Stock, util

            # VIX is a CBOE index, not a stock
            if symbol.upper() == "VIX":
                contract = Index("VIX", "CBOE")
                what_to_show = "TRADES"
            else:
                contract = Stock(symbol, "SMART", "USD")
                what_to_show = "TRADES"

            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=True,
                timeout=self.timeout,
            )
            if not bars:
                logger.warning("No bars returned for %s", symbol)
                return None
            df = util.df(bars)
            df.columns = [c.lower() for c in df.columns]
            return df
        except Exception as e:
            logger.error("Error fetching %s from IBKR: %s", symbol, e)
            return None

    def get_current_price(self, symbol: str) -> dict | None:
        """Return {open, high, low, close} for the latest bar, or None."""
        df = self.get_historical_bars(symbol, duration="5 D", bar_size="1 day")
        if df is None or len(df) == 0:
            return None
        latest = df.iloc[-1]
        return {
            "open": float(latest.get("open", 0)),
            "high": float(latest.get("high", 0)),
            "low": float(latest.get("low", 0)),
            "close": float(latest.get("close", 0)),
        }

    def ping(self) -> bool:
        """Check connectivity by attempting to connect if not already connected."""
        if self.connected:
            return True
        return self.connect()

    def run_scanner(self, scan_code: str, num_results: int = 25) -> list[str]:
        if not self.connected:
            logger.warning("IBKR not connected, cannot run scanner")
            return []
        try:
            from ib_insync import ScannerSubscription

            sub = ScannerSubscription(
                instrument="STK",
                locationCode="STK.US.MAJOR",
                scanCode=scan_code,
                numberOfRows=num_results,
            )
            results = self.ib.reqScannerData(sub)
            symbols = [r.contractDetails.contract.symbol for r in results]
            logger.info("Scanner %s returned %d results", scan_code, len(symbols))
            return symbols
        except Exception as e:
            logger.error("Scanner error: %s", e)
            return []
