"""
bot/exchange.py – ccxt wrapper for market data and order execution.

Read-only operations (ticker, OHLCV) work without API keys via
Binance's public endpoints.  Trading operations require valid
EXCHANGE_API_KEY and EXCHANGE_SECRET in the environment.
"""

from __future__ import annotations

import logging
from typing import Optional

import ccxt

from config import Config

logger = logging.getLogger(__name__)

# Map common user-typed symbols to ccxt base symbols
_SYMBOL_ALIASES: dict[str, str] = {
    "BITCOIN": "BTC",
    "ETHEREUM": "ETH",
    "SOLANA": "SOL",
    "CARDANO": "ADA",
    "RIPPLE": "XRP",
    "DOGECOIN": "DOGE",
    "SHIBA": "SHIB",
    "POLKADOT": "DOT",
    "CHAINLINK": "LINK",
    "AVALANCHE": "AVAX",
    "MATIC": "MATIC",
    "POLYGON": "MATIC",
    "LITECOIN": "LTC",
    "UNISWAP": "UNI",
    "AAVE": "AAVE",
}

SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")


def normalise_symbol(raw: str) -> str:
    """Uppercase and resolve common aliases."""
    upper = raw.strip().upper()
    return _SYMBOL_ALIASES.get(upper, upper)


class ExchangeManager:
    """Thin wrapper around a ccxt exchange instance."""

    def __init__(self) -> None:
        exchange_cls = getattr(ccxt, Config.EXCHANGE_ID, None)
        if exchange_cls is None:
            logger.warning(
                "Unknown exchange %r, falling back to binance", Config.EXCHANGE_ID
            )
            exchange_cls = ccxt.binance

        self.exchange: ccxt.Exchange = exchange_cls(
            {
                "apiKey": Config.EXCHANGE_API_KEY or None,
                "secret": Config.EXCHANGE_SECRET or None,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )
        self._authenticated = bool(
            Config.EXCHANGE_API_KEY and Config.EXCHANGE_SECRET
        )

    # ── public read-only methods (no auth needed) ─────────────────────────

    def get_ticker(self, symbol: str) -> dict:
        """Return latest ticker for *symbol*/USDT."""
        pair = f"{normalise_symbol(symbol)}/USDT"
        try:
            return self.exchange.fetch_ticker(pair)
        except ccxt.BaseError as exc:
            logger.error("fetch_ticker failed for %s: %s", pair, exc)
            raise

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 200,
    ) -> list[list]:
        """Return OHLCV candles as [[ts_ms, O, H, L, C, V], ...]."""
        if timeframe not in SUPPORTED_TIMEFRAMES:
            timeframe = "1h"
        pair = f"{normalise_symbol(symbol)}/USDT"
        try:
            return self.exchange.fetch_ohlcv(pair, timeframe, limit=limit)
        except ccxt.BaseError as exc:
            logger.error("fetch_ohlcv failed for %s: %s", pair, exc)
            raise

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        pair = f"{normalise_symbol(symbol)}/USDT"
        try:
            return self.exchange.fetch_order_book(pair, limit)
        except ccxt.BaseError as exc:
            logger.error("fetch_order_book failed: %s", exc)
            raise

    # ── authenticated methods ─────────────────────────────────────────────

    def _require_auth(self) -> None:
        if not self._authenticated:
            raise PermissionError(
                "Exchange API keys not configured. "
                "Set EXCHANGE_API_KEY and EXCHANGE_SECRET in your .env file."
            )

    def get_balance(self) -> dict:
        self._require_auth()
        try:
            return self.exchange.fetch_balance()
        except ccxt.BaseError as exc:
            logger.error("fetch_balance failed: %s", exc)
            raise

    def sell_all_to_usdt(self, dry_run: Optional[bool] = None) -> list[dict]:
        """
        Sell every non-USDT balance back to USDT.

        Returns a list of order result dicts (or simulated order dicts when
        *dry_run* is True).
        """
        self._require_auth()
        effective_dry = dry_run if dry_run is not None else Config.DRY_RUN
        balance = self.get_balance()
        results: list[dict] = []

        for asset, info in balance.get("total", {}).items():
            if asset == "USDT" or float(info or 0) <= 0:
                continue
            pair = f"{asset}/USDT"
            amount = float(info)
            if effective_dry:
                results.append(
                    {
                        "symbol": pair,
                        "amount": amount,
                        "status": "simulated",
                        "dry_run": True,
                    }
                )
                logger.info("[DRY RUN] Would sell %.6f %s", amount, asset)
            else:
                try:
                    order = self.exchange.create_market_sell_order(pair, amount)
                    results.append(order)
                    logger.info("Sold %.6f %s → USDT  order=%s", amount, asset, order.get("id"))
                except ccxt.BaseError as exc:
                    logger.error("sell_all failed for %s: %s", pair, exc)
                    results.append({"symbol": pair, "error": str(exc)})

        return results

    def place_market_buy(self, symbol: str, amount: float) -> dict:
        self._require_auth()
        pair = f"{normalise_symbol(symbol)}/USDT"
        if Config.DRY_RUN:
            ticker = self.get_ticker(symbol)
            return {
                "symbol": pair,
                "amount": amount,
                "price": ticker["last"],
                "status": "simulated",
                "dry_run": True,
            }
        order = self.exchange.create_market_buy_order(pair, amount)
        return order

    def place_market_sell(self, symbol: str, amount: float) -> dict:
        self._require_auth()
        pair = f"{normalise_symbol(symbol)}/USDT"
        if Config.DRY_RUN:
            ticker = self.get_ticker(symbol)
            return {
                "symbol": pair,
                "amount": amount,
                "price": ticker["last"],
                "status": "simulated",
                "dry_run": True,
            }
        order = self.exchange.create_market_sell_order(pair, amount)
        return order
