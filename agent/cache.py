"""Simple file-based market data cache for --dry-run replay."""

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")


def save_instruments(instruments: list) -> None:
    """Cache scanned instruments so --dry-run can replay them."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    for inst in instruments:
        ticker_dir = CACHE_DIR / inst.ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)

        if inst.ohlcv is not None and len(inst.ohlcv) > 0:
            inst.ohlcv.to_csv(ticker_dir / f"{today}.csv", index=False)

        meta = {
            "ticker": inst.ticker,
            "name": inst.name,
            "broker": inst.broker.value,
            "epic": inst.epic,
            "sector": getattr(inst, "sector", ""),
            "date": today,
        }
        (ticker_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    logger.info("Cached %d instruments to %s", len(instruments), CACHE_DIR)


def load_cached_instruments() -> list:
    """Load the most recent cached instruments for dry-run mode."""
    from agent.models import Broker, Instrument

    if not CACHE_DIR.exists():
        logger.warning("No cache directory found at %s", CACHE_DIR)
        return []

    instruments = []
    for ticker_dir in sorted(CACHE_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue

        meta_file = ticker_dir / "meta.json"
        if not meta_file.exists():
            continue

        meta = json.loads(meta_file.read_text())

        # Find most recent CSV
        csvs = sorted(ticker_dir.glob("*.csv"), reverse=True)
        ohlcv = None
        if csvs:
            ohlcv = pd.read_csv(csvs[0])

        instruments.append(
            Instrument(
                ticker=meta["ticker"],
                name=meta.get("name", meta["ticker"]),
                broker=Broker(meta["broker"]),
                epic=meta.get("epic"),
                sector=meta.get("sector", ""),
                ohlcv=ohlcv,
            )
        )

    logger.info("Loaded %d cached instruments from %s", len(instruments), CACHE_DIR)
    return instruments
