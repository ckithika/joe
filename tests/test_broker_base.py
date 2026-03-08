"""Tests for brokers.base module."""

import pytest

from brokers.base import BaseBroker
from brokers.capital_client import CapitalClient
from brokers.ibkr_client import IBKRClient


class TestBaseBroker:
    def test_cannot_instantiate(self):
        """BaseBroker is abstract and should not be instantiable."""
        with pytest.raises(TypeError):
            BaseBroker()

    def test_ibkr_is_base_broker(self):
        client = IBKRClient.__new__(IBKRClient)
        assert isinstance(client, BaseBroker)

    def test_capital_is_base_broker(self):
        client = CapitalClient.__new__(CapitalClient)
        assert isinstance(client, BaseBroker)
