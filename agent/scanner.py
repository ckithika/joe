import logging
from pathlib import Path

import yaml

from agent.models import Broker, Instrument, SECTOR_MAP
from brokers.ibkr_client import IBKRClient
from brokers.capital_client import CapitalClient

logger = logging.getLogger(__name__)


class MarketScanner:
    """Fetches instruments from both brokers and builds the scan universe."""

    def __init__(
        self,
        ibkr: IBKRClient | None = None,
        capital: CapitalClient | None = None,
        config_path: str = "config/watchlist.yaml",
    ):
        self.ibkr = ibkr
        self.capital = capital
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if config_file.exists():
            return yaml.safe_load(config_file.read_text())
        logger.warning("Watchlist config not found at %s, using defaults", path)
        return {
            "ibkr": {"etfs": ["SPY", "QQQ"], "stocks": [], "scan_presets": []},
            "capital": {
                "indices": ["US500"],
                "forex": ["EURUSD"],
                "crypto": ["BTCUSD"],
                "commodities": ["GOLD"],
            },
        }

    def scan_ibkr(self) -> list[Instrument]:
        """Fetch IBKR watchlist instruments and scanner results."""
        instruments = []
        ibkr_config = self.config.get("ibkr", {})

        if not self.ibkr or not self.ibkr.connected:
            logger.info("IBKR not available, skipping")
            return instruments

        # Fetch watchlist ETFs and stocks
        tickers = ibkr_config.get("etfs", []) + ibkr_config.get("stocks", [])

        for ticker in tickers:
            df = self.ibkr.get_historical_bars(ticker)
            if df is not None:
                instruments.append(
                    Instrument(
                        ticker=ticker,
                        name=ticker,
                        broker=Broker.IBKR,
                        sector=SECTOR_MAP.get(ticker, ""),
                        ohlcv=df,
                    )
                )
                logger.debug("Loaded %s from IBKR (%d bars)", ticker, len(df))

        # Run scanner presets for dynamic discovery
        for preset in ibkr_config.get("scan_presets", []):
            scanner_results = self.ibkr.run_scanner(preset, num_results=10)
            for ticker in scanner_results:
                if any(i.ticker == ticker for i in instruments):
                    continue  # Skip duplicates
                df = self.ibkr.get_historical_bars(ticker)
                if df is not None:
                    instruments.append(
                        Instrument(
                            ticker=ticker,
                            name=ticker,
                            broker=Broker.IBKR,
                            sector=SECTOR_MAP.get(ticker, ""),
                            ohlcv=df,
                        )
                    )

        logger.info("IBKR scan complete: %d instruments", len(instruments))
        return instruments

    def scan_capital(self) -> list[Instrument]:
        """Fetch Capital.com watchlist instruments."""
        instruments = []
        cap_config = self.config.get("capital", {})

        if not self.capital or not self.capital.connected:
            logger.info("Capital.com not available, skipping")
            return instruments

        # Combine all Capital.com instrument categories
        all_epics = []
        for category in ["indices", "forex", "crypto", "commodities", "stocks"]:
            all_epics.extend(cap_config.get(category, []))

        for epic in all_epics:
            df = self.capital.get_prices(epic)
            if df is not None:
                # Fetch client sentiment for Capital.com instruments
                cap_sentiment = self.capital.get_client_sentiment(epic)
                instruments.append(
                    Instrument(
                        ticker=epic,
                        name=epic,
                        broker=Broker.CAPITAL,
                        epic=epic,
                        sector=SECTOR_MAP.get(epic, ""),
                        ohlcv=df,
                        capital_sentiment=cap_sentiment,
                    )
                )
                logger.debug("Loaded %s from Capital.com (%d bars)", epic, len(df))

        logger.info("Capital.com scan complete: %d instruments", len(instruments))
        return instruments

    def scan_all(self) -> list[Instrument]:
        """Run full scan across both brokers."""
        instruments = self.scan_ibkr() + self.scan_capital()
        logger.info(
            "Full scan complete: %d total instruments "
            "(IBKR: %d, Capital: %d)",
            len(instruments),
            sum(1 for i in instruments if i.broker == Broker.IBKR),
            sum(1 for i in instruments if i.broker == Broker.CAPITAL),
        )
        return instruments
