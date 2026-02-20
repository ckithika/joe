"""Alerting system — Telegram and Discord notifications for trading signals."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """A single alert to be sent."""
    title: str
    message: str
    level: str = "info"      # "info", "warning", "critical"
    category: str = "signal"  # "signal", "position", "earnings", "system", "daily"
    ticker: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class TelegramNotifier:
    """Send alerts via Telegram Bot API.

    Setup:
    1. Message @BotFather on Telegram, send /newbot, follow prompts
    2. Copy the bot token (looks like: 123456:ABC-DEF1234)
    3. Start a chat with your bot, send any message
    4. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates
    5. Find your chat_id in the response
    6. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
    """

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def available(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, alert: Alert) -> bool:
        """Send a single alert via Telegram."""
        if not self.available:
            return False

        icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(alert.level, "📊")
        # Use HTML to avoid Telegram Markdown escaping issues
        text = f"{icon} <b>{alert.title}</b>\n\n{alert.message}"
        # Strip any residual Markdown bold/italic that would confuse HTML mode
        text = text.replace("*", "").replace("_", " ")

        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            return False


class DiscordNotifier:
    """Send alerts via Discord webhook.

    Setup:
    1. In your Discord server, go to channel Settings > Integrations > Webhooks
    2. Click "New Webhook", name it, copy the webhook URL
    3. Set DISCORD_WEBHOOK_URL in .env
    """

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")

    @property
    def available(self) -> bool:
        return bool(self.webhook_url)

    def send(self, alert: Alert) -> bool:
        """Send a single alert via Discord webhook."""
        if not self.available:
            return False

        color = {"info": 3447003, "warning": 16776960, "critical": 15158332}.get(alert.level, 3447003)

        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": color,
            "footer": {"text": f"{alert.category} | {alert.timestamp[:19]}"},
        }
        if alert.ticker:
            embed["fields"] = [{"name": "Ticker", "value": alert.ticker, "inline": True}]

        try:
            resp = requests.post(
                self.webhook_url,
                json={"embeds": [embed]},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Discord send failed: %s", e)
            return False


class AlertManager:
    """Manages sending alerts across all configured channels.

    Usage:
        manager = AlertManager()

        # Send a signal alert
        manager.send_signal_alert("AAPL", "LONG", "trend_following", 0.85)

        # Send daily summary
        manager.send_daily_summary(regime="trending_up", balance=523.50, signals=5)
    """

    def __init__(self):
        self.telegram = TelegramNotifier()
        self.discord = DiscordNotifier()
        self._sent_today: list[dict] = []

    @property
    def available(self) -> bool:
        return self.telegram.available or self.discord.available

    def _send(self, alert: Alert) -> bool:
        """Send alert to all available channels."""
        sent = False
        if self.telegram.available:
            sent = self.telegram.send(alert) or sent
        if self.discord.available:
            sent = self.discord.send(alert) or sent

        if sent:
            self._sent_today.append({
                "title": alert.title,
                "level": alert.level,
                "timestamp": alert.timestamp,
            })

        return sent

    def send_signal_alert(
        self,
        ticker: str,
        direction: str,
        strategy: str,
        confidence: float,
        entry_price: float = 0,
        stop_loss: float = 0,
        take_profit: float = 0,
    ) -> bool:
        """Send alert for a new trading signal."""
        msg = (
            f"{direction} {ticker}\n"
            f"Strategy: {strategy.replace('_', ' ').title()}\n"
            f"Confidence: {confidence:.0%}"
        )
        if entry_price > 0:
            msg += (
                f"\nEntry: ${entry_price:.2f}"
                f"\nSL: ${stop_loss:.2f} | TP: ${take_profit:.2f}"
            )

        return self._send(Alert(
            title=f"Signal: {ticker} {direction}",
            message=msg,
            level="info",
            category="signal",
            ticker=ticker,
        ))

    def send_position_alert(
        self,
        ticker: str,
        event: str,  # "opened", "closed", "stopped_out", "target_hit", "trailing_stopped"
        pnl: float = 0,
        direction: str = "",
        reason: str = "",
    ) -> bool:
        """Send alert for position events."""
        level = "info" if pnl >= 0 else "warning"

        if event == "opened":
            msg = f"Opened {direction} position in {ticker}"
        elif event in ("stopped_out", "trailing_stopped"):
            msg = f"{ticker} {event.replace('_', ' ')} — P&L: ${pnl:+.2f}"
            level = "warning"
        elif event == "target_hit":
            msg = f"{ticker} target hit — P&L: ${pnl:+.2f}"
        else:
            msg = f"{ticker} closed ({reason}) — P&L: ${pnl:+.2f}"

        return self._send(Alert(
            title=f"Position: {ticker} {event.replace('_', ' ').title()}",
            message=msg,
            level=level,
            category="position",
            ticker=ticker,
        ))

    def send_earnings_warning(self, ticker: str, days_until: int) -> bool:
        """Send warning about upcoming earnings for an open position."""
        return self._send(Alert(
            title=f"Earnings Warning: {ticker}",
            message=f"{ticker} reports earnings in {days_until} day{'s' if days_until != 1 else ''}. "
                    f"Consider closing or reducing position before the report.",
            level="warning",
            category="earnings",
            ticker=ticker,
        ))

    def send_daily_summary(
        self,
        regime: str,
        confidence: float,
        balance: float,
        open_positions: int,
        signals_count: int,
        win_rate: float = 0,
        ai_summary: str = "",
    ) -> bool:
        """Send daily pipeline summary."""
        msg = (
            f"Regime: {regime.replace('_', ' ').title()} ({confidence:.0%})\n"
            f"Balance: ${balance:.2f}\n"
            f"Open Positions: {open_positions}/3\n"
            f"Signals Today: {signals_count}\n"
            f"Win Rate: {win_rate:.0%}"
        )
        if ai_summary:
            # Truncate for Telegram's message limit
            summary = ai_summary[:500]
            msg += f"\n\nAI Summary:\n{summary}"

        return self._send(Alert(
            title="Daily Briefing",
            message=msg,
            level="info",
            category="daily",
        ))

    def send_risk_alert(
        self,
        risk_level: str,
        composite_score: float,
        alerts: list[str],
    ) -> bool:
        """Send alert when risk level is elevated."""
        if risk_level.lower() in ("low", "moderate"):
            return False  # Don't spam on normal risk levels

        msg = f"Risk Score: {composite_score:.1f}/10 — {risk_level.upper()}\n"
        if alerts:
            msg += "\n".join(f"- {a}" for a in alerts[:5])

        return self._send(Alert(
            title=f"Risk Alert: {risk_level.upper()}",
            message=msg,
            level="critical" if risk_level.lower() == "extreme" else "warning",
            category="system",
        ))

    def send_crypto_alert(
        self,
        signal_type: str,
        symbol: str,
        direction: str,
        details: str,
    ) -> bool:
        """Send crypto overnight signal alert."""
        return self._send(Alert(
            title=f"Crypto: {symbol} {signal_type.replace('_', ' ').title()}",
            message=f"{direction} signal — {details}",
            level="info",
            category="signal",
            ticker=symbol,
        ))

    def send_system_alert(self, title: str, message: str, level: str = "warning") -> bool:
        """Send a system-level alert (errors, circuit breaker trips, etc.)."""
        return self._send(Alert(
            title=title,
            message=message,
            level=level,
            category="system",
        ))

    def get_sent_today(self) -> list[dict]:
        return self._sent_today
