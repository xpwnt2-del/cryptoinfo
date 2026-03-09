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
# Multi-bot state: keyed by normalised symbol
_bot_states: dict[str, dict] = {}

# Maximum number of symbols to scan in /api/ai/recommend
_MAX_RECOMMENDATION_SYMBOLS = 10

# ── Helpers ───────────────────────────────────────────────────────────────────

_TF_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}


def _opt_str(value) -> Optional[str]:
    """Convert a value to str or None; empty strings become None."""
    s = str(value or "").strip()
    return s if s else None


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
        if symbol in _bot_states:
            _bot_states[symbol]["last_action"] = {
                "symbol": symbol,
                "direction": result.overall_direction,
                "confidence": result.overall_confidence,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            direction_filter = _bot_states[symbol].get("direction", "both")
        else:
            direction_filter = "both"

    if (
        result.overall_confidence >= Config.MIN_CONFIDENCE
        and result.overall_direction in ("bullish", "bearish")
        and Config.EXCHANGE_API_KEY
    ):
        side = "buy" if result.overall_direction == "bullish" else "sell"

        # Respect the direction filter configured when the bot was started:
        # "long"  → only buy (go long)
        # "short" → only sell (go short/close)
        # "both"  → trade in either direction
        if direction_filter == "long" and side != "buy":
            logger.info(
                "Bot skipping %s signal for %s (direction_filter=%s)",
                side, symbol, direction_filter,
            )
            return
        if direction_filter == "short" and side != "sell":
            logger.info(
                "Bot skipping %s signal for %s (direction_filter=%s)",
                side, symbol, direction_filter,
            )
            return

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
                note=f"Auto-trade ({direction_filter}): {result.overall_direction} {result.overall_confidence}%",
            )
            logger.info(
                "Bot placed %s order for %s at %.4f (conf=%d%%, dir=%s)",
                side, symbol, trade_price, result.overall_confidence, direction_filter,
            )
        except Exception as exc:
            logger.warning("Bot trade failed: %s", exc)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/ticker/<symbol>")
def get_ticker_price(symbol: str):
    """Lightweight endpoint for live price polling.

    Returns just the latest price + 24-hour change so the UI can refresh
    the coin overview without re-running the full analysis.
    """
    sym = normalise_symbol(symbol)
    try:
        ticker = exchange.get_ticker(sym)
        return jsonify(
            {
                "symbol": sym,
                "price": ticker.get("last"),
                "change_24h": ticker.get("percentage"),
                "high_24h": ticker.get("high"),
                "low_24h": ticker.get("low"),
                "volume_24h": ticker.get("quoteVolume"),
            }
        )
    except Exception as exc:
        logger.warning("Ticker fetch failed for %s: %s", sym, exc)
        return jsonify({"error": str(exc)}), 502


