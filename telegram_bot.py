#!/usr/bin/env python3
"""Interactive Telegram bot for the AI Trading Agent."""

import asyncio
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# Add project root to path so agent/ imports work
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DATA_DIR = Path(__file__).parent / "data"
FINDINGS_DIR = DATA_DIR / "findings"
PAPER_DIR = DATA_DIR / "paper"

CRYPTO_TICKERS = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}

TICKER_NAMES = {
    # Mega-cap tech
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "GOOGL": "Alphabet Inc.",
    "GOOG": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla Inc.",
    # Financials
    "JPM": "JPMorgan Chase",
    "GS": "Goldman Sachs",
    "BAC": "Bank of America",
    "MS": "Morgan Stanley",
    "WFC": "Wells Fargo",
    "C": "Citigroup",
    # Energy
    "XOM": "ExxonMobil",
    "CVX": "Chevron Corp.",
    # ETFs
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "VOO": "Vanguard S&P 500",
    "IWM": "Russell 2000 ETF",
    "DIA": "Dow Jones ETF",
    "SCHD": "Schwab Dividend ETF",
    # Indices
    "US500": "S&P 500",
    "US100": "Nasdaq 100",
    "UK100": "FTSE 100",
    "DE40": "DAX 40",
    # Forex
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    # Crypto
    "BTCUSD": "Bitcoin",
    "ETHUSD": "Ethereum",
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    # Commodities
    "GOLD": "Gold",
    "OIL_CRUDE": "Crude Oil",
    # Other large-caps
    "NFLX": "Netflix Inc.",
    "AMD": "AMD Inc.",
    "INTC": "Intel Corp.",
    "CRM": "Salesforce Inc.",
    "ORCL": "Oracle Corp.",
    "AVGO": "Broadcom Inc.",
    "COST": "Costco Wholesale",
    "PEP": "PepsiCo Inc.",
    "KO": "Coca-Cola Co.",
    "DIS": "Walt Disney Co.",
    "V": "Visa Inc.",
    "MA": "Mastercard Inc.",
    "HD": "Home Depot",
    "UNH": "UnitedHealth Group",
    "JNJ": "Johnson & Johnson",
    "PG": "Procter & Gamble",
    "MRK": "Merck & Co.",
    "ABBV": "AbbVie Inc.",
    "LLY": "Eli Lilly",
    "PFE": "Pfizer Inc.",
    "T": "AT&T Inc.",
    "VZ": "Verizon Comm.",
    "CSCO": "Cisco Systems",
    "ADBE": "Adobe Inc.",
    "PYPL": "PayPal Holdings",
    "SQ": "Block Inc.",
    "SHOP": "Shopify Inc.",
    "UBER": "Uber Technologies",
    "ABNB": "Airbnb Inc.",
    "SNAP": "Snap Inc.",
    "PLTR": "Palantir Tech.",
    "RIVN": "Rivian Automotive",
    "LCID": "Lucid Group",
    "SOFI": "SoFi Technologies",
    "COIN": "Coinbase Global",
    "MSTR": "MicroStrategy",
    "HOOD": "Robinhood Markets",
    "BA": "Boeing Co.",
    "CAT": "Caterpillar Inc.",
    "DE": "Deere & Co.",
    "GM": "General Motors",
    "F": "Ford Motor Co.",
    "WMT": "Walmart Inc.",
    "TGT": "Target Corp.",
    "SBUX": "Starbucks Corp.",
    "MCD": "McDonald's Corp.",
    "NKE": "Nike Inc.",
}


def ticker_display(ticker: str) -> str:
    """Return 'TICKER - Company Name' or just 'TICKER' if unknown."""
    name = TICKER_NAMES.get(ticker)
    return f"{ticker} - {name}" if name else ticker


def is_crypto(ticker: str) -> bool:
    """Check if a ticker is a cryptocurrency."""
    return ticker.upper() in CRYPTO_TICKERS


# ── Data Loading ─────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict | list | None:
    """Load a JSON file — delegates to data_loader for cloud support."""
    from agent.data_loader import load_json_file
    return load_json_file(path)


def _latest_findings() -> dict | None:
    """Load today's findings, falling back to the most recent file."""
    from agent.data_loader import list_json_files
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_json(FINDINGS_DIR / f"{today}.json")
    if data:
        return data
    files = list_json_files(FINDINGS_DIR, "*.json")
    if files:
        return _load_json(files[0])
    return None


def load_regime() -> dict | None:
    findings = _latest_findings()
    return findings.get("regime") if findings else None


def load_ai_summary() -> str | None:
    findings = _latest_findings()
    return findings.get("ai_summary") if findings else None


def load_risk() -> dict | None:
    findings = _latest_findings()
    return findings.get("risk") if findings else None


def load_after_hours() -> dict | None:
    findings = _latest_findings()
    return findings.get("after_hours") if findings else None


def load_signals(crypto: bool = False) -> list:
    findings = _latest_findings()
    if not findings:
        return []
    signals = findings.get("signals", [])
    return [s for s in signals if is_crypto(s.get("ticker", "")) == crypto]


