#!/usr/bin/env python3
"""Interactive Telegram bot for Joe AI."""

import asyncio
import csv
import json
import logging
import os
import re
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

# Ticker validation: 1-10 uppercase letters/digits, optional underscore
TICKER_PATTERN = re.compile(r"^[A-Z0-9_]{1,10}$")

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


GUIDE_PAGES = [
    (
        "1/6 — What is Joe AI?",
        "🤖 <b>What is Joe AI?</b>\n\n"
        "Joe AI is a <b>paper trading agent</b> that learns to trade alongside you.\n\n"
        "• Starts with <b>$500 virtual capital</b> — no real money at risk\n"
        "• Scans US stocks, indices, forex, crypto, and commodities\n"
        "• Uses AI analysis (Gemini) to grade every signal\n"
        "• Manages positions with stop-losses and take-profits\n"
        "• Sends you Telegram alerts for entries, exits, and daily briefings\n\n"
        "Think of it as a research assistant that also keeps a paper portfolio "
        "so you can see how its ideas actually perform.",
    ),
    (
        "2/6 — 2-Prong Setup",
        "🏗️ <b>2-Prong Setup</b>\n\n"
        "<b>Local (your laptop)</b>\n"
        "• Connects to IBKR TWS + Capital.com\n"
        "• Full scanner data from both brokers\n"
        "• Run manually: <code>python main.py --once</code>\n\n"
        "<b>Cloud (automated)</b>\n"
        "• Runs on Google Cloud Run (scheduled)\n"
        "• Capital.com only (no IBKR in cloud)\n"
        "• Pipeline runs daily; monitor checks positions every 5 min\n"
        "• Telegram bot runs 24/7 for on-demand queries\n\n"
        "Best results: run locally when you can, let the cloud handle "
        "the rest automatically.",
    ),
    (
        "3/6 — Reading Signals",
        "📊 <b>Reading Signals</b>\n\n"
        "<b>Signal Grades:</b>\n"
        "• 🟢 <b>STRONG_BUY</b> — High-conviction setup (score ≥ 0.45)\n"
        "• 🟡 <b>BUY</b> — Decent setup (score ≥ 0.35)\n"
        "• ⚪ <b>NEUTRAL</b> — No clear edge\n"
        "• 🔴 <b>SELL / STRONG_SELL</b> — Bearish signals\n\n"
        "<b>Key Numbers:</b>\n"
        "• <b>SL</b> (Stop Loss) — auto-exit if price drops here\n"
        "• <b>TP</b> (Take Profit) — auto-exit at target\n"
        "• <b>ATR</b> — Average True Range; measures volatility\n"
        "• <b>P&L</b> — Profit and Loss on the position\n"
        "• <b>R:R</b> — Risk-to-Reward ratio (higher = better)\n\n"
        "Joe sizes positions so no single trade risks more than 5% of capital.",
    ),
    (
        "4/6 — Running Locally",
        "💻 <b>Running Locally</b>\n\n"
        "<b>Daily pipeline:</b>\n"
        "<code>./venv/bin/python3 main.py --once</code>\n"
        "Scans markets, scores, opens/closes positions, sends briefing.\n\n"
        "<b>Dry run (no trades):</b>\n"
        "<code>./venv/bin/python3 main.py --once --dry-run</code>\n\n"
        "<b>Intraday monitor:</b>\n"
        "<code>./venv/bin/python3 monitor.py</code>\n"
        "Loops every 5 min during market hours checking SL/TP exits.\n\n"
        "<b>Push data to GitHub:</b>\n"
        "<code>./venv/bin/python3 main.py --once --push</code>\n\n"
        "<b>Dashboard:</b>\n"
        "Open <code>dashboard/index.html</code> in your browser for charts.",
    ),
    (
        "5/6 — Bot Commands",
        "📱 <b>Bot Commands</b>\n\n"
        "/start — Main menu\n"
        "/menu — Main menu\n"
        "/briefing — Regime + AI summary\n"
        "/positions — Open positions\n"
        "/regime — Market regime details\n"
        "/guide — This walkthrough\n"
        "/help — Command list\n\n"
        "<b>Main menu sections:</b>\n"
        "📊 Daily Briefing — regime, AI summary, risk, after-hours\n"
        "📈 Stocks — signals, earnings, breadth, sectors, insiders\n"
        "🪙 Crypto — fear/greed, BTC/ETH, DeFi, whales\n"
        "💼 Portfolio — positions, performance, analytics, history\n"
        "🤖 Ask AI — type any question\n"
        "⚙️ System — API health, run pipeline",
    ),
    (
        "6/6 — Key Concepts",
        "📚 <b>Key Concepts</b>\n\n"
        "<b>Regime</b> — Market state (Trending Up/Down, Range-Bound, "
        "High Volatility). Determines which strategies are active.\n\n"
        "<b>Defensive Mode</b> — Triggered by high VIX, drawdown past "
        "-10%, or bad regime. Blocks new entries, tightens stops.\n\n"
        "<b>R:R (Risk-to-Reward)</b> — Distance to TP vs distance to SL. "
        "Joe targets at least 1.5:1.\n\n"
        "<b>ATR</b> — Average True Range. Measures how much a stock moves "
        "daily. Used to set SL/TP distances.\n\n"
        "<b>VIX</b> — CBOE Volatility Index. Above 28 = elevated fear.\n\n"
        "<b>Drawdown</b> — Peak-to-trough decline in portfolio value. "
        "Joe enters defensive mode at -10%.",
    ),
]