@app.route("/api/search/<symbol>")
def search(symbol: str):
    """Full analysis for a symbol: ticker, technicals, news, AI predictions."""
    sym = normalise_symbol(symbol)
    agent = request.args.get("agent", "auto")

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
    result = analyse(sym, price, snapshots, news, sentiment, metadata, agent=agent)

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

    def _pred_dict(p):
        return {
            "timeframe": p.timeframe,
            "direction": p.direction,
            "confidence": p.confidence,
            "reasoning": p.reasoning,
            "source": p.source,
        }

    return jsonify(
        {
            "symbol": sym,
            "ticker": ticker_data,
            "metadata": metadata,
            "indicators": {tf: _snap_dict(s) for tf, s in snapshots.items()},
            "news": news,
            "news_sentiment": sentiment,
            "predictions": [_pred_dict(p) for p in result.predictions],
            "openai_predictions": [_pred_dict(p) for p in result.openai_predictions],
            "rule_based_predictions": [_pred_dict(p) for p in result.rule_based_predictions],
            "overall_direction": result.overall_direction,
            "overall_confidence": result.overall_confidence,
            "ai_powered": result.ai_powered,
            "agent": result.agent,
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


@app.route("/api/wallet")
def get_wallet():
    """Return combined wallet view: exchange balances + deposit-based holdings.

    Exchange balances are fetched when API keys are configured; otherwise an
    empty dict is returned.  Deposit totals are always available (local DB).

    Response shape::

        {
          "exchange_balances": {"BTC": 0.5, "USDT": 1200.0, ...},
          "deposit_totals":    {"BTC": 1.0, "ETH": 2.5, ...},
          "prices":            {"BTC": 67000.0, "ETH": 3500.0, ...},
          "total_usd":         <estimated total portfolio value>,
          "exchange_error":    null | "<error message>",
        }
    """
    # Exchange balances (requires API keys)
    exchange_balances: dict[str, float] = {}
    exchange_error: Optional[str] = None
    try:
        raw = exchange.get_balance()
        exchange_balances = {
            asset: float(amt)
            for asset, amt in raw.get("total", {}).items()
            if float(amt or 0) > 0
        }
    except PermissionError as exc:
        exchange_error = str(exc)
    except Exception as exc:
        exchange_error = str(exc)

    # Deposit totals from local database
    deposits = db.get_deposits()
    deposit_totals: dict[str, float] = {}
    for dep in deposits:
        asset = dep["asset"]
        deposit_totals[asset] = deposit_totals.get(asset, 0.0) + dep["amount"]

    # Collect all unique non-USDT assets to price
    all_assets = set(exchange_balances) | set(deposit_totals)
    prices: dict[str, float] = {}
    for asset in all_assets:
        if asset == "USDT":
            prices[asset] = 1.0
            continue
        try:
            ticker = exchange.get_ticker(asset)
            p = ticker.get("last")
            if p:
                prices[asset] = float(p)
        except Exception:
            pass  # price unavailable – skip

    # Estimate total USD value.
    # Prefer live exchange balances when available (exchange_error is None);
    # fall back to locally-tracked deposit totals so the total is always shown.
    holdings = exchange_balances if exchange_error is None and exchange_balances else deposit_totals
    total_usd = sum(
        amount * prices.get(asset, 0.0)
        for asset, amount in holdings.items()
    )

    return jsonify(
        {
            "exchange_balances": exchange_balances,
            "deposit_totals": deposit_totals,
            "prices": prices,
            "total_usd": total_usd,
            "exchange_error": exchange_error,
        }
    )


@app.route("/api/wallet/deposits", methods=["GET"])
def list_deposits():
    asset = request.args.get("asset")
    if asset:
        asset = normalise_symbol(asset)
    return jsonify(db.get_deposits(asset))


@app.route("/api/wallet/deposits", methods=["POST"])
def create_deposit():
    data = request.get_json(force=True, silent=True) or {}
    required = ("asset", "amount")
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    try:
        dep = db.add_deposit(
            asset=normalise_symbol(str(data["asset"])),
            amount=float(data["amount"]),
            network=_opt_str(data.get("network")),
            tx_hash=_opt_str(data.get("tx_hash")),
            note=_opt_str(data.get("note")),
        )
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(dep), 201


@app.route("/api/wallet/deposits/<int:dep_id>", methods=["DELETE"])
def delete_deposit(dep_id: int):
    deleted = db.delete_deposit(dep_id)
    if not deleted:
        return jsonify({"error": "Deposit not found"}), 404
    return jsonify({"deleted": dep_id})


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


@app.route("/api/ai/recommend")
def ai_recommend():
    """Return AI-recommended crypto picks for 1h, 1d, and 1w timeframes.

    Analyses a basket of popular coins and returns the top bullish pick for
    each timeframe based on the currently configured AI agent.

    Query params:
        agent  : 'auto' (default) | 'openai' | 'rule-based' | 'both'
        symbols: comma-separated list of symbols to scan
                 (default: BTC,ETH,SOL,BNB,XRP,ADA,AVAX,DOGE,DOT,MATIC)
    """
    agent = request.args.get("agent", "auto")
    raw_symbols = request.args.get(
        "symbols", "BTC,ETH,SOL,BNB,XRP,ADA,AVAX,DOGE,DOT,MATIC"
    )
    symbols = [normalise_symbol(s.strip()) for s in raw_symbols.split(",") if s.strip()][:_MAX_RECOMMENDATION_SYMBOLS]

    results_by_tf: dict[str, list] = {"1h": [], "1d": [], "1w": []}

    for sym in symbols:
        try:
            # Fetch OHLCV and compute technicals
            tf_data: dict[str, list] = {}
            for tf in ("1h", "4h", "1d"):
                try:
                    tf_data[tf] = exchange.get_ohlcv(sym, tf, limit=100)
                except Exception:
                    pass

            snapshots = {}
            for tf, ohlcv in tf_data.items():
                try:
                    from bot.technical import calculate as calc
                    snapshots[tf] = calc(ohlcv_to_df(ohlcv))
                except Exception:
                    pass

            if not snapshots:
                continue

            try:
                ticker = exchange.get_ticker(sym)
                price = ticker.get("last")
            except Exception:
                price = None

            news = get_news(sym, limit=5)
            sentiment = get_aggregate_sentiment(news)

            result = analyse(sym, price, snapshots, news, sentiment, {}, agent=agent)

            for pred in result.predictions:
                if pred.timeframe in results_by_tf:
                    results_by_tf[pred.timeframe].append(
                        {
                            "symbol": sym,
                            "direction": pred.direction,
                            "confidence": pred.confidence,
                            "reasoning": pred.reasoning,
                            "price": price,
                        }
                    )
        except Exception as exc:
            logger.warning("Recommendation analysis failed for %s: %s", sym, exc)

    # Sort each timeframe by confidence descending, keep top 3 bullish picks
    recommendations: dict[str, list] = {}
    for tf, entries in results_by_tf.items():
        bullish = sorted(
            [e for e in entries if e["direction"] == "bullish"],
            key=lambda x: x["confidence"],
            reverse=True,
        )
        recommendations[tf] = bullish[:3]

    return jsonify(
        {
            "agent": agent,
            "symbols_scanned": symbols,
            "recommendations": recommendations,
        }
    )


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    data = request.get_json(force=True, silent=True) or {}
    symbol = normalise_symbol(str(data.get("symbol", "BTC")))
    # direction: "both" (default), "long" (buy only), "short" (sell only)
    direction = str(data.get("direction", "both")).lower()
    if direction not in ("both", "long", "short"):
        direction = "both"

    with _bot_lock:
        if symbol in _bot_states and _bot_states[symbol].get("running"):
            return jsonify({"error": "Bot already running for this symbol", "symbol": symbol}), 409

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_bot_loop, args=(symbol, stop_event), daemon=True
        )
        _bot_states[symbol] = {
            "running": True,
            "symbol": symbol,
            "thread": thread,
            "stop_event": stop_event,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_action": None,
            "direction": direction,
        }
        thread.start()

    logger.info("Bot started for %s (direction=%s)", symbol, direction)
    return jsonify({"status": "started", "symbol": symbol, "direction": direction})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    data = request.get_json(force=True, silent=True) or {}
    # If a symbol is supplied, stop only that bot; otherwise stop all.
    raw_symbol = data.get("symbol", "")
    symbol = normalise_symbol(str(raw_symbol)) if raw_symbol else None

    stopped: list[str] = []
    with _bot_lock:
        targets = [symbol] if symbol else list(_bot_states.keys())
        for sym in targets:
            state = _bot_states.get(sym)
            if state and state.get("running"):
                se: threading.Event = state.get("stop_event")
                if se:
                    se.set()
                state["running"] = False
                stopped.append(sym)

    for sym in stopped:
        logger.info("Bot stopped for %s", sym)

    if not stopped and symbol:
        return jsonify({"status": "not_running", "symbol": symbol}), 200

    return jsonify({"status": "stopped", "symbols": stopped})


@app.route("/api/bot/status")
def bot_status():
    with _bot_lock:
        bots = [
            {
                "symbol": sym,
                "running": state["running"],
                "started_at": state["started_at"],
                "last_action": state["last_action"],
                "direction": state.get("direction", "both"),
            }
            for sym, state in _bot_states.items()
            if state.get("running")
        ]
        return jsonify(
            {
                "bots": bots,
                # Legacy fields for backwards compatibility
                "running": bool(bots),
                "symbol": bots[0]["symbol"] if bots else None,
                "dry_run": Config.DRY_RUN,
            }
        )


@app.route("/health")
def health():
    """Liveness/readiness probe used by Docker HEALTHCHECK and Cloudflare."""
    return jsonify({"status": "ok"}), 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