def load_earnings() -> list:
    findings = _latest_findings()
    if not findings:
        return []
    return findings.get("stock_intelligence", {}).get("upcoming_earnings", [])


def load_market_breadth() -> dict | None:
    findings = _latest_findings()
    if not findings:
        return None
    return findings.get("stock_intelligence", {}).get("market_breadth")


def load_sector_performance() -> list:
    findings = _latest_findings()
    if not findings:
        return []
    return findings.get("stock_intelligence", {}).get("sector_performance", [])


def load_insider_trades() -> list:
    findings = _latest_findings()
    if not findings:
        return []
    return findings.get("stock_intelligence", {}).get("insider_trades", [])


def load_crypto_intel() -> dict | None:
    findings = _latest_findings()
    if not findings:
        return None
    return findings.get("crypto_intelligence")


def load_open_positions() -> list:
    return _load_json(PAPER_DIR / "open_positions.json") or []


def load_performance() -> dict | None:
    return _load_json(PAPER_DIR / "performance.json")


def load_analytics() -> dict | None:
    return _load_json(PAPER_DIR / "portfolio_analytics.json")


def load_trade_history(n: int = 5) -> list[dict]:
    """Load last N rows from trade_history.csv."""
    path = PAPER_DIR / "trade_history.csv"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            reader = list(csv.DictReader(f))
        return reader[-n:] if reader else []
    except Exception:
        return []


def load_api_health() -> dict | None:
    return _load_json(PAPER_DIR / "api_health.json")


# ── Formatters ───────────────────────────────────────────────────────────────


def format_regime() -> str:
    regime = load_regime()
    if not regime:
        return "❌ No regime data available."
    r = regime.get("regime", "unknown").replace("_", " ").title()
    conf = regime.get("confidence", 0)
    adx = regime.get("adx", 0)
    vix = regime.get("vix", 0)
    strategies = ", ".join(regime.get("active_strategies", []))
    size_mod = regime.get("position_size_modifier", 1.0)
    return (
        f"🌡️ <b>Market Regime</b>\n\n"
        f"<b>Regime:</b> {r}\n"
        f"<b>Confidence:</b> {conf:.0%}\n"
        f"<b>ADX:</b> {adx:.1f}\n"
        f"<b>VIX:</b> {vix:.1f}\n"
        f"<b>Active Strategies:</b> {strategies or 'None'}\n"
        f"<b>Position Size Modifier:</b> {size_mod:.2f}"
    )


def format_ai_summary() -> str:
    summary = load_ai_summary()
    if not summary:
        return "❌ No AI summary available."
    text = summary[:3800]
    return f"🤖 <b>AI Summary</b>\n\n{text}"


def format_risk() -> str:
    risk = load_risk()
    if not risk:
        return "❌ No risk data available."
    level = str(risk.get("risk_level", "unknown")).replace("RiskLevel.", "")
    score = risk.get("composite_score", 0)
    emoji_map = {
        "LOW": "🟢", "MODERATE": "🟡", "ELEVATED": "🟠",
        "HIGH": "🔴", "EXTREME": "🔴",
    }
    emoji = emoji_map.get(level.upper(), "⚪")
    text = f"⚠️ <b>Risk Assessment</b>\n\n"
    text += f"{emoji} <b>Level:</b> {level.title()}\n"
    text += f"<b>Composite Score:</b> {score:.1f}\n"

    full_risk = _load_json(PAPER_DIR / "risk_assessment.json")
    if full_risk and "dimensions" in full_risk:
        text += "\n<b>Dimensions:</b>\n"
        for dim, val in full_risk["dimensions"].items():
            if isinstance(val, dict):
                s = val.get("score", 0)
                text += f"  • {dim.title()}: {s:.1f}\n"
            else:
                text += f"  • {dim.title()}: {val:.1f}\n"

    if full_risk and full_risk.get("alerts"):
        text += "\n<b>Alerts:</b>\n"
        for alert in full_risk["alerts"][:5]:
            sev = alert.get("severity", "info")
            msg = alert.get("message", "")
            text += f"  ⚠ [{sev}] {msg}\n"

    return text


def format_after_hours() -> str:
    ah = load_after_hours()
    if not ah:
        return "❌ No after-hours data available."
    session = ah.get("session", "unknown")
    text = f"🌙 <b>After-Hours Intel</b>\n\n"
    text += f"<b>Session:</b> {session.replace('_', ' ').title()}\n"

    gaps = ah.get("earnings_gaps", [])
    if gaps:
        text += "\n<b>Earnings Gaps:</b>\n"
        for g in gaps[:5]:
            t = g.get("ticker", "?")
            gap = g.get("gap_pct", 0)
            direction = "⬆️" if gap > 0 else "⬇️"
            text += f"  {direction} {ticker_display(t)}: {gap:+.1f}%\n"

    movers = ah.get("pre_market_movers", [])
    if movers:
        text += "\n<b>Pre-Market Movers:</b>\n"
        for m in movers[:5]:
            t = m.get("ticker", "?")
            chg = m.get("change_pct", 0)
            direction = "⬆️" if chg > 0 else "⬇️"
            text += f"  {direction} {ticker_display(t)}: {chg:+.1f}%\n"

    crypto = ah.get("crypto_overnight", [])
    if crypto:
        text += "\n<b>Crypto Overnight:</b>\n"
        for c in crypto[:5]:
            sym = c.get("symbol", "?")
            sig = c.get("signal", "?")
            text += f"  • {ticker_display(sym)}: {sig}\n"

    if not gaps and not movers and not crypto:
        text += "\nNo notable after-hours activity detected."

    return text


