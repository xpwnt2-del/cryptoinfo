"""
app.py – CryptoBotAI – Flask application entry point.

Run with:
    python app.py
or:
    flask --app app run --port 5000
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from math import floor
from typing import Optional

from flask import Flask, jsonify, render_template, request

from bot.analyzer import analyse
from bot.exchange import ExchangeManager, normalise_symbol
from bot.news import get_aggregate_sentiment, get_market_metadata, get_news
from bot.technical import get_timeframe_signals, ohlcv_to_df, calculate
from config import Config
from database import Database

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App init ──────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY

db = Database()
exchange = ExchangeManager()

_bot_lock = threading.Lock()
_bot_state: dict = {
    "running": False,
    "symbol": None,
    "thread": None,
    "last_action": None,
    "started_at": None,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

_TF_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}


def _floor_ts(ts_seconds: float, timeframe: str) -> int:
    interval = _TF_INTERVAL_SECONDS.get(timeframe, 3600)
    return int(floor(ts_seconds / interval) * interval)


def _transactions_to_markers(transactions: list[dict], timeframe: str) -> list[dict]:
    """Convert stored transactions to Lightweight Charts marker objects."""
    markers: list[dict] = []
    for tx in transactions:
        try:
            ts_str: str = tx["timestamp"]
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            ts_sec = int(dt.timestamp())
            floored = _floor_ts(ts_sec, timeframe)
        except Exception:
            continue

        is_buy = tx["side"] == "buy"
        source = tx.get("source", "user")

        if source == "bot":
            color = "#26a69a" if is_buy else "#ef5350"  # teal / red
            shape = "arrowUp" if is_buy else "arrowDown"
            label = "Bot Buy" if is_buy else "Bot Sell"
        else:
            color = "#2196f3" if is_buy else "#ff9800"  # blue / orange
            shape = "circle"
            label = "Buy" if is_buy else "Sell"

        p = tx['price']
        price_str = (
            f"${p:,.2f}" if p >= 1
            else f"${p:.6f}".rstrip('0').rstrip('.')
        )
        markers.append(
            {
                "time": floored,
                "position": "belowBar" if is_buy else "aboveBar",
                "color": color,
                "shape": shape,
                "text": f"{label} @ {price_str}",
                "transaction_id": tx["id"],
                "source": source,
                "side": tx["side"],
                "price": tx["price"],
                "amount": tx["amount"],
            }
        )
    return markers


def _bot_loop(symbol: str, stop_event: threading.Event) -> None:
    """Background loop that periodically analyses *symbol* and trades when confident."""
    logger.info("Bot loop started for %s", symbol)
    while not stop_event.is_set():
        try:
            _bot_tick(symbol)
        except Exception as exc:
            logger.error("Bot tick error: %s", exc)
        stop_event.wait(Config.BOT_INTERVAL)
    logger.info("Bot loop stopped for %s", symbol)


def _bot_tick(symbol: str) -> None:
    """Single analysis + optional trade for the bot."""
    try:
        ohlcv_1h = exchange.get_ohlcv(symbol, "1h", limit=100)
    except Exception as exc:
        logger.warning("_bot_tick: failed to fetch OHLCV: %s", exc)
        return

    try:
        df = ohlcv_to_df(ohlcv_1h)
        snap = calculate(df)
    except Exception as exc:
        logger.warning("_bot_tick: technical calc failed: %s", exc)
        return

    news = get_news(symbol, limit=10)
    sentiment = get_aggregate_sentiment(news)
    snapshots = {"1h": snap}
    metadata = {}

    try:
        ticker = exchange.get_ticker(symbol)
        price = ticker.get("last")
    except Exception:
        price = None

    result = analyse(symbol, price, snapshots, news, sentiment, metadata)

    with _bot_lock:
        _bot_state["last_action"] = {
            "symbol": symbol,
            "direction": result.overall_direction,
            "confidence": result.overall_confidence,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    if (
        result.overall_confidence >= Config.MIN_CONFIDENCE
        and result.overall_direction in ("bullish", "bearish")
        and Config.EXCHANGE_API_KEY
    ):
        side = "buy" if result.overall_direction == "bullish" else "sell"
        trade_amount = Config.BOT_TRADE_AMOUNT
        try:
            if side == "buy":
                order = exchange.place_market_buy(symbol, amount=trade_amount)
            else:
                order = exchange.place_market_sell(symbol, amount=trade_amount)

            trade_price = order.get("price") or (price or 0)
            db.add_transaction(
                symbol=symbol,
                side=side,
                price=trade_price,
                amount=trade_amount,
                source="bot",
                note=f"Auto-trade: {result.overall_direction} {result.overall_confidence}%",
            )
            logger.info(
                "Bot placed %s order for %s at %.4f (conf=%d%%)",
                side, symbol, trade_price, result.overall_confidence,
            )
        except Exception as exc:
            logger.warning("Bot trade failed: %s", exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/search/<symbol>")
def search(symbol: str):
    """Full analysis for a symbol: ticker, technicals, news, AI predictions."""
    sym = normalise_symbol(symbol)

    # Fetch OHLCV for multiple timeframes
    tf_data: dict[str, list] = {}
    for tf in ("1h", "4h", "1d"):
        try:
            tf_data[tf] = exchange.get_ohlcv(sym, tf, limit=200)
        except Exception as exc:
            logger.warning("OHLCV %s/%s failed: %s", sym, tf, exc)

    snapshots = {}
    for tf, data in tf_data.items():
        try:
            df = ohlcv_to_df(data)
            from bot.technical import calculate as calc
            snapshots[tf] = calc(df)
        except Exception:
            pass

    # Ticker
    price: Optional[float] = None
    ticker_data: dict = {}
    try:
        ticker = exchange.get_ticker(sym)
        price = ticker.get("last")
        ticker_data = {
            "price": price,
            "change_24h": ticker.get("percentage"),
            "volume_24h": ticker.get("quoteVolume"),
            "high_24h": ticker.get("high"),
            "low_24h": ticker.get("low"),
        }
    except Exception as exc:
        logger.warning("Ticker fetch failed: %s", exc)

    # News + metadata
    news = get_news(sym, limit=10)
    sentiment = get_aggregate_sentiment(news)
    metadata = get_market_metadata(sym)

    # AI analysis
    result = analyse(sym, price, snapshots, news, sentiment, metadata)

    # Serialise snapshots
    def _snap_dict(s):
        return {
            "rsi": round(s.rsi, 2) if s.rsi is not None else None,
            "rsi_signal": s.rsi_signal,
            "macd_signal": s.macd_signal,
            "bb_signal": s.bb_signal,
            "ma_signal": s.ma_signal,
            "volume_signal": s.volume_signal,
            "overall_signal": s.overall_signal,
            "score": s.score,
            "summary": s.summary,
            "sma_20": round(s.sma_20, 4) if s.sma_20 else None,
            "sma_50": round(s.sma_50, 4) if s.sma_50 else None,
            "ema_12": round(s.ema_12, 4) if s.ema_12 else None,
            "ema_26": round(s.ema_26, 4) if s.ema_26 else None,
            "bb_upper": round(s.bb_upper, 4) if s.bb_upper else None,
            "bb_lower": round(s.bb_lower, 4) if s.bb_lower else None,
        }

    return jsonify(
        {
            "symbol": sym,
            "ticker": ticker_data,
            "metadata": metadata,
            "indicators": {tf: _snap_dict(s) for tf, s in snapshots.items()},
            "news": news,
            "news_sentiment": sentiment,
            "predictions": [
                {
                    "timeframe": p.timeframe,
                    "direction": p.direction,
                    "confidence": p.confidence,
                    "reasoning": p.reasoning,
                }
                for p in result.predictions
            ],
            "overall_direction": result.overall_direction,
            "overall_confidence": result.overall_confidence,
            "ai_powered": result.ai_powered,
            "summary": result.summary,
        }
    )


@app.route("/api/candles/<symbol>")
def get_candles(symbol: str):
    """
    Return OHLCV candle data + transaction markers for the chart.

    Query params:
        timeframe : one of 1m 5m 15m 30m 1h 4h 1d 1w  (default: 1h)
        limit     : number of candles (default: 200, max: 500)
    """
    sym = normalise_symbol(symbol)
    timeframe = request.args.get("timeframe", "1h")
    try:
        limit = min(int(request.args.get("limit", 200)), 500)
    except (ValueError, TypeError):
        limit = 200

    try:
        raw = exchange.get_ohlcv(sym, timeframe, limit=limit)
    except Exception as exc:
        logger.warning("OHLCV fetch failed for %s/%s: %s", sym, timeframe, exc)
        # Return empty candles rather than 502 – chart will show unavailable message
        transactions = db.get_transactions(sym)
        markers = _transactions_to_markers(transactions, timeframe)
        return jsonify({"candles": [], "markers": markers, "timeframe": timeframe, "error": str(exc)})

    candles = [
        {
            "time": int(row[0] / 1000),  # ms → seconds for Lightweight Charts
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        }
        for row in raw
    ]

    transactions = db.get_transactions(sym)
    markers = _transactions_to_markers(transactions, timeframe)

    return jsonify({"candles": candles, "markers": markers, "timeframe": timeframe})


@app.route("/api/transactions", methods=["GET"])
def list_transactions():
    symbol = request.args.get("symbol")
    if symbol:
        symbol = normalise_symbol(symbol)
    txs = db.get_transactions(symbol)
    return jsonify(txs)


@app.route("/api/transactions", methods=["POST"])
def create_transaction():
    data = request.get_json(force=True, silent=True) or {}
    required = ("symbol", "side", "price", "amount")
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        tx = db.add_transaction(
            symbol=normalise_symbol(str(data["symbol"])),
            side=str(data["side"]),
            price=float(data["price"]),
            amount=float(data["amount"]),
            source="user",
            note=str(data.get("note", "") or ""),
        )
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(tx), 201


@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
def delete_transaction(tx_id: int):
    deleted = db.delete_transaction(tx_id)
    if not deleted:
        return jsonify({"error": "Transaction not found"}), 404
    return jsonify({"deleted": tx_id})


@app.route("/api/balance")
def get_balance():
    try:
        raw = exchange.get_balance()
        balances = {
            asset: float(amt)
            for asset, amt in raw.get("total", {}).items()
            if float(amt or 0) > 0
        }
        return jsonify({"balances": balances})
    except PermissionError as exc:
        return jsonify({"error": str(exc), "balances": {}}), 200
    except Exception as exc:
        return jsonify({"error": str(exc), "balances": {}}), 502


@app.route("/api/sell-all", methods=["POST"])
def sell_all():
    data = request.get_json(force=True, silent=True) or {}
    dry_run = data.get("dry_run", Config.DRY_RUN)

    try:
        results = exchange.sell_all_to_usdt(dry_run=bool(dry_run))
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    # Record non-simulated sells in the transaction log
    if not dry_run:
        for r in results:
            if "error" not in r and not r.get("dry_run"):
                sym = r.get("symbol", "").replace("/USDT", "")
                if sym:
                    try:
                        db.add_transaction(
                            symbol=sym,
                            side="sell",
                            price=float(r.get("average") or r.get("price") or 0),
                            amount=float(r.get("filled") or r.get("amount") or 0),
                            source="bot",
                            note="sell-all-to-USDT",
                        )
                    except Exception:
                        pass

    return jsonify({"dry_run": dry_run, "orders": results})


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    data = request.get_json(force=True, silent=True) or {}
    symbol = normalise_symbol(str(data.get("symbol", "BTC")))

    with _bot_lock:
        if _bot_state["running"]:
            return jsonify({"error": "Bot already running", "symbol": _bot_state["symbol"]}), 409

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_bot_loop, args=(symbol, stop_event), daemon=True
        )
        _bot_state.update(
            {
                "running": True,
                "symbol": symbol,
                "thread": thread,
                "stop_event": stop_event,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "last_action": None,
            }
        )
        thread.start()

    logger.info("Bot started for %s", symbol)
    return jsonify({"status": "started", "symbol": symbol})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    with _bot_lock:
        if not _bot_state["running"]:
            return jsonify({"status": "not_running"}), 200

        stop_event: threading.Event = _bot_state.get("stop_event")
        if stop_event:
            stop_event.set()

        _bot_state.update(
            {"running": False, "symbol": None, "thread": None, "stop_event": None}
        )

    logger.info("Bot stopped")
    return jsonify({"status": "stopped"})


@app.route("/api/bot/status")
def bot_status():
    with _bot_lock:
        return jsonify(
            {
                "running": _bot_state["running"],
                "symbol": _bot_state["symbol"],
                "started_at": _bot_state["started_at"],
                "last_action": _bot_state["last_action"],
                "dry_run": Config.DRY_RUN,
            }
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
