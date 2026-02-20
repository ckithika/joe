"""AI Analyst — Gemini-powered intelligence layer for the trading agent."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SentimentAnalysis:
    ticker: str
    sentiment: str  # bullish, neutral, bearish
    confidence: float  # 0.0 to 1.0
    score: float  # -1.0 to 1.0
    reasoning: str
    key_factors: list[str] = field(default_factory=list)


@dataclass
class TradeAnalysis:
    ticker: str
    recommendation: str  # take, skip, reduce_size
    bull_case: str
    bear_case: str
    risk_factors: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class JournalInsight:
    patterns: list[str]
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    overall_assessment: str


class AIAnalyst:
    """Gemini-powered analysis for sentiment, trade reasoning, and journal review."""

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-pro"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not set")
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _call(self, prompt: str, json_output: bool = False) -> str:
        """Make a single Gemini API call."""
        try:
            client = self._get_client()
            config = {}
            if json_output:
                config["response_mime_type"] = "application/json"

            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config if config else None,
            )
            return response.text
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            return ""

    # ── Sentiment Analysis ────────────────────────────────────────

    def analyze_sentiment(self, ticker: str, headlines: list[str]) -> SentimentAnalysis | None:
        """Analyze news headlines for a ticker using Gemini."""
        if not self.available or not headlines:
            return None

        headlines_text = "\n".join(f"- {h}" for h in headlines[:20])

        prompt = f"""Analyze the financial sentiment for {ticker} based on these recent headlines:

{headlines_text}