def format_stock_signals() -> str:
    signals = load_signals(crypto=False)
    if not signals:
        return "📊 <b>Today's Stock Signals</b>\n\nNo signals today."

    text = "📊 <b>Today's Stock Signals</b>\n\n"
    for s in signals:
        t = s.get("ticker", "?")
        signal = s.get("signal", "?")
        score = s.get("score", 0)
        strategy = s.get("strategy", "?")
        action = s.get("action", "?")
        direction = s.get("direction", "?")
        entry = s.get("entry_price", 0)
        action_emoji = {"enter_now": "🟢", "watch": "🟡", "skip": "⚪"}.get(action, "⚪")
        text += (
            f"{action_emoji} <b>{ticker_display(t)}</b>\n"
            f"  Signal: {signal} | Score: {score:.2f}\n"
            f"  Strategy: {strategy} | {direction}\n"
            f"  Entry: ${entry:,.2f}"
        )
        sl = s.get("stop_loss")
        tp = s.get("take_profit")
        if sl:
            text += f" | SL: ${sl:,.2f}"
        if tp:
            text += f" | TP: ${tp:,.2f}"
        text += "\n\n"

    return text[:4000]


def format_earnings() -> str:
    earnings = load_earnings()
    if not earnings:
        return "📅 <b>Earnings Calendar</b>\n\nNo upcoming earnings."
    text = "📅 <b>Earnings Calendar</b>\n\n"
    for e in earnings[:10]:
        t = e.get("ticker", e.get("symbol", "?"))
        date = e.get("date", e.get("report_date", "?"))
        timing = e.get("timing", e.get("time", ""))
        text += f"  • {ticker_display(t)} — {date}"
        if timing:
            text += f" ({timing})"
        text += "\n"
    return text


def format_market_breadth() -> str:
    breadth = load_market_breadth()
    if not breadth:
        return "📈 <b>Market Breadth</b>\n\nNo breadth data available."
    text = "📈 <b>Market Breadth</b>\n\n"
    for k, v in breadth.items():
        label = k.replace("_", " ").title()
        if isinstance(v, float):
            text += f"  <b>{label}:</b> {v:.2f}\n"
        else:
            text += f"  <b>{label}:</b> {v}\n"
    return text


def format_sector_performance() -> str:
    sectors = load_sector_performance()
    if not sectors:
        return "🏭 <b>Sector Performance</b>\n\nNo sector data available."
    text = "🏭 <b>Sector Performance</b>\n\n"
    for s in sectors:
        name = s.get("sector", "?")
        d1 = s.get("change_1d", 0)
        w1 = s.get("change_1w", 0)
        m1 = s.get("change_1m", 0)
        direction = "🟢" if d1 >= 0 else "🔴"
        text += (
            f"{direction} <b>{ticker_display(name)}</b>\n"
            f"  1D: {d1:+.2f}% | 1W: {w1:+.2f}% | 1M: {m1:+.2f}%\n\n"
        )
    return text[:4000]


def format_insider_activity() -> str:
    trades = load_insider_trades()
    if not trades:
        return "🕵️ <b>Insider Activity</b>\n\nNo recent insider trades."
    text = "🕵️ <b>Insider Activity</b>\n\n"
    for t in trades[:10]:
        ticker = t.get("ticker", "?")
        insider = t.get("insider_name", "Unknown")
        txn = t.get("transaction_type", "?")
        shares = t.get("shares", 0)
        value = t.get("value", 0)
        date = t.get("date", "?")
        emoji = "🔴" if txn.lower() == "sell" else "🟢"
        text += (
            f"{emoji} <b>{ticker_display(ticker)}</b>\n"
            f"  {insider} — {txn.upper()}\n"
            f"  {shares:,} shares (${value:,.0f}) on {date}\n\n"
        )
    return text[:4000]


