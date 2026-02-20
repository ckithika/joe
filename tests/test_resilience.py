"""Tests for agent.resilience module."""

from unittest.mock import patch

import pytest

from agent.resilience import (
    CircuitBreaker,
    CircuitState,
    APIHealth,
    resilient_request,
    retry_with_backoff,
)


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        health = cb.get_health("test_api")
        assert health.state == CircuitState.CLOSED

    def test_can_call_when_closed(self):
        cb = CircuitBreaker()
        assert cb.can_call("test_api") is True

    def test_success_records_correctly(self):
        cb = CircuitBreaker()
        cb.record_success("test_api")
        health = cb.get_health("test_api")
        assert health.total_calls == 1
        assert health.failures == 0
        assert health.last_success != ""

    def test_failure_records_correctly(self):
        cb = CircuitBreaker()
        cb.record_failure("test_api", "timeout")
        health = cb.get_health("test_api")
        assert health.total_calls == 1
        assert health.failures == 1
        assert health.consecutive_failures == 1

    def test_trips_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure("test_api", "timeout")

        health = cb.get_health("test_api")
        assert health.state == CircuitState.OPEN
        assert cb.can_call("test_api") is False

    def test_success_resets_consecutive_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("api", "err")
        cb.record_failure("api", "err")
        cb.record_success("api")  # reset
        cb.record_failure("api", "err")

        health = cb.get_health("api")
        assert health.consecutive_failures == 1
        assert health.state == CircuitState.CLOSED

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)

        # Trip the circuit
        cb.record_failure("api", "err")
        cb.record_failure("api", "err")
        assert cb.get_health("api").state == CircuitState.OPEN

        # Recovery timeout is 0, so should go to HALF_OPEN immediately
        assert cb.can_call("api") is True
        assert cb.get_health("api").state == CircuitState.HALF_OPEN

        # Successful test request closes the circuit
        cb.record_success("api")
        assert cb.get_health("api").state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0)

        cb.record_failure("api", "err")
        cb.record_failure("api", "err")

        # Move to HALF_OPEN
        cb.can_call("api")

        # Failed test request
        cb.record_failure("api", "still broken")
        assert cb.get_health("api").state == CircuitState.OPEN

    def test_get_all_health(self):
        cb = CircuitBreaker()
        cb.record_success("api_a")
        cb.record_failure("api_b", "err")

        health_list = cb.get_all_health()
        assert len(health_list) == 2
        names = {h["name"] for h in health_list}
        assert "api_a" in names
        assert "api_b" in names

    def test_get_summary(self):
        cb = CircuitBreaker()
        cb.record_success("binance")
        cb.record_failure("coingecko", "timeout")

        summary = cb.get_summary()
        assert "binance" in summary
        assert "coingecko" in summary


class TestAPIHealth:
    def test_failure_rate_zero_calls(self):
        health = APIHealth(name="test")
        assert health.failure_rate == 0.0

    def test_failure_rate_calculation(self):
        health = APIHealth(name="test", total_calls=10, failures=3)
        assert health.failure_rate == 0.3

    def test_to_dict(self):
        health = APIHealth(name="test", total_calls=5, failures=1)
        d = health.to_dict()
        assert d["name"] == "test"
        assert d["failure_rate"] == 0.2


class TestRetryWithBackoff:
    def test_succeeds_first_try(self):
        @retry_with_backoff("test_api", max_retries=3, base_delay=0.01)
        def good_func():
            return "success"

        assert good_func() == "success"

    @patch("agent.resilience.time.sleep")
    def test_retries_on_failure(self, mock_sleep):
        call_count = 0

        @retry_with_backoff("test_retry", max_retries=3, base_delay=0.01)
        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("temporarily down")
            return "recovered"

        result = flaky_func()
        assert result == "recovered"
        assert call_count == 3

    @patch("agent.resilience.time.sleep")
    def test_returns_none_after_all_retries_fail(self, mock_sleep):
        @retry_with_backoff("always_fail", max_retries=2, base_delay=0.01)
        def bad_func():
            raise ConnectionError("always down")

        assert bad_func() is None

    def test_skips_when_circuit_open(self):
        from agent.resilience import get_circuit_breaker
        breaker = get_circuit_breaker()

        # Force circuit open
        health = breaker.get_health("blocked_api")
        health.state = CircuitState.OPEN
        health.opened_at = "2099-01-01T00:00:00"  # far future = won't recover

        @retry_with_backoff("blocked_api", max_retries=3)
        def should_skip():
            return "should not reach"

        result = should_skip()
        assert result is None

        # Clean up
        health.state = CircuitState.CLOSED


class TestResilientRequest:
    def test_successful_request(self):
        result = resilient_request("test", lambda: {"data": 42})
        assert result == {"data": 42}

    @patch("agent.resilience.time.sleep")
    def test_returns_none_on_failure(self, mock_sleep):
        def failing():
            raise Exception("boom")

        result = resilient_request("fail_test", failing, max_retries=2, base_delay=0.01)
        assert result is None
