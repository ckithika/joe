"""Resilience layer — circuit breaker, retry with backoff, and API health tracking."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal — requests go through
    OPEN = "open"          # Tripped — requests blocked
    HALF_OPEN = "half_open"  # Testing — one request allowed


@dataclass
class APIHealth:
    """Health stats for a single API endpoint."""
    name: str
    total_calls: int = 0
    failures: int = 0
    last_failure: str = ""
    last_success: str = ""
    state: CircuitState = CircuitState.CLOSED
    opened_at: str = ""
    consecutive_failures: int = 0

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.failures / self.total_calls

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "total_calls": self.total_calls,
            "failures": self.failures,
            "failure_rate": round(self.failure_rate, 3),
            "last_failure": self.last_failure,
            "last_success": self.last_success,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
        }


class CircuitBreaker:
    """Circuit breaker pattern for API calls.

    States:
    - CLOSED: Normal operation. Requests go through. If failures exceed threshold, trips to OPEN.
    - OPEN: All requests are blocked immediately (fail fast). After recovery_timeout, moves to HALF_OPEN.
    - HALF_OPEN: Allows one test request. If it succeeds, go to CLOSED. If it fails, go to OPEN.

    Why this matters:
    - Prevents hammering a dead API (wastes time, may get IP banned)
    - Fails fast so the pipeline doesn't hang on timeouts
    - Automatically recovers when the API comes back
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: int = 300,  # seconds
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._apis: dict[str, APIHealth] = {}

    def get_health(self, api_name: str) -> APIHealth:
        if api_name not in self._apis:
            self._apis[api_name] = APIHealth(name=api_name)
        return self._apis[api_name]

    def can_call(self, api_name: str) -> bool:
        """Check if an API call is allowed."""
        health = self.get_health(api_name)

        if health.state == CircuitState.CLOSED:
            return True

        if health.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if health.opened_at:
                opened = datetime.fromisoformat(health.opened_at)
                if datetime.now() - opened > timedelta(seconds=self.recovery_timeout):
                    health.state = CircuitState.HALF_OPEN
                    logger.info("Circuit %s: OPEN -> HALF_OPEN (testing recovery)", api_name)
                    return True
            return False

        # HALF_OPEN: allow one test request
        return True

    def record_success(self, api_name: str):
        """Record a successful API call."""
        health = self.get_health(api_name)
        health.total_calls += 1
        health.consecutive_failures = 0
        health.last_success = datetime.now().isoformat()

        if health.state == CircuitState.HALF_OPEN:
            health.state = CircuitState.CLOSED
            logger.info("Circuit %s: HALF_OPEN -> CLOSED (recovered)", api_name)

    def record_failure(self, api_name: str, error: str = ""):
        """Record a failed API call."""
        health = self.get_health(api_name)
        health.total_calls += 1
        health.failures += 1
        health.consecutive_failures += 1
        health.last_failure = datetime.now().isoformat()

        if health.state == CircuitState.HALF_OPEN:
            # Test request failed — go back to OPEN
            health.state = CircuitState.OPEN
            health.opened_at = datetime.now().isoformat()
            logger.warning("Circuit %s: HALF_OPEN -> OPEN (test failed: %s)", api_name, error)

        elif health.consecutive_failures >= self.failure_threshold:
            health.state = CircuitState.OPEN
            health.opened_at = datetime.now().isoformat()
            logger.warning(
                "Circuit %s: CLOSED -> OPEN (%d consecutive failures)",
                api_name, health.consecutive_failures,
            )

    def get_all_health(self) -> list[dict]:
        """Return health status for all tracked APIs."""
        return [h.to_dict() for h in self._apis.values()]

    def get_summary(self) -> str:
        """Human-readable health summary."""
        lines = ["## API Health"]
        for h in self._apis.values():
            icon = {"closed": "OK", "open": "DOWN", "half_open": "TESTING"}[h.state.value]
            lines.append(
                f"- **{h.name}**: [{icon}] {h.total_calls} calls, "
                f"{h.failure_rate:.0%} failure rate"
            )
        return "\n".join(lines)


# Global circuit breaker instance
_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _breaker


def retry_with_backoff(
    api_name: str,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple = (Exception,),
):
    """Decorator: retry with exponential backoff and circuit breaker integration.

    Usage:
        @retry_with_backoff("coingecko", max_retries=3)
        def fetch_something():
            resp = requests.get(url)
            resp.raise_for_status()
            return resp.json()

    Behavior:
    - Check circuit breaker before calling
    - On success: record success, reset failure counter
    - On failure: retry with exponential backoff (1s, 2s, 4s, ...)
    - After max_retries failures: record failure in circuit breaker, return None
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker()

            if not breaker.can_call(api_name):
                logger.warning("Circuit OPEN for %s — skipping call to %s", api_name, func.__name__)
                return None

            last_error = None
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    breaker.record_success(api_name)
                    return result
                except exceptions as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            "%s attempt %d/%d failed: %s — retrying in %.1fs",
                            api_name, attempt + 1, max_retries, e, delay,
                        )
                        time.sleep(delay)

            # All retries exhausted
            breaker.record_failure(api_name, str(last_error))
            logger.error("%s: all %d retries failed: %s", api_name, max_retries, last_error)
            return None

        return wrapper
    return decorator


def resilient_request(
    api_name: str,
    request_func,
    max_retries: int = 3,
    base_delay: float = 1.0,
):
    """Functional wrapper for one-off resilient API calls.

    Usage:
        result = resilient_request(
            "binance",
            lambda: requests.get(url, timeout=10).json(),
        )
    """
    breaker = get_circuit_breaker()

    if not breaker.can_call(api_name):
        logger.warning("Circuit OPEN for %s — skipping", api_name)
        return None

    last_error = None
    for attempt in range(max_retries):
        try:
            result = request_func()
            breaker.record_success(api_name)
            return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), 30.0)
                logger.warning(
                    "%s attempt %d/%d failed: %s — retrying in %.1fs",
                    api_name, attempt + 1, max_retries, e, delay,
                )
                time.sleep(delay)

    breaker.record_failure(api_name, str(last_error))
    return None