def format_fear_greed() -> str:
    intel = load_crypto_intel()
    if not intel or not intel.get("fear_greed"):
        return "😱 <b>Fear &amp; Greed Index</b>\n\nNo data available."
    fg = intel["fear_greed"]
    value = fg.get("value", 0)
    label = fg.get("classification", "Unknown")
    filled = int(value / 5)  # 20 chars total
    bar = "█" * filled + "░" * (20 - filled)
    if value <= 25:
        emoji = "🔴"
    elif value <= 45:
        emoji = "🟠"
    elif value <= 55:
        emoji = "🟡"
    else:
        emoji = "🟢"
    text = (
        f"😱 <b>Crypto Fear &amp; Greed Index</b>\n\n"
        f"{emoji} <b>{value}</b> — {label}\n\n"
        f"<code>[{bar}] {value}/100</code>\n"
    )
    history = fg.get("history_7d", [])
    if history:
        text += "\n<b>7-Day History:</b>\n"
        for h in history[-7:]:
            if isinstance(h, dict):
                v = h.get("value", 0)
                d = h.get("date", "")
                mini_bar = "█" * int(v / 10) + "░" * (10 - int(v / 10))
                text += f"  {d}: <code>[{mini_bar}]</code> {v}\n"
            else:
                v = int(h)
                mini_bar = "█" * int(v / 10) + "░" * (10 - int(v / 10))
                text += f"  <code>[{mini_bar}]</code> {v}\n"
    return text


def format_btc_eth_overview() -> str:
    intel = load_crypto_intel()
    if not intel:
        return "₿ <b>BTC/ETH Overview</b>\n\nNo data available."
    text = "₿ <b>BTC/ETH Overview</b>\n\n"

    dom = intel.get("dominance", {})
    if dom:
        text += "<b>Market Dominance:</b>\n"
        text += f"  BTC: {dom.get('btc_dominance', 0):.1f}%\n"
        text += f"  ETH: {dom.get('eth_dominance', 0):.1f}%\n"
        mc = dom.get("total_market_cap", 0)
        if mc:
            text += f"  Total Market Cap: ${mc / 1e12:.2f}T\n"
        text += "\n"

    btc_f = intel.get("btc_funding", {})
    eth_f = intel.get("eth_funding", {})
    if btc_f or eth_f:
        text += "<b>Funding Rates:</b>\n"
        if btc_f:
            rate = btc_f.get("rate", 0)
            ann = btc_f.get("annualized", 0)
            text += f"  BTC: {rate:.6f} ({ann:+.1f}% ann.)\n"
        if eth_f:
            rate = eth_f.get("rate", 0)
            ann = eth_f.get("annualized", 0)
            text += f"  ETH: {rate:.6f} ({ann:+.1f}% ann.)\n"
        text += "\n"

    btc_oi = intel.get("btc_open_interest", {})
    eth_oi = intel.get("eth_open_interest", {})
    if btc_oi or eth_oi:
        text += "<b>Open Interest:</b>\n"
        if btc_oi:
            oi = btc_oi.get("open_interest", 0)
            chg = btc_oi.get("change_24h_pct", 0)
            text += f"  BTC: {oi:,.0f} ({chg:+.1f}% 24h)\n"
        if eth_oi:
            oi = eth_oi.get("open_interest", 0)
            chg = eth_oi.get("change_24h_pct", 0)
            text += f"  ETH: {oi:,.0f} ({chg:+.1f}% 24h)\n"
        text += "\n"

    sc = intel.get("stablecoin_supply", {})
    if sc:
        text += "<b>Stablecoin Supply:</b>\n"
        usdt = sc.get("usdt_market_cap", 0)
        usdc = sc.get("usdc_market_cap", 0)
        if usdt:
            text += f"  USDT: ${usdt / 1e9:.1f}B\n"
        if usdc:
            text += f"  USDC: ${usdc / 1e9:.1f}B\n"

    return text


def format_defi_gas() -> str:
    intel = load_crypto_intel()
    if not intel:
        return "🏦 <b>DeFi &amp; Gas</b>\n\nNo data available."
    text = "🏦 <b>DeFi &amp; Gas</b>\n\n"

    defi = intel.get("defi", {})
    if defi:
        tvl = defi.get("total_tvl", 0)
        text += f"<b>Total DeFi TVL:</b> ${tvl / 1e9:.1f}B\n\n"
        protocols = defi.get("top_protocols", [])
        if protocols:
            text += "<b>Top Protocols:</b>\n"
            for p in protocols[:8]:
                name = p.get("name", "?")
                p_tvl = p.get("tvl", 0)
                chg = p.get("change_1d", p.get("change_24h", 0))
                text += f"  • {name}: ${p_tvl / 1e9:.2f}B ({chg:+.1f}%)\n"
        text += "\n"

    gas = intel.get("gas", {})
    if gas:
        gwei = gas.get("gas_price_gwei", 0)
        text += f"⛽ <b>ETH Gas:</b> {gwei:.2f} Gwei\n"

    return text


