import logging
import time

import pandas as pd
import requests

from brokers.base import BaseBroker

logger = logging.getLogger(__name__)


class CapitalClient(BaseBroker):
    """Read-only Capital.com demo API client for research."""

    BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

    def __init__(self, api_key: str, identifier: str, password: str):
        self.api_key = api_key
        self.identifier = identifier
        self.password = password
        self.cst: str | None = None
        self.security_token: str | None = None
        self._last_auth: float = 0
        self._connected = False

    def authenticate(self) -> bool:
        try:
            resp = requests.post(
                f"{self.BASE_URL}/session",
                headers={"X-CAP-API-KEY": self.api_key},
                json={
                    "identifier": self.identifier,
                    "password": self.password,
                    "encryptedPassword": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            self.cst = resp.headers.get("CST")
            self.security_token = resp.headers.get("X-SECURITY-TOKEN")
            self._last_auth = time.time()
            self._connected = True
            logger.info("Authenticated with Capital.com demo API")
            return True
        except Exception as e:
            logger.warning("Capital.com auth failed: %s", e)
            self._connected = False
            return False

    def connect(self) -> bool:
        """Connect to Capital.com API (alias for authenticate)."""
        return self.authenticate()

    def disconnect(self) -> None:
        """No persistent connection to close."""
        self._connected = False

    @property
    def connected(self) -> bool:
        if not self._connected:
            return False
        # Re-auth if tokens may have expired (10 min)
        if time.time() - self._last_auth > 540:
            return self.authenticate()
        return True

    def _headers(self) -> dict:
        return {
            "X-CAP-API-KEY": self.api_key,
            "CST": self.cst or "",
            "X-SECURITY-TOKEN": self.security_token or "",
            "Content-Type": "application/json",
        }

    def _ensure_connected(self) -> bool:
        if not self.connected:
            return self.authenticate()
        return True

    def get_prices(self, epic: str, resolution: str = "DAY", max_bars: int = 50) -> pd.DataFrame | None:
        if not self._ensure_connected():
            return None
        try:
            resp = requests.get(
                f"{self.BASE_URL}/prices/{epic}",
                headers=self._headers(),
                params={"resolution": resolution, "max": max_bars},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            prices = data.get("prices", [])
            if not prices:
                logger.warning("No prices returned for %s", epic)
                return None

            rows = []
            for p in prices:
                close_price = p.get("closePrice", {})
                rows.append(
                    {
                        "date": p.get("snapshotTimeUTC", ""),
                        "open": (p.get("openPrice", {}).get("bid", 0) + p.get("openPrice", {}).get("ask", 0)) / 2,
                        "high": (p.get("highPrice", {}).get("bid", 0) + p.get("highPrice", {}).get("ask", 0)) / 2,
                        "low": (p.get("lowPrice", {}).get("bid", 0) + p.get("lowPrice", {}).get("ask", 0)) / 2,
                        "close": (close_price.get("bid", 0) + close_price.get("ask", 0)) / 2,
                        "volume": p.get("lastTradedVolume", 0),
                    }
                )
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.error("Error fetching %s from Capital.com: %s", epic, e)
            return None

    def get_historical_bars(self, symbol: str, duration: str = "50 D", bar_size: str = "1 day") -> pd.DataFrame | None:
        """Fetch historical bars via get_prices (BaseBroker interface)."""
        # Map duration string to max_bars approximation
        max_bars = 50
        if duration:
            parts = duration.strip().split()
            if len(parts) == 2:
                try:
                    num = int(parts[0])
                    unit = parts[1].upper()
                    if unit.startswith("D"):
                        max_bars = num
                    elif unit.startswith("M"):
                        max_bars = num * 30
                    elif unit.startswith("Y"):
                        max_bars = num * 365
                except ValueError:
                    pass

        # Map bar_size to Capital.com resolution
        resolution = "DAY"
        if bar_size and "hour" in bar_size.lower():
            resolution = "HOUR"
        elif bar_size and "min" in bar_size.lower():
            resolution = "MINUTE_15"

        return self.get_prices(symbol, resolution=resolution, max_bars=max_bars)

    def get_current_price(self, symbol: str) -> dict | None:
        """Return {open, high, low, close} for the latest bar, or None."""
        df = self.get_prices(symbol, max_bars=1)
        if df is None or len(df) == 0:
            return None
        latest = df.iloc[-1]
        return {
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "close": float(latest["close"]),
        }

    def search_markets(self, term: str, limit: int = 10) -> list[dict]:
        if not self._ensure_connected():
            return []
        try:
            resp = requests.get(
                f"{self.BASE_URL}/markets",
                headers=self._headers(),
                params={"searchTerm": term, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("markets", [])
        except Exception as e:
            logger.error("Market search error: %s", e)
            return []

    def get_client_sentiment(self, market_id: str) -> dict | None:
        if not self._ensure_connected():
            return None
        try:
            resp = requests.get(
                f"{self.BASE_URL}/clientsentiment/{market_id}",
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error("Sentiment error for %s: %s", market_id, e)
            return None

    def ping(self) -> bool:
        try:
            requests.get(f"{self.BASE_URL}/ping", headers=self._headers(), timeout=5)
            return True
        except Exception:
            return False
