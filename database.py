"""
database.py – SQLite persistence for bot and user transactions.
"""

import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "cryptobot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT    NOT NULL,
    side       TEXT    NOT NULL CHECK(side IN ('buy','sell')),
    price      REAL    NOT NULL CHECK(price > 0),
    amount     REAL    NOT NULL CHECK(amount > 0),
    total      REAL    NOT NULL,
    timestamp  TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT 'user'
                       CHECK(source IN ('bot','user')),
    note       TEXT
);

CREATE TABLE IF NOT EXISTS deposits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset      TEXT    NOT NULL,
    amount     REAL    NOT NULL CHECK(amount > 0),
    timestamp  TEXT    NOT NULL,
    network    TEXT,
    tx_hash    TEXT,
    note       TEXT
);
"""


class Database:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    # ── internal helpers ──────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ── public API ────────────────────────────────────────────────────────

    def add_transaction(
        self,
        symbol: str,
        side: str,
        price: float,
        amount: float,
        source: str = "user",
        note: Optional[str] = None,
    ) -> dict:
        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if price <= 0 or amount <= 0:
            raise ValueError("price and amount must be positive")
        if source not in ("bot", "user"):
            raise ValueError(f"source must be 'bot' or 'user', got {source!r}")

        total = price * amount
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO transactions (symbol, side, price, amount, total,
                                          timestamp, source, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol.upper(), side, price, amount, total,
                 timestamp, source, note),
            )
            conn.commit()
            row_id = cur.lastrowid

        return self.get_transaction(row_id)

    def get_transaction(self, transaction_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_transactions(self, symbol: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE symbol = ? ORDER BY timestamp ASC",
                    (symbol.upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM transactions ORDER BY timestamp ASC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_transaction(self, transaction_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM transactions WHERE id = ?", (transaction_id,)
            )
            conn.commit()
        return cur.rowcount > 0

    # ── deposits ──────────────────────────────────────────────────────────

    def add_deposit(
        self,
        asset: str,
        amount: float,
        network: Optional[str] = None,
        tx_hash: Optional[str] = None,
        note: Optional[str] = None,
    ) -> dict:
        """Record a deposit of *amount* units of *asset*."""
        if not asset:
            raise ValueError("asset must not be empty")
        if amount <= 0:
            raise ValueError("amount must be positive")

        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO deposits (asset, amount, timestamp, network, tx_hash, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (asset.upper(), amount, timestamp, network, tx_hash, note),
            )
            conn.commit()
            row_id = cur.lastrowid
        return self.get_deposit(row_id)

    def get_deposit(self, deposit_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM deposits WHERE id = ?", (deposit_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_deposits(self, asset: Optional[str] = None) -> list[dict]:
        with self._connect() as conn:
            if asset:
                rows = conn.execute(
                    "SELECT * FROM deposits WHERE asset = ? ORDER BY timestamp DESC",
                    (asset.upper(),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM deposits ORDER BY timestamp DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_deposit(self, deposit_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM deposits WHERE id = ?", (deposit_id,)
            )
            conn.commit()
        return cur.rowcount > 0