def format_whale_activity() -> str:
    intel = load_crypto_intel()
    if not intel or not intel.get("whale_activity"):
        return "🐋 <b>Whale Activity</b>\n\nNo data available."
    w = intel["whale_activity"]
    txns = w.get("large_txns_24h", 0)
    flow = w.get("net_exchange_flow", "unknown")
    flow_emoji = {"inflow": "🔴", "outflow": "🟢", "neutral": "🟡"}.get(flow, "⚪")
    text = (
        f"🐋 <b>Whale Activity</b>\n\n"
        f"<b>Large Transactions (24h):</b> {txns:,}\n"
        f"<b>Net Exchange Flow:</b> {flow_emoji} {flow.title()}\n"
    )
    liq = intel.get("liquidation_estimate", {})
    if liq:
        longs = liq.get("long_liquidation_zones", [])
        shorts = liq.get("short_liquidation_zones", [])
        if longs or shorts:
            text += "\n<b>Liquidation Zones:</b>\n"
            if longs:
                text += "  Longs: " + ", ".join(
                    f"${z:,.0f}" if isinstance(z, (int, float)) else str(z)
                    for z in longs[:3]
                ) + "\n"
            if shorts:
                text += "  Shorts: " + ", ".join(
                    f"${z:,.0f}" if isinstance(z, (int, float)) else str(z)
                    for z in shorts[:3]
                ) + "\n"
    return text


def format_crypto_signals() -> str:
    signals = load_signals(crypto=True)
    if not signals:
        return "🌙 <b>Overnight Crypto Signals</b>\n\nNo crypto signals today."
    text = "🌙 <b>Overnight Crypto Signals</b>\n\n"
    for s in signals:
        t = s.get("ticker", "?")
        signal = s.get("signal", "?")
        score = s.get("score", 0)
        strategy = s.get("strategy", "?")
        action = s.get("action", "?")
        direction = s.get("direction", "?")
        entry = s.get("entry_price", 0)
        action_emoji = {"enter_now": "🟢", "watch": "🟡", "skip": "⚪"}.get(action, "⚪")
        text += (
            f"{action_emoji} <b>{ticker_display(t)}</b>\n"
            f"  Signal: {signal} | Score: {score:.2f}\n"
            f"  Strategy: {strategy} | {direction}\n"
            f"  Entry: ${entry:,.2f}\n\n"
        )
    return text[:4000]


def format_open_positions() -> str:
    positions = load_open_positions()
    if not positions:
        return "📂 <b>Open Positions</b>\n\nNo open positions."
    text = "📂 <b>Open Positions</b>\n\n"
    for p in positions:
        t = p.get("ticker", "?")
        direction = p.get("direction", "?")
        entry = p.get("entry_price", 0)
        size = p.get("position_size", 0)
        pnl = p.get("unrealized_pnl", 0)
        days = p.get("days_held", 0)
        strategy = p.get("strategy", "?")
        sl = p.get("stop_loss", 0)
        tp = p.get("take_profit", 0)
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        dir_emoji = "⬆️" if direction == "LONG" else "⬇️"
        text += (
            f"{dir_emoji} <b>{ticker_display(t)}</b>\n"
            f"  {direction} via {strategy}\n"
            f"  Entry: ${entry:,.2f} | Size: {size:.2f}\n"
            f"  SL: ${sl:,.2f} | TP: ${tp:,.2f}\n"
            f"  {pnl_emoji} PnL: ${pnl:,.2f} | Day {days}\n\n"
        )
    return text[:4000]


def format_performance() -> str:
    perf = load_performance()
    if not perf:
        return "💰 <b>Performance Summary</b>\n\nNo performance data."
    balance = perf.get("virtual_balance", 0)
    starting = perf.get("starting_balance", 0)
    total_ret = ((balance - starting) / starting * 100) if starting else 0
    trades = perf.get("total_trades", 0)
    wins = perf.get("wins", 0)
    losses = perf.get("losses", 0)
    expired = perf.get("expired", 0)
    win_rate = (wins / trades * 100) if trades else 0
    return (
        f"💰 <b>Performance Summary</b>\n\n"
        f"<b>Balance:</b> ${balance:,.2f}\n"
        f"<b>Starting:</b> ${starting:,.2f}\n"
        f"<b>Total Return:</b> {total_ret:+.2f}%\n\n"
        f"<b>Total Trades:</b> {trades}\n"
        f"<b>Wins:</b> {wins} | <b>Losses:</b> {losses} | <b>Expired:</b> {expired}\n"
        f"<b>Win Rate:</b> {win_rate:.1f}%"
    )


def format_analytics() -> str:
    a = load_analytics()
    if not a:
        return "📐 <b>Portfolio Analytics</b>\n\nNo analytics data."
    text = "📐 <b>Portfolio Analytics</b>\n\n"
    text += f"<b>Current Balance:</b> ${a.get('current_balance', 0):,.2f}\n"
    text += f"<b>Total Return:</b> {a.get('total_return_pct', 0):+.2f}%\n"
    text += f"<b>Win Rate:</b> {a.get('win_rate', 0):.1f}%\n\n"
    text += "<b>Risk Metrics:</b>\n"
    text += f"  Sharpe Ratio: {a.get('sharpe_ratio', 0):.2f}\n"
    text += f"  Sortino Ratio: {a.get('sortino_ratio', 0):.2f}\n"
    text += f"  Calmar Ratio: {a.get('calmar_ratio', 0):.2f}\n"
    text += f"  Max Drawdown: {a.get('max_drawdown_pct', 0):.2f}%\n"
    text += f"  Current Drawdown: {a.get('current_drawdown_pct', 0):.2f}%\n\n"
    text += "<b>Trade Stats:</b>\n"
    text += f"  Profit Factor: {a.get('profit_factor', 0):.2f}\n"
    text += f"  Expectancy: ${a.get('expectancy', 0):.2f}\n"
    text += f"  Avg Hold Days: {a.get('avg_hold_days', 0):.1f}\n"
    text += f"  Avg R-Multiple: {a.get('avg_r_multiple', 0):.2f}\n"
    return text


