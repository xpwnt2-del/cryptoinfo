"""Tests for database.py"""

import os
import tempfile

import pytest

from database import Database


@pytest.fixture
def db(tmp_path):
    """Provide a fresh in-memory-like Database for each test."""
    path = str(tmp_path / "test.db")
    return Database(db_path=path)


class TestAddTransaction:
    def test_returns_dict(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        assert isinstance(tx, dict)

    def test_id_assigned(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        assert tx["id"] is not None and tx["id"] > 0

    def test_total_calculated(self, db):
        tx = db.add_transaction("ETH", "sell", 3000.0, 2.0)
        assert abs(tx["total"] - 6000.0) < 0.001

    def test_symbol_uppercased(self, db):
        tx = db.add_transaction("btc", "buy", 50000.0, 0.01)
        assert tx["symbol"] == "BTC"

    def test_side_lowercased(self, db):
        tx = db.add_transaction("BTC", "BUY", 50000.0, 0.01)
        assert tx["side"] == "buy"

    def test_source_default_user(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        assert tx["source"] == "user"

    def test_source_bot(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01, source="bot")
        assert tx["source"] == "bot"

    def test_invalid_side_raises(self, db):
        with pytest.raises(ValueError):
            db.add_transaction("BTC", "hold", 50000.0, 0.01)

    def test_invalid_price_raises(self, db):
        with pytest.raises(ValueError):
            db.add_transaction("BTC", "buy", -1.0, 0.01)

    def test_invalid_amount_raises(self, db):
        with pytest.raises(ValueError):
            db.add_transaction("BTC", "buy", 50000.0, -0.01)

    def test_invalid_source_raises(self, db):
        with pytest.raises(ValueError):
            db.add_transaction("BTC", "buy", 50000.0, 0.01, source="admin")


class TestGetTransactions:
    def test_empty_on_fresh_db(self, db):
        txs = db.get_transactions()
        assert txs == []

    def test_returns_all(self, db):
        db.add_transaction("BTC", "buy", 50000.0, 0.1)
        db.add_transaction("ETH", "sell", 3000.0, 1.0)
        txs = db.get_transactions()
        assert len(txs) == 2

    def test_filter_by_symbol(self, db):
        db.add_transaction("BTC", "buy", 50000.0, 0.1)
        db.add_transaction("ETH", "buy", 3000.0, 1.0)
        btc_txs = db.get_transactions("BTC")
        assert len(btc_txs) == 1
        assert btc_txs[0]["symbol"] == "BTC"

    def test_filter_case_insensitive(self, db):
        db.add_transaction("BTC", "buy", 50000.0, 0.1)
        txs = db.get_transactions("btc")
        assert len(txs) == 1

    def test_ordered_by_timestamp_asc(self, db):
        db.add_transaction("BTC", "buy", 50000.0, 0.1)
        db.add_transaction("BTC", "sell", 51000.0, 0.1)
        txs = db.get_transactions("BTC")
        assert txs[0]["id"] < txs[1]["id"]


class TestGetTransaction:
    def test_returns_dict(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        fetched = db.get_transaction(tx["id"])
        assert fetched is not None
        assert fetched["id"] == tx["id"]

    def test_missing_returns_none(self, db):
        assert db.get_transaction(9999) is None


class TestDeleteTransaction:
    def test_delete_existing(self, db):
        tx = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        result = db.delete_transaction(tx["id"])
        assert result is True
        assert db.get_transaction(tx["id"]) is None

    def test_delete_missing_returns_false(self, db):
        assert db.delete_transaction(9999) is False

    def test_delete_reduces_count(self, db):
        tx1 = db.add_transaction("BTC", "buy", 50000.0, 0.01)
        db.add_transaction("BTC", "sell", 51000.0, 0.01)
        db.delete_transaction(tx1["id"])
        assert len(db.get_transactions("BTC")) == 1


class TestAddDeposit:
    def test_returns_dict(self, db):
        dep = db.add_deposit("BTC", 0.5)
        assert isinstance(dep, dict)

    def test_id_assigned(self, db):
        dep = db.add_deposit("ETH", 1.0)
        assert dep["id"] is not None and dep["id"] > 0

    def test_asset_uppercased(self, db):
        dep = db.add_deposit("btc", 0.5)
        assert dep["asset"] == "BTC"

    def test_amount_stored(self, db):
        dep = db.add_deposit("SOL", 10.0)
        assert abs(dep["amount"] - 10.0) < 1e-9

    def test_optional_fields_stored(self, db):
        dep = db.add_deposit("BTC", 1.0, network="BTC", tx_hash="abc123", note="from Coinbase")
        assert dep["network"]  == "BTC"
        assert dep["tx_hash"]  == "abc123"
        assert dep["note"]     == "from Coinbase"

    def test_invalid_amount_raises(self, db):
        with pytest.raises(ValueError):
            db.add_deposit("BTC", -1.0)

    def test_zero_amount_raises(self, db):
        with pytest.raises(ValueError):
            db.add_deposit("BTC", 0)

    def test_empty_asset_raises(self, db):
        with pytest.raises(ValueError):
            db.add_deposit("", 1.0)


class TestGetDeposits:
    def test_empty_on_fresh_db(self, db):
        assert db.get_deposits() == []

    def test_returns_all(self, db):
        db.add_deposit("BTC", 0.5)
        db.add_deposit("ETH", 1.0)
        assert len(db.get_deposits()) == 2

    def test_filter_by_asset(self, db):
        db.add_deposit("BTC", 0.5)
        db.add_deposit("ETH", 1.0)
        btc_deps = db.get_deposits("BTC")
        assert len(btc_deps) == 1
        assert btc_deps[0]["asset"] == "BTC"

    def test_filter_case_insensitive(self, db):
        db.add_deposit("BTC", 0.5)
        assert len(db.get_deposits("btc")) == 1

    def test_ordered_newest_first(self, db):
        db.add_deposit("BTC", 0.1)
        db.add_deposit("BTC", 0.2)
        deps = db.get_deposits("BTC")
        assert deps[0]["id"] > deps[1]["id"]


class TestGetDeposit:
    def test_returns_dict(self, db):
        dep = db.add_deposit("BTC", 0.5)
        fetched = db.get_deposit(dep["id"])
        assert fetched is not None
        assert fetched["id"] == dep["id"]

    def test_missing_returns_none(self, db):
        assert db.get_deposit(9999) is None


class TestDeleteDeposit:
    def test_delete_existing(self, db):
        dep = db.add_deposit("BTC", 0.5)
        assert db.delete_deposit(dep["id"]) is True
        assert db.get_deposit(dep["id"]) is None

    def test_delete_missing_returns_false(self, db):
        assert db.delete_deposit(9999) is False

    def test_delete_reduces_count(self, db):
        dep1 = db.add_deposit("BTC", 0.1)
        db.add_deposit("BTC", 0.2)
        db.delete_deposit(dep1["id"])
        assert len(db.get_deposits("BTC")) == 1
