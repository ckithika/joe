"""Tests for agent.alerts module."""

from unittest.mock import MagicMock, patch

import pytest

from agent.alerts import (
    Alert,
    AlertManager,
    DiscordNotifier,
    TelegramNotifier,
)


class TestAlert:
    def test_defaults(self):
        alert = Alert(title="Test", message="msg")
        assert alert.level == "info"
        assert alert.category == "signal"
        assert alert.timestamp != ""

    def test_custom_fields(self):
        alert = Alert(title="Risk", message="high", level="critical", category="system", ticker="AAPL")
        assert alert.level == "critical"
        assert alert.ticker == "AAPL"


class TestTelegramNotifier:
    def test_not_available_without_config(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        assert notifier.available is False

    def test_available_with_config(self):
        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        assert notifier.available is True

    def test_send_fails_when_unavailable(self):
        notifier = TelegramNotifier(bot_token="", chat_id="")
        assert notifier.send(Alert(title="Test", message="msg")) is False

    @patch("agent.alerts.requests.post")
    def test_send_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        result = notifier.send(Alert(title="Signal", message="AAPL LONG"))
        assert result is True
        mock_post.assert_called_once()

    @patch("agent.alerts.requests.post")
    def test_send_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection error")
        notifier = TelegramNotifier(bot_token="123:ABC", chat_id="456")
        result = notifier.send(Alert(title="Test", message="msg"))
        assert result is False


class TestDiscordNotifier:
    def test_not_available_without_config(self):
        notifier = DiscordNotifier(webhook_url="")
        assert notifier.available is False

    def test_available_with_config(self):
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/123/abc")
        assert notifier.available is True

    @patch("agent.alerts.requests.post")
    def test_send_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        mock_post.return_value.raise_for_status = MagicMock()

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/123/abc")
        result = notifier.send(Alert(title="Signal", message="AAPL LONG", ticker="AAPL"))
        assert result is True

    @patch("agent.alerts.requests.post")
    def test_send_with_different_levels(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        mock_post.return_value.raise_for_status = MagicMock()

        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/123/abc")

        for level in ("info", "warning", "critical"):
            result = notifier.send(Alert(title="Test", message="msg", level=level))
            assert result is True


class TestAlertManager:
    def test_not_available_without_config(self):
        manager = AlertManager()
        # Both telegram and discord unconfigured by default
        assert manager.available is False

    def test_send_signal_alert(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_signal_alert(
            ticker="AAPL", direction="LONG", strategy="trend_following",
            confidence=0.85, entry_price=185.0, stop_loss=180.0, take_profit=195.0,
        )
        assert result is True
        manager.telegram.send.assert_called_once()

    def test_send_position_alert_closed(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_position_alert(
            ticker="AAPL", event="target_hit", pnl=12.50, direction="LONG",
        )
        assert result is True

    def test_send_position_alert_stopped(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_position_alert(
            ticker="MSFT", event="stopped_out", pnl=-5.00, direction="SHORT",
        )
        assert result is True

    def test_send_earnings_warning(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_earnings_warning("AAPL", 2)
        assert result is True

    def test_send_daily_summary(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_daily_summary(
            regime="trending_up", confidence=0.85, balance=523.50,
            open_positions=2, signals_count=5, win_rate=0.6,
            ai_summary="Market looks bullish.",
        )
        assert result is True

    def test_risk_alert_low_skips(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_risk_alert("low", 2.0, [])
        assert result is False  # Low risk doesn't trigger alert

    def test_risk_alert_high_sends(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_risk_alert("high", 8.0, ["Drawdown exceeding threshold"])
        assert result is True

    def test_sends_to_both_channels(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=True, send=MagicMock(return_value=True))

        manager.send_signal_alert("AAPL", "LONG", "trend", 0.8)
        manager.telegram.send.assert_called_once()
        manager.discord.send.assert_called_once()

    def test_tracks_sent_alerts(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        manager.send_signal_alert("AAPL", "LONG", "trend", 0.8)
        manager.send_signal_alert("MSFT", "SHORT", "reversion", 0.7)

        sent = manager.get_sent_today()
        assert len(sent) == 2

    def test_send_system_alert(self):
        manager = AlertManager()
        manager.telegram = MagicMock(available=True, send=MagicMock(return_value=True))
        manager.discord = MagicMock(available=False)

        result = manager.send_system_alert("API Down", "CoinGecko circuit breaker tripped")
        assert result is True