def format_trade_history() -> str:
    trades = load_trade_history(5)
    if not trades:
        return "📜 <b>Trade History</b>\n\nNo trade history."
    text = "📜 <b>Recent Trades (Last 5)</b>\n\n"
    for t in reversed(trades):
        ticker = t.get("ticker", "?")
        direction = t.get("direction", "?")
        entry = float(t.get("entry_price", 0))
        exit_p = float(t.get("exit_price", 0))
        pnl = float(t.get("pnl", t.get("realized_pnl", 0)))
        reason = t.get("exit_reason", t.get("reason", "?"))
        date = t.get("exit_date", t.get("date", "?"))
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        text += (
            f"{pnl_emoji} <b>{ticker_display(ticker)}</b> ({direction})\n"
            f"  Entry: ${entry:,.2f} → Exit: ${exit_p:,.2f}\n"
            f"  PnL: ${pnl:,.2f} | {reason} | {date}\n\n"
        )
    return text[:4000]


def format_api_health() -> str:
    health = load_api_health()
    if not health:
        return "🔧 <b>API Health</b>\n\nNo health data available."
    text = "🔧 <b>API Health</b>\n\n"
    if isinstance(health, dict):
        for api, status in health.items():
            if isinstance(status, dict):
                state = status.get("state", status.get("status", "unknown"))
                failures = status.get("failure_count", status.get("failures", 0))
                emoji = "🟢" if state in ("closed", "ok", "healthy") else "🔴"
                text += f"{emoji} <b>{api}:</b> {state}"
                if failures:
                    text += f" ({failures} failures)"
                text += "\n"
            else:
                text += f"  <b>{api}:</b> {status}\n"
    else:
        text += str(health)[:3000]
    return text


# ── AI Q&A ────────────────────────────────────────────────────────────────────


def _build_qa_context() -> str:
    """Build context from current data for Q&A answers."""
    parts = []
    regime = load_regime()
    if regime:
        parts.append(
            f"Market regime: {regime.get('regime', 'unknown')} "
            f"(confidence {regime.get('confidence', 0):.0%}, VIX {regime.get('vix', 0):.1f})"
        )
    perf = load_performance()
    if perf:
        parts.append(
            f"Portfolio: ${perf.get('virtual_balance', 0):,.2f}, "
            f"win rate {perf.get('win_rate', 0):.0%}, "
            f"{perf.get('total_trades', 0)} total trades"
        )
    positions = load_open_positions()
    if positions:
        pos_text = ", ".join(
            f"{p.get('ticker')} {p.get('direction')} (PnL ${p.get('unrealized_pnl', 0):+.2f})"
            for p in positions
        )
        parts.append(f"Open positions: {pos_text}")
    signals = load_signals(crypto=False)[:3]
    if signals:
        sig_text = ", ".join(
            f"{s.get('ticker')} {s.get('signal')} ({s.get('strategy')})"
            for s in signals
        )
        parts.append(f"Top signals: {sig_text}")
    analytics = load_analytics()
    if analytics:
        parts.append(
            f"Sharpe: {analytics.get('sharpe_ratio', 0):.2f}, "
            f"Max DD: {analytics.get('max_drawdown_pct', 0):.1f}%"
        )
    return "\n".join(parts) if parts else "No data available yet."


def _ask_gemini(question: str, context: str) -> str:
    """Send a question to Gemini with trading context."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return "Gemini API key not configured. Set GEMINI_API_KEY in your .env file."

    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        prompt = f"""You are a trading education assistant for a paper trading portfolio.
Answer questions clearly and concisely. Reference the user's live data below when relevant.
Never recommend real trades — this is for educational purposes only.
Keep answers under 300 words.

USER'S LIVE DATA:
{context}

QUESTION: {question}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text[:3800]
    except Exception as e:
        logger.error("Gemini Q&A error: %s", e)
        return f"Sorry, I couldn't process that question. Error: {e}"


# ── Keyboards ────────────────────────────────────────────────────────────────


def main_menu_keyboard() -> InlineKeyboardMarkup:
    from agent.preferences import is_module_enabled
    buttons = [
        [InlineKeyboardButton("📊 Daily Briefing", callback_data="menu_briefing")],
        [InlineKeyboardButton("📈 Stocks", callback_data="menu_stocks")],
    ]
    if is_module_enabled("crypto"):
        buttons.append([InlineKeyboardButton("🪙 Crypto", callback_data="menu_crypto")])
    buttons.extend([
        [InlineKeyboardButton("💼 Portfolio", callback_data="menu_portfolio")],
        [InlineKeyboardButton("🤖 Ask AI", callback_data="menu_ask_ai")],
        [InlineKeyboardButton("⚙️ System", callback_data="menu_system")],
    ])
    return InlineKeyboardMarkup(buttons)


