import importlib
import pkgutil
from typing import TypeVar

from agent.strategies.base import BaseStrategy

T = TypeVar("T", bound=BaseStrategy)

_registry: dict[str, BaseStrategy] = {}


def register(cls: type[T]) -> type[T]:
    """Decorator to register a strategy class."""
    instance = cls()
    _registry[instance.name] = instance
    return cls


class StrategyRegistry:
    """Registry that discovers and provides access to strategy instances."""

    def __init__(self) -> None:
        self._strategies = _registry
        self._discover()

    def _discover(self) -> None:
        """Auto-discover strategy modules in this package."""
        import agent.strategies as pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(pkg.__path__):
            if modname not in ("base", "registry"):
                importlib.import_module(f"agent.strategies.{modname}")
        # Re-bind after discovery in case new strategies registered
        self._strategies = _registry

    def get(self, name: str) -> BaseStrategy | None:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def all(self) -> dict[str, BaseStrategy]:
        """Return all registered strategies."""
        return dict(self._strategies)