def guide_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    """Navigation keyboard for guide pages."""
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"guide_page_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"guide_page_{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("« Back to Menu", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)


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


# ── Bot State (pause / blacklist) ─────────────────────────────────────────────

BOT_STATE_FILE = PAPER_DIR / "bot_state.json"


def _load_bot_state() -> dict:
    """Load bot state from disk."""
    if BOT_STATE_FILE.exists():
        try:
            return json.loads(BOT_STATE_FILE.read_text())
        except Exception:
            pass
    return {"paused": False, "blacklist": [], "paused_at": None}


def _save_bot_state(state: dict) -> None:
    """Save bot state to disk."""
    BOT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOT_STATE_FILE.write_text(json.dumps(state, indent=2))


def is_trading_paused() -> bool:
    """Check if trading is paused (used by main.py / paper_trader)."""
    return _load_bot_state().get("paused", False)


def get_blacklist() -> list[str]:
    """Get the current ticker blacklist (used by main.py)."""
    return _load_bot_state().get("blacklist", [])


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
        "LOW": "🟢",
        "MODERATE": "🟡",
        "ELEVATED": "🟠",
        "HIGH": "🔴",
        "EXTREME": "🔴",
    }
    emoji = emoji_map.get(level.upper(), "⚪")
    text = "⚠️ <b>Risk Assessment</b>\n\n"
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
    text = "🌙 <b>After-Hours Intel</b>\n\n"
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
        text += f"{direction} <b>{ticker_display(name)}</b>\n" f"  1D: {d1:+.2f}% | 1W: {w1:+.2f}% | 1M: {m1:+.2f}%\n\n"
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
                text += (
                    "  Longs: "
                    + ", ".join(f"${z:,.0f}" if isinstance(z, (int, float)) else str(z) for z in longs[:3])
                    + "\n"
                )
            if shorts:
                text += (
                    "  Shorts: "
                    + ", ".join(f"${z:,.0f}" if isinstance(z, (int, float)) else str(z) for z in shorts[:3])
                    + "\n"
                )
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
            f"{p.get('ticker')} {p.get('direction')} (PnL ${p.get('unrealized_pnl', 0):+.2f})" for p in positions
        )
        parts.append(f"Open positions: {pos_text}")
    signals = load_signals(crypto=False)[:3]
    if signals:
        sig_text = ", ".join(f"{s.get('ticker')} {s.get('signal')} ({s.get('strategy')})" for s in signals)
        parts.append(f"Top signals: {sig_text}")
    analytics = load_analytics()
    if analytics:
        parts.append(
            f"Sharpe: {analytics.get('sharpe_ratio', 0):.2f}, " f"Max DD: {analytics.get('max_drawdown_pct', 0):.1f}%"
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
    buttons.extend(
        [
            [InlineKeyboardButton("💼 Portfolio", callback_data="menu_portfolio")],
            [InlineKeyboardButton("🤖 Ask AI", callback_data="menu_ask_ai")],
            [InlineKeyboardButton("📖 Guide", callback_data="menu_guide")],
            [InlineKeyboardButton("⚙️ System", callback_data="menu_system")],
        ]
    )
    return InlineKeyboardMarkup(buttons)


def briefing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🌡️ Market Regime", callback_data="briefing_regime")],
            [InlineKeyboardButton("🤖 AI Summary", callback_data="briefing_ai")],
            [InlineKeyboardButton("⚠️ Risk Assessment", callback_data="briefing_risk")],
            [InlineKeyboardButton("🌙 After-Hours Intel", callback_data="briefing_after_hours")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


def stocks_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📊 Today's Signals", callback_data="stocks_signals")],
            [InlineKeyboardButton("📅 Earnings Calendar", callback_data="stocks_earnings")],
            [InlineKeyboardButton("📈 Market Breadth", callback_data="stocks_breadth")],
            [InlineKeyboardButton("🏭 Sector Performance", callback_data="stocks_sectors")],
            [InlineKeyboardButton("🕵️ Insider Activity", callback_data="stocks_insider")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


def crypto_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("😱 Fear & Greed Index", callback_data="crypto_fear_greed")],
            [InlineKeyboardButton("₿ BTC/ETH Overview", callback_data="crypto_btc_eth")],
            [InlineKeyboardButton("🏦 DeFi & Gas", callback_data="crypto_defi")],
            [InlineKeyboardButton("🐋 Whale Activity", callback_data="crypto_whale")],
            [InlineKeyboardButton("🌙 Overnight Signals", callback_data="crypto_signals")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


def portfolio_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📂 Open Positions", callback_data="portfolio_positions")],
            [InlineKeyboardButton("💰 Performance Summary", callback_data="portfolio_performance")],
            [InlineKeyboardButton("📐 Analytics", callback_data="portfolio_analytics")],
            [InlineKeyboardButton("📜 Trade History", callback_data="portfolio_history")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


def system_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔧 API Health", callback_data="system_health")],
            [InlineKeyboardButton("▶️ Run Pipeline", callback_data="system_run_pipeline")],
            [InlineKeyboardButton("« Back", callback_data="back_main")],
        ]
    )


# ── Auth ─────────────────────────────────────────────────────────────────────


def authorized(update: Update) -> bool:
    """Only respond to the configured chat ID."""
    return str(update.effective_chat.id) == CHAT_ID


# ── Command Handlers ─────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "🤖 <b>Joe AI</b>\n\nSelect a section:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await update.message.reply_text(
        "🤖 <b>Joe AI — Help</b>\n\n"
        "<b>Commands:</b>\n"
        "/start — Main menu\n"
        "/menu — Main menu\n"
        "/briefing — Quick briefing (regime + AI summary)\n"
        "/status — Portfolio overview (balance, P&amp;L, regime, risk)\n"
        "/positions — Open positions with details\n"
        "/performance — Win rate, Sharpe, best/worst trade\n"
        "/journal — Last 5 trades with setup, times, P&amp;L\n"
        "/regime — Market regime\n\n"
        "<b>Controls:</b>\n"
        "/pause — Pause new trades (keeps monitoring SL/TP)\n"
        "/resume — Resume trading\n"
        "/blacklist TICKER — Block a ticker from scanning\n"
        "/whitelist TICKER — Unblock a ticker\n\n"
        "/guide — Interactive walkthrough\n"
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


async def cmd_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    title, body = GUIDE_PAGES[0]
    await update.message.reply_text(
        body,
        parse_mode="HTML",
        reply_markup=guide_keyboard(0, len(GUIDE_PAGES)),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current portfolio status overview."""
    if not authorized(update):
        return
    perf = load_performance()
    positions = load_open_positions()
    regime_data = load_regime()
    risk = load_risk()
    bot_state = _load_bot_state()

    if not perf:
        await update.message.reply_text("No performance data available yet.")
        return

    balance = perf.get("virtual_balance", 0)
    starting = perf.get("starting_balance", 500)
    total_return = ((balance - starting) / starting * 100) if starting else 0

    # Today's P&L: sum unrealized from open positions
    today_pnl = sum(p.get("unrealized_pnl", 0) for p in positions)

    regime_str = "Unknown"
    if regime_data:
        regime_str = regime_data.get("regime", "unknown").replace("_", " ").title()

    risk_str = "Unknown"
    if risk:
        risk_str = str(risk.get("risk_level", "unknown")).replace("RiskLevel.", "").title()

    paused = bot_state.get("paused", False)
    blacklist = bot_state.get("blacklist", [])

    text = (
        f"📊 <b>Portfolio Status</b>\n\n"
        f"<b>Balance:</b> ${balance:,.2f} ({total_return:+.1f}%)\n"
        f"<b>Open Positions:</b> {len(positions)}\n"
        f"<b>Today's P&amp;L:</b> ${today_pnl:+,.2f}\n"
        f"<b>Win Rate:</b> {perf.get('win_rate', 0):.0%}\n"
        f"<b>Total Trades:</b> {perf.get('total_trades', 0)}\n\n"
        f"<b>Regime:</b> {regime_str}\n"
        f"<b>Risk Grade:</b> {risk_str}\n\n"
        f"<b>Trading:</b> {'⏸️ PAUSED' if paused else '▶️ Active'}\n"
    )
    if blacklist:
        text += f"<b>Blacklist:</b> {', '.join(blacklist)}\n"

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_keyboard())


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pause trading — skip new entries but keep monitoring existing positions."""
    if not authorized(update):
        return
    state = _load_bot_state()
    if state.get("paused"):
        await update.message.reply_text(
            "⏸️ Trading is already paused.\n\nUse /resume to resume.",
            parse_mode="HTML",
        )
        return
    state["paused"] = True
    state["paused_at"] = datetime.now().isoformat()
    _save_bot_state(state)
    await update.message.reply_text(
        "⏸️ <b>Trading Paused</b>\n\n"
        "New entries are blocked. Existing positions will still be monitored for SL/TP exits.\n\n"
        "Use /resume to resume trading.",
        parse_mode="HTML",
    )


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resume trading after a pause."""
    if not authorized(update):
        return
    state = _load_bot_state()
    if not state.get("paused"):
        await update.message.reply_text(
            "▶️ Trading is already active.\n\nUse /pause to pause.",
            parse_mode="HTML",
        )
        return
    paused_at = state.get("paused_at", "")
    state["paused"] = False
    state["paused_at"] = None
    _save_bot_state(state)

    duration = ""
    if paused_at:
        try:
            dt = datetime.fromisoformat(paused_at)
            elapsed = datetime.now() - dt
            hours = int(elapsed.total_seconds() // 3600)
            mins = int((elapsed.total_seconds() % 3600) // 60)
            duration = f"\n\nWas paused for {hours}h {mins}m."
        except Exception:
            pass

    await update.message.reply_text(
        f"▶️ <b>Trading Resumed</b>\n\nNew entries are now allowed.{duration}",
        parse_mode="HTML",
    )


async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a ticker to the temporary blacklist."""
    if not authorized(update):
        return
    if not context.args:
        state = _load_bot_state()
        bl = state.get("blacklist", [])
        if bl:
            await update.message.reply_text(
                f"🚫 <b>Current Blacklist</b>\n\n{', '.join(bl)}\n\n" "Usage: /blacklist TICKER",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "🚫 <b>Blacklist is empty.</b>\n\nUsage: /blacklist TICKER",
                parse_mode="HTML",
            )
        return

    ticker = context.args[0].upper()
    if not TICKER_PATTERN.match(ticker):
        await update.message.reply_text(
            "Invalid ticker format. Use 1-10 uppercase letters/digits.",
            parse_mode="HTML",
        )
        return
    state = _load_bot_state()
    blacklist = state.get("blacklist", [])
    if ticker in blacklist:
        await update.message.reply_text(
            f"🚫 {ticker} is already blacklisted.",
            parse_mode="HTML",
        )
        return
    blacklist.append(ticker)
    state["blacklist"] = blacklist
    _save_bot_state(state)
    await update.message.reply_text(
        f"🚫 <b>{ticker} blacklisted.</b>\n\n" f"It will be skipped in scanning. Use /whitelist {ticker} to remove.",
        parse_mode="HTML",
    )


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a ticker from the blacklist."""
    if not authorized(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /whitelist TICKER\n\nRemoves a ticker from the blacklist.",
            parse_mode="HTML",
        )
        return

    ticker = context.args[0].upper()
    if not TICKER_PATTERN.match(ticker):
        await update.message.reply_text(
            "Invalid ticker format. Use 1-10 uppercase letters/digits.",
            parse_mode="HTML",
        )
        return
    state = _load_bot_state()
    blacklist = state.get("blacklist", [])
    if ticker not in blacklist:
        await update.message.reply_text(
            f"✅ {ticker} is not on the blacklist.",
            parse_mode="HTML",
        )
        return
    blacklist.remove(ticker)
    state["blacklist"] = blacklist
    _save_bot_state(state)
    await update.message.reply_text(
        f"✅ <b>{ticker} removed from blacklist.</b>",
        parse_mode="HTML",
    )


async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed performance: win rate, best/worst, Sharpe, etc."""
    if not authorized(update):
        return
    perf = load_performance()
    analytics = load_analytics()
    trades = load_trade_history(100)  # Load more for best/worst

    if not perf:
        await update.message.reply_text("No performance data available yet.")
        return

    balance = perf.get("virtual_balance", 0)
    starting = perf.get("starting_balance", 500)
    total_return = ((balance - starting) / starting * 100) if starting else 0
    total_trades = perf.get("total_trades", 0)
    wins = perf.get("wins", 0)
    losses = perf.get("losses", 0)
    win_rate = perf.get("win_rate", 0)
    pf = perf.get("profit_factor", 0)
    expectancy = perf.get("expectancy", 0)
    sharpe = perf.get("sharpe_ratio", 0)
    max_dd = perf.get("max_drawdown_pct", 0)
    avg_r = perf.get("avg_r_multiple", 0)

    # Use portfolio analytics for better metrics if available
    if analytics:
        sharpe = analytics.get("sharpe_ratio", sharpe)
        max_dd = analytics.get("max_drawdown_pct", max_dd)

    # Find best and worst trade
    best_trade = None
    worst_trade = None
    if trades:
        pnl_trades = []
        for t in trades:
            try:
                pnl_trades.append((float(t.get("pnl", 0)), t))
            except (ValueError, TypeError):
                pass
        if pnl_trades:
            pnl_trades.sort(key=lambda x: x[0])
            worst_pnl, worst_trade = pnl_trades[0]
            best_pnl, best_trade = pnl_trades[-1]

    text = (
        f"📈 <b>Performance Report</b>\n\n"
        f"<b>Balance:</b> ${balance:,.2f} ({total_return:+.1f}%)\n"
        f"<b>Starting:</b> ${starting:,.2f}\n\n"
        f"<b>Trades:</b> {total_trades} (W: {wins} / L: {losses})\n"
        f"<b>Win Rate:</b> {win_rate:.0%}\n"
        f"<b>Profit Factor:</b> {pf:.2f}\n"
        f"<b>Expectancy:</b> ${expectancy:,.2f}\n"
        f"<b>Avg R-Multiple:</b> {avg_r:.2f}\n\n"
        f"<b>Sharpe Ratio:</b> {sharpe:.2f}\n"
        f"<b>Max Drawdown:</b> {max_dd:.1f}%\n"
    )

    if best_trade:
        text += f"\n<b>Best Trade:</b> {best_trade.get('ticker', '?')} " f"${float(best_trade.get('pnl', 0)):+,.2f}\n"
    if worst_trade:
        text += f"<b>Worst Trade:</b> {worst_trade.get('ticker', '?')} " f"${float(worst_trade.get('pnl', 0)):+,.2f}\n"

    # Strategy breakdown
    strat_metrics = perf.get("strategy_metrics", {})
    if strat_metrics:
        text += "\n<b>By Strategy:</b>\n"
        for strat, m in strat_metrics.items():
            s_trades = m.get("total_trades", 0)
            s_wr = m.get("win_rate", 0)
            s_pnl = m.get("pnl", 0)
            text += f"  {strat}: {s_trades} trades, {s_wr:.0%} WR, ${s_pnl:+,.2f}\n"

    await update.message.reply_text(text[:4096], parse_mode="HTML", reply_markup=portfolio_keyboard())


async def cmd_journal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show last 5 trades with day-trading details: setup, times, duration, P&L, exit type."""
    if not authorized(update):
        return
    trades = load_trade_history(5)
    if not trades:
        await update.message.reply_text("No trades recorded yet.")
        return

    lines = ["📓 <b>Trade Journal — Last 5</b>\n"]
    for t in reversed(trades):  # Most recent first
        ticker = t.get("ticker", "?")
        direction = t.get("direction", "?")
        pnl = float(t.get("pnl", 0))
        pnl_str = f"${pnl:+,.2f}"
        icon = "✅" if pnl > 0 else ("❌" if pnl < 0 else "➖")

        setup = t.get("setup_type") or t.get("strategy", "—")
        exit_type = t.get("exit_type") or t.get("exit_reason", "—")

        # Entry/exit times (show time portion only if available)
        entry_time = t.get("entry_time", "")
        exit_time = t.get("exit_time", "")
        entry_display = ""
        exit_display = ""
        if entry_time:
            try:
                et = datetime.fromisoformat(entry_time)
                entry_display = et.strftime("%H:%M")
            except (ValueError, TypeError):
                entry_display = entry_time[:5] if len(entry_time) >= 5 else entry_time
        if exit_time:
            try:
                xt = datetime.fromisoformat(exit_time)
                exit_display = xt.strftime("%H:%M")
            except (ValueError, TypeError):
                exit_display = exit_time[:5] if len(exit_time) >= 5 else exit_time

        duration_str = ""
        mins = t.get("time_held_minutes", "")
        if mins:
            try:
                m = float(mins)
                if m >= 60:
                    duration_str = f"{m / 60:.1f}h"
                else:
                    duration_str = f"{m:.0f}m"
            except (ValueError, TypeError):
                pass

        time_str = ""
        if entry_display and exit_display:
            time_str = f"{entry_display} → {exit_display}"
        elif entry_display:
            time_str = f"in {entry_display}"

        entry_date = t.get("entry_date", "")

        lines.append(f"{icon} <b>{ticker}</b> {direction} | {pnl_str}")
        lines.append(f"   Setup: {setup} | Exit: {exit_type}")
        detail_parts = [entry_date]
        if time_str:
            detail_parts.append(time_str)
        if duration_str:
            detail_parts.append(duration_str)
        lines.append(f"   {' | '.join(detail_parts)}")
        lines.append("")

    await update.message.reply_text("\n".join(lines)[:4096], parse_mode="HTML", reply_markup=portfolio_keyboard())


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
    "back_main": "🤖 <b>Joe AI</b>\n\nSelect a section:",
}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not authorized(update):
        await query.answer()
        return

    await query.answer()
    data = query.data

    # Guide page navigation
    if data.startswith("guide_page_"):
        page = int(data.split("_")[-1])
        if 0 <= page < len(GUIDE_PAGES):
            title, body = GUIDE_PAGES[page]
            await query.edit_message_text(
                body,
                parse_mode="HTML",
                reply_markup=guide_keyboard(page, len(GUIDE_PAGES)),
            )
        return

    if data == "noop":
        return

    # Guide from main menu
    if data == "menu_guide":
        title, body = GUIDE_PAGES[0]
        await query.edit_message_text(
            body,
            parse_mode="HTML",
            reply_markup=guide_keyboard(0, len(GUIDE_PAGES)),
        )
        return

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
                sys.executable,
                str(main_py),
                "--once",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
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
    app.add_handler(CommandHandler("guide", cmd_guide))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("blacklist", cmd_blacklist))
    app.add_handler(CommandHandler("whitelist", cmd_whitelist))
    app.add_handler(CommandHandler("performance", cmd_performance))
    app.add_handler(CommandHandler("journal", cmd_journal))

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

        if not webhook_url:
            # First deploy: WEBHOOK_URL not yet known. Start a minimal HTTP
            # server so Cloud Run health checks pass and the service URL is
            # assigned. The deploy script then updates WEBHOOK_URL and the
            # next revision starts the real bot.
            from http.server import BaseHTTPRequestHandler, HTTPServer

            logger.warning("WEBHOOK_URL not set — health-check server only on port %d", port)

            class _Health(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")

                def log_message(self, *a):
                    pass

            HTTPServer(("0.0.0.0", port), _Health).serve_forever()
        else:
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