def briefing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌡️ Market Regime", callback_data="briefing_regime")],
        [InlineKeyboardButton("🤖 AI Summary", callback_data="briefing_ai")],
        [InlineKeyboardButton("⚠️ Risk Assessment", callback_data="briefing_risk")],
        [InlineKeyboardButton("🌙 After-Hours Intel", callback_data="briefing_after_hours")],
        [InlineKeyboardButton("« Back", callback_data="back_main")],
    ])


def stocks_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Today's Signals", callback_data="stocks_signals")],
        [InlineKeyboardButton("📅 Earnings Calendar", callback_data="stocks_earnings")],
        [InlineKeyboardButton("📈 Market Breadth", callback_data="stocks_breadth")],
        [InlineKeyboardButton("🏭 Sector Performance", callback_data="stocks_sectors")],
        [InlineKeyboardButton("🕵️ Insider Activity", callback_data="stocks_insider")],
        [InlineKeyboardButton("« Back", callback_data="back_main")],
    ])


def crypto_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("😱 Fear & Greed Index", callback_data="crypto_fear_greed")],
        [InlineKeyboardButton("₿ BTC/ETH Overview", callback_data="crypto_btc_eth")],
        [InlineKeyboardButton("🏦 DeFi & Gas", callback_data="crypto_defi")],
        [InlineKeyboardButton("🐋 Whale Activity", callback_data="crypto_whale")],
        [InlineKeyboardButton("🌙 Overnight Signals", callback_data="crypto_signals")],
        [InlineKeyboardButton("« Back", callback_data="back_main")],
    ])


def portfolio_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Open Positions", callback_data="portfolio_positions")],
        [InlineKeyboardButton("💰 Performance Summary", callback_data="portfolio_performance")],
        [InlineKeyboardButton("📐 Analytics", callback_data="portfolio_analytics")],
        [InlineKeyboardButton("📜 Trade History", callback_data="portfolio_history")],
        [InlineKeyboardButton("« Back", callback_data="back_main")],
    ])


def system_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔧 API Health", callback_data="system_health")],
        [InlineKeyboardButton("▶️ Run Pipeline", callback_data="system_run_pipeline")],
        [InlineKeyboardButton("« Back", callback_data="back_main")],
    ])


# ── Auth ─────────────────────────────────────────────────────────────────────


def authorized(update: Update) -> bool:
    """Only respond to the configured chat ID."""
    return str(update.effective_chat.id) == CHAT_ID


# ── Command Handlers ─────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "🤖 <b>AI Trading Agent</b>\n\nSelect a section:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "🤖 <b>AI Trading Agent — Help</b>\n\n"
        "<b>Commands:</b>\n"
        "/start — Main menu\n"
        "/menu — Main menu\n"
        "/briefing — Quick briefing (regime + AI summary)\n"
        "/positions — Open positions\n"
        "/regime — Market regime\n"
        "/help — This message\n\n"
        "Use the inline buttons to navigate sections.",
        parse_mode="HTML",
    )


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    regime_text = format_regime()
    ai_text = format_ai_summary()
    combined = regime_text + "\n\n" + "─" * 30 + "\n\n" + ai_text
    await update.message.reply_text(
        combined[:4096],
        parse_mode="HTML",
        reply_markup=briefing_keyboard(),
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        format_open_positions(),
        parse_mode="HTML",
        reply_markup=portfolio_keyboard(),
    )


async def cmd_regime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        format_regime(),
        parse_mode="HTML",
        reply_markup=briefing_keyboard(),
    )


# ── Callback Router ──────────────────────────────────────────────────────────

CALLBACK_MAP = {
    # Submenus
    "menu_briefing": (None, briefing_keyboard),
    "menu_stocks": (None, stocks_keyboard),
    "menu_crypto": (None, crypto_keyboard),
    "menu_portfolio": (None, portfolio_keyboard),
    "menu_ask_ai": (None, main_menu_keyboard),
    "menu_system": (None, system_keyboard),
    "back_main": (None, main_menu_keyboard),
    # Briefing
    "briefing_regime": (format_regime, briefing_keyboard),
    "briefing_ai": (format_ai_summary, briefing_keyboard),
    "briefing_risk": (format_risk, briefing_keyboard),
    "briefing_after_hours": (format_after_hours, briefing_keyboard),
    # Stocks
    "stocks_signals": (format_stock_signals, stocks_keyboard),
    "stocks_earnings": (format_earnings, stocks_keyboard),
    "stocks_breadth": (format_market_breadth, stocks_keyboard),
    "stocks_sectors": (format_sector_performance, stocks_keyboard),
    "stocks_insider": (format_insider_activity, stocks_keyboard),
    # Crypto
    "crypto_fear_greed": (format_fear_greed, crypto_keyboard),
    "crypto_btc_eth": (format_btc_eth_overview, crypto_keyboard),
    "crypto_defi": (format_defi_gas, crypto_keyboard),
    "crypto_whale": (format_whale_activity, crypto_keyboard),
    "crypto_signals": (format_crypto_signals, crypto_keyboard),
    # Portfolio
    "portfolio_positions": (format_open_positions, portfolio_keyboard),
    "portfolio_performance": (format_performance, portfolio_keyboard),
    "portfolio_analytics": (format_analytics, portfolio_keyboard),
    "portfolio_history": (format_trade_history, portfolio_keyboard),
    # System
    "system_health": (format_api_health, system_keyboard),
}

