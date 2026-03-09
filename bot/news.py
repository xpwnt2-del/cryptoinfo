"""
bot/news.py – Headline aggregation and sentiment scoring.

Uses CryptoCompare (free, no auth) for headlines and
CoinGecko (free, no auth) for coin metadata.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from config import Config

logger = logging.getLogger(__name__)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "CryptoBotAI/1.0"})

# Keyword lists for simple sentiment scoring
_BULLISH_WORDS = frozenset(
    {
        "surge", "rally", "bull", "breakout", "gain", "rise", "high",
        "adoption", "buy", "upgrade", "partnership", "positive", "growth",
        "outperform", "strong", "momentum", "support", "bullish", "record",
        "milestone", "launch", "approve", "approved", "etf", "institutional",
        "accumulate", "pump", "recovery", "recover", "uptrend", "bottom",
    }
)

_BEARISH_WORDS = frozenset(
    {
        "crash", "drop", "bear", "dump", "sell", "warning", "risk", "fear",
        "lower", "resistance", "negative", "loss", "hack", "ban", "regulate",
        "regulation", "lawsuit", "investigation", "scam", "fraud", "bearish",
        "downtrend", "decline", "concern", "problem", "issue", "vulnerable",
        "correction", "weak", "panic", "liquidation", "capitulate",
    }
)

_MAX_DESCRIPTION_LENGTH = 300

# CoinGecko symbol → id mapping for common coins
_COINGECKO_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "USDC": "usd-coin",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "TON": "the-open-network",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "UNI": "uniswap",
    "SHIB": "shiba-inu",
    "LTC": "litecoin",
    "ATOM": "cosmos",
    "NEAR": "near",
    "FTM": "fantom",
    "ALGO": "algorand",
    "AAVE": "aave",
    "MKR": "maker",
}


def _score_text(text: str) -> int:
    """Return sentiment score for *text*: positive = bullish, negative = bearish."""
    words = text.lower().split()
    score = 0
    for word in words:
        clean = word.strip(".,!?;:'\"()")
        if clean in _BULLISH_WORDS:
            score += 1
        elif clean in _BEARISH_WORDS:
            score -= 1
    return score


def score_to_label(score: int) -> str:
    if score > 0:
        return "bullish"
    if score < 0:
        return "bearish"
    return "neutral"


def get_news(symbol: str, limit: int = 10) -> list[dict]:
    """
    Fetch recent headlines for *symbol* from CryptoCompare.
    Returns a list of dicts with keys: title, url, source, published_on,
    sentiment, sentiment_score.
    """
    url = f"{Config.CRYPTOCOMPARE_BASE}/v2/news/"
    params = {"categories": symbol.upper(), "lang": "EN", "sortOrder": "latest"}
    try:
        resp = _SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("Data", [])
    except Exception as exc:
        logger.warning("CryptoCompare news request failed: %s", exc)
        return []

    articles: list[dict] = []
    for item in raw[:limit]:
        title = item.get("title", "")
        body = item.get("body", "")
        score = _score_text(title + " " + body)
        articles.append(
            {
                "title": title,
                "url": item.get("url", ""),
                "source": item.get("source_info", {}).get("name", ""),
                "published_on": item.get("published_on", 0),
                "sentiment": score_to_label(score),
                "sentiment_score": score,
            }
        )
    return articles


def get_market_metadata(symbol: str) -> dict:
    """
    Fetch coin metadata from CoinGecko: market cap, 24h volume, description, etc.
    """
    coin_id = _COINGECKO_IDS.get(symbol.upper())
    if not coin_id:
        # Try a search first
        coin_id = _search_coingecko_id(symbol)
    if not coin_id:
        return {}

    url = f"{Config.COINGECKO_BASE}/coins/{coin_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "community_data": "false",
        "developer_data": "false",
    }
    try:
        resp = _SESSION.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("CoinGecko metadata request failed: %s", exc)
        return {}

    mkt = data.get("market_data", {})
    return {
        "name": data.get("name", symbol),
        "symbol": data.get("symbol", "").upper(),
        "description": data.get("description", {}).get("en", "")[:_MAX_DESCRIPTION_LENGTH],
        "market_cap_usd": mkt.get("market_cap", {}).get("usd"),
        "total_volume_usd": mkt.get("total_volume", {}).get("usd"),
        "price_usd": mkt.get("current_price", {}).get("usd"),
        "price_change_24h": mkt.get("price_change_percentage_24h"),
        "price_change_7d": mkt.get("price_change_percentage_7d"),
        "ath_usd": mkt.get("ath", {}).get("usd"),
        "atl_usd": mkt.get("atl", {}).get("usd"),
        "circulating_supply": mkt.get("circulating_supply"),
        "market_cap_rank": data.get("market_cap_rank"),
        "coingecko_id": coin_id,
    }


def _search_coingecko_id(symbol: str) -> Optional[str]:
    """Search CoinGecko for the ID matching *symbol*."""
    url = f"{Config.COINGECKO_BASE}/search"
    try:
        resp = _SESSION.get(url, params={"query": symbol}, timeout=8)
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        for coin in coins:
            if coin.get("symbol", "").upper() == symbol.upper():
                return coin["id"]
    except Exception as exc:
        logger.warning("CoinGecko search failed: %s", exc)
    return None


def get_aggregate_sentiment(articles: list[dict]) -> dict:
    """Return an aggregated sentiment summary from a list of news articles."""
    if not articles:
        return {"label": "neutral", "score": 0, "bullish": 0, "bearish": 0, "neutral": 0}

    total = sum(a["sentiment_score"] for a in articles)
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for a in articles:
        counts[a["sentiment"]] += 1

    avg = total / len(articles)
    label = score_to_label(round(avg))
    return {
        "label": label,
        "score": round(avg, 2),
        **counts,
    }