Respond in JSON with exactly these fields:
{{
  "sentiment": "bullish" or "neutral" or "bearish",
  "confidence": 0.0 to 1.0,
  "score": -1.0 to 1.0 (negative=bearish, positive=bullish),
  "reasoning": "one sentence explanation",
  "key_factors": ["factor1", "factor2", "factor3"]
}}"""

        result = self._call(prompt, json_output=True)
        if not result:
            return None

        try:
            data = json.loads(result)
            return SentimentAnalysis(
                ticker=ticker,
                sentiment=data.get("sentiment", "neutral"),
                confidence=float(data.get("confidence", 0.5)),
                score=float(data.get("score", 0.0)),
                reasoning=data.get("reasoning", ""),
                key_factors=data.get("key_factors", []),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse sentiment for %s: %s", ticker, e)
            return None

    def batch_sentiment(self, tickers_headlines: dict[str, list[str]]) -> dict[str, SentimentAnalysis]:
        """Analyze sentiment for multiple tickers efficiently."""
        results = {}
        for ticker, headlines in tickers_headlines.items():
            analysis = self.analyze_sentiment(ticker, headlines)
            if analysis:
                results[ticker] = analysis
        return results

    # ── Pre-Trade Analysis (Devil's Advocate) ─────────────────────

    def analyze_trade(
        self, ticker: str, direction: str, strategy: str,
        entry_price: float, stop_loss: float, take_profit: float,
        setup_description: str, regime: str,
    ) -> TradeAnalysis | None:
        """Run devil's advocate analysis before entering a trade."""
        if not self.available:
            return None

        prompt = f"""You are a senior trading analyst reviewing a proposed trade.

PROPOSED TRADE:
- Ticker: {ticker}
- Direction: {direction}
- Strategy: {strategy}
- Entry: ${entry_price:.2f}
- Stop Loss: ${stop_loss:.2f}
- Take Profit: ${take_profit:.2f}
- Setup: {setup_description}
- Market Regime: {regime}

Provide a balanced analysis. Be honest about risks.

Respond in JSON:
{{
  "recommendation": "take" or "skip" or "reduce_size",
  "bull_case": "why this trade could work (2-3 sentences)",
  "bear_case": "why this trade could fail (2-3 sentences)",
  "risk_factors": ["specific risk 1", "specific risk 2", "specific risk 3"],
  "confidence": 0.0 to 1.0
}}"""

        result = self._call(prompt, json_output=True)
        if not result:
            return None

        try:
            data = json.loads(result)
            return TradeAnalysis(
                ticker=ticker,
                recommendation=data.get("recommendation", "skip"),
                bull_case=data.get("bull_case", ""),
                bear_case=data.get("bear_case", ""),
                risk_factors=data.get("risk_factors", []),
                confidence=float(data.get("confidence", 0.5)),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse trade analysis for %s: %s", ticker, e)
            return None

    # ── Daily Briefing Summary ────────────────────────────────────

    def generate_daily_summary(
        self, regime: str, confidence: float,
        signals: list[dict], positions: list[dict],
        performance: dict,
        crypto_intel: dict | None = None,
        stock_intel: dict | None = None,
    ) -> str | None:
        """Generate a natural language daily briefing summary."""
        if not self.available:
            return None

        signals_text = ""
        for s in signals[:5]:
            signals_text += f"- {s.get('ticker')}: {s.get('signal')} (score {s.get('score', 0):.2f}), strategy: {s.get('strategy', 'unknown')}\n"

        positions_text = ""
        for p in positions:
            positions_text += f"- {p.get('ticker')} {p.get('direction')} @ ${p.get('entry_price', 0):.2f}, P&L: ${p.get('unrealized_pnl', 0):.2f}, day {p.get('days_held', 0)}/{p.get('max_hold_days', 10)}\n"

        balance = performance.get("virtual_balance", 500)
        win_rate = performance.get("win_rate", 0)
        total_trades = performance.get("total_trades", 0)

        # Build crypto context if available
        crypto_section = ""
        if crypto_intel:
            fg = crypto_intel.get("fear_greed", {})
            dom = crypto_intel.get("dominance", {})
            btc_f = crypto_intel.get("btc_funding", {})
            crypto_section = f"""
CRYPTO INTELLIGENCE:
- Fear & Greed: {fg.get('value', 'N/A')}/100 ({fg.get('classification', 'N/A')})
- BTC Dominance: {dom.get('btc_dominance', 'N/A')}%
- BTC Funding Rate: {btc_f.get('rate', 'N/A')} ({btc_f.get('direction', 'N/A')})
"""

        # Build stock context if available
        stock_section = ""
        if stock_intel:
            earnings = stock_intel.get("upcoming_earnings", [])
            breadth = stock_intel.get("market_breadth", {})
            if earnings:
                ear_text = ", ".join(f"{e['ticker']} ({e['days_until']}d)" for e in earnings[:3])
                stock_section += f"\nUPCOMING EARNINGS: {ear_text}"
            if breadth:
                stock_section += f"\nBREADTH: A/D ratio {breadth.get('advance_decline_ratio', 'N/A')}, {breadth.get('pct_above_200sma', 'N/A')}% above 200 SMA"

        prompt = f"""You are a trading research assistant. Write a concise daily briefing (4-6 sentences).

MARKET REGIME: {regime} (confidence: {confidence:.0%})

TODAY'S TOP SIGNALS:
{signals_text or "No signals today"}

OPEN POSITIONS:
{positions_text or "No open positions"}

PORTFOLIO: ${balance:.2f} | Win rate: {win_rate:.0%} | Total trades: {total_trades}
{crypto_section}{stock_section}

Write a brief, actionable summary. Focus on: what the regime means today, which signals look strongest, any position management needed, and one key thing to watch. Include crypto sentiment context if available. Keep it practical and direct. Do not use emojis."""

        return self._call(prompt)

    # ── Journal / Trade History Analysis ──────────────────────────

    def analyze_journal(self, trades_csv_text: str) -> JournalInsight | None:
        """Analyze trade history to find patterns and behavioral insights."""
        if not self.available or not trades_csv_text:
            return None

        prompt = f"""Analyze this trading journal data and identify patterns.

TRADE HISTORY (CSV):
{trades_csv_text[:3000]}

Look for:
1. Winning vs losing patterns (time held, strategy, direction)
2. Common mistakes (holding losers too long, cutting winners short)
3. Strategy effectiveness (which strategies make money?)
4. Behavioral patterns (overtrading, revenge trading, etc.)

Respond in JSON:
{{
  "patterns": ["pattern 1", "pattern 2"],
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "suggestions": ["actionable suggestion 1", "actionable suggestion 2"],
  "overall_assessment": "2-3 sentence summary"
}}"""

        result = self._call(prompt, json_output=True)
        if not result:
            return None

        try:
            data = json.loads(result)
            return JournalInsight(
                patterns=data.get("patterns", []),
                strengths=data.get("strengths", []),
                weaknesses=data.get("weaknesses", []),
                suggestions=data.get("suggestions", []),
                overall_assessment=data.get("overall_assessment", ""),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse journal analysis: %s", e)
            return None

    # ── Crypto-Specific Analysis ──────────────────────────────────

    def analyze_crypto_market(
        self, btc_price: float, eth_price: float,
        btc_rsi: float, eth_rsi: float,
        btc_sentiment: float, eth_sentiment: float,
    ) -> str | None:
        """Crypto-specific market analysis with on-chain context."""
        if not self.available:
            return None

        prompt = f"""You are a crypto market analyst. Provide a brief analysis.

CURRENT DATA:
- BTC: ${btc_price:,.2f} (RSI: {btc_rsi:.1f}, sentiment: {btc_sentiment:.2f})
- ETH: ${eth_price:,.2f} (RSI: {eth_rsi:.1f}, sentiment: {eth_sentiment:.2f})

Analyze:
1. Overall crypto market direction (1 sentence)
2. BTC dominance outlook and what it means for alts (1 sentence)
3. Key levels to watch for BTC and ETH (1 sentence each)
4. Risk assessment for crypto positions right now (1 sentence)

Be concise and practical. No emojis."""

        return self._call(prompt)