SUBMENU_TITLES = {
    "menu_briefing": "📊 <b>Daily Briefing</b>\n\nSelect an item:",
    "menu_stocks": "📈 <b>Stocks</b>\n\nSelect an item:",
    "menu_crypto": "🪙 <b>Crypto</b>\n\nSelect an item:",
    "menu_portfolio": "💼 <b>Portfolio</b>\n\nSelect an item:",
    "menu_ask_ai": "🤖 <b>Ask AI</b>\n\nType your question and I'll answer using your portfolio data.\n\nExamples:\n• What is a Sharpe ratio?\n• How is my portfolio doing?\n• Explain the current market regime",
    "menu_system": "⚙️ <b>System</b>\n\nSelect an item:",
    "back_main": "🤖 <b>AI Trading Agent</b>\n\nSelect a section:",
}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not authorized(update):
        await query.answer()
        return

    await query.answer()
    data = query.data

    # Special: Crypto callbacks when module is disabled
    if data.startswith("crypto_") or data == "menu_crypto":
        from agent.preferences import is_module_enabled
        if not is_module_enabled("crypto"):
            await query.edit_message_text(
                "🪙 <b>Crypto module is disabled.</b>\n\nEnable it in the setup wizard:\n<code>python setup_wizard.py</code>",
                parse_mode="HTML",
                reply_markup=main_menu_keyboard(),
            )
            return

    # Special: Run Pipeline
    if data == "system_run_pipeline":
        await query.edit_message_text(
            "▶️ <b>Running pipeline...</b>\n\nThis may take several minutes.",
            parse_mode="HTML",
            reply_markup=system_keyboard(),
        )
        try:
            main_py = Path(__file__).parent / "main.py"
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(main_py), "--once",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=600
                )
            except asyncio.TimeoutError:
                proc.kill()
                await query.edit_message_text(
                    "⏱️ <b>Pipeline timed out</b> (10 min limit).",
                    parse_mode="HTML",
                    reply_markup=system_keyboard(),
                )
                return

            if proc.returncode == 0:
                await query.edit_message_text(
                    "✅ <b>Pipeline completed successfully!</b>",
                    parse_mode="HTML",
                    reply_markup=system_keyboard(),
                )
            else:
                err = stderr.decode()[-500:] if stderr else "Unknown error"
                await query.edit_message_text(
                    f"❌ <b>Pipeline failed</b>\n\n<code>{err}</code>",
                    parse_mode="HTML",
                    reply_markup=system_keyboard(),
                )
        except Exception as e:
            await query.edit_message_text(
                f"❌ <b>Error launching pipeline:</b>\n\n<code>{e}</code>",
                parse_mode="HTML",
                reply_markup=system_keyboard(),
            )
        return

    # Standard callbacks
    if data in CALLBACK_MAP:
        formatter, kb_func = CALLBACK_MAP[data]
        if formatter:
            text = formatter()
        else:
            text = SUBMENU_TITLES.get(data, "Select an option:")
        await query.edit_message_text(
            text[:4096],
            parse_mode="HTML",
            reply_markup=kb_func(),
        )
    else:
        await query.edit_message_text(
            "❓ Unknown action.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )


# ── Text Message Handler (AI Q&A) ────────────────────────────────────────────


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages — send to Gemini for Q&A."""
    if not authorized(update):
        return

    question = update.message.text.strip()
    if not question:
        return

    # Send "thinking" message
    thinking_msg = await update.message.reply_text("🤔 Thinking...")

    qa_context = _build_qa_context()
    answer = _ask_gemini(question, qa_context)

    await thinking_msg.edit_text(
        f"🤖 <b>AI Answer</b>\n\n{answer}",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    if not CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("regime", cmd_regime))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Free-text messages → AI Q&A
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Webhook vs polling mode
    from agent.preferences import get_telegram_mode
    telegram_mode = os.getenv("TELEGRAM_MODE", get_telegram_mode())

    if telegram_mode == "webhook":
        port = int(os.getenv("PORT", "8080"))
        webhook_url = os.getenv("WEBHOOK_URL", "")
        logger.info("Bot started — webhook mode on port %d", port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{webhook_url}/{BOT_TOKEN}",
        )
    else:
        logger.info("Bot started — polling for updates")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
