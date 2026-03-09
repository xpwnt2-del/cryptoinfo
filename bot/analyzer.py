"""
bot/analyzer.py – Multi-timeframe AI analysis engine.

Primary path  : OpenAI GPT (if OPENAI_API_KEY is configured).
Fallback path : Deterministic rule-based scoring from technicals + news.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from bot.technical import IndicatorSnapshot
from config import Config

logger = logging.getLogger(__name__)

# Timeframes analysed, ordered short → long
TIMEFRAMES = ("1h", "4h", "1d", "1w")

# Score thresholds
_STRONG_BULL = 40
_STRONG_BEAR = -40
_WEAK_BULL = 15
_WEAK_BEAR = -15


@dataclass
class TimeframePrediction:
    timeframe: str
    direction: str  # 'bullish' | 'bearish' | 'neutral'
    confidence: int  # 0–100
    reasoning: str


@dataclass
class AnalysisResult:
    symbol: str
    current_price: Optional[float]
    predictions: list[TimeframePrediction] = field(default_factory=list)
    overall_direction: str = "neutral"
    overall_confidence: int = 0
    news_sentiment: str = "neutral"
    news_score: float = 0.0
    technical_score: int = 0
    ai_powered: bool = False
    summary: str = ""


# ── helpers ──────────────────────────────────────────────────────────────────

def _direction_from_score(score: int) -> str:
    if score >= _WEAK_BULL:
        return "bullish"
    if score <= _WEAK_BEAR:
        return "bearish"
    return "neutral"


def _confidence_from_score(score: int) -> int:
    """Map –100…+100 score to 0…100 confidence."""
    return min(100, max(0, abs(score)))


def _blend_score(tech_score: int, news_score: float, tf: str) -> int:
    """
    Blend technical and news scores with timeframe-specific weights.
    Short TFs lean on technicals; long TFs lean on news/sentiment.
    """
    weights = {
        "1h": (0.85, 0.15),
        "4h": (0.70, 0.30),
        "1d": (0.50, 0.50),
        "1w": (0.30, 0.70),
    }
    tw, nw = weights.get(tf, (0.65, 0.35))
    blended = tw * tech_score + nw * news_score * 20  # news_score in ±5 range
    return int(max(-100, min(100, blended)))


def _rule_based_prediction(
    tf: str,
    snap: IndicatorSnapshot,
    news_score: float,
) -> TimeframePrediction:
    blended = _blend_score(snap.score, news_score, tf)
    direction = _direction_from_score(blended)
    confidence = _confidence_from_score(blended)

    parts: list[str] = []
    if snap.rsi is not None:
        parts.append(f"RSI {snap.rsi:.0f}")
    if snap.macd_signal != "neutral":
        parts.append(f"MACD {snap.macd_signal}")
    if snap.ma_signal != "neutral":
        parts.append(f"MA cross {snap.ma_signal}")
    if news_score > 0.3:
        parts.append("positive headlines")
    elif news_score < -0.3:
        parts.append("negative headlines")

    reasoning = "; ".join(parts) if parts else "Mixed signals – no clear edge."
    return TimeframePrediction(
        timeframe=tf,
        direction=direction,
        confidence=confidence,
        reasoning=reasoning,
    )


# ── OpenAI integration ────────────────────────────────────────────────────────

def _build_prompt(
    symbol: str,
    price: Optional[float],
    snapshots: dict[str, IndicatorSnapshot],
    news_items: list[dict],
    metadata: dict,
) -> str:
    lines = [
        f"Analyse {symbol}/USDT for a crypto trader.",
        f"Current price: {'${:,.4f}'.format(price) if price else 'unknown'}",
        "",
        "## Technical Indicators",
    ]
    for tf, snap in snapshots.items():
        lines.append(
            f"  {tf}: RSI={snap.rsi:.1f if snap.rsi else 'n/a'}, "
            f"MACD={snap.macd_signal}, BB={snap.bb_signal}, "
            f"MA={snap.ma_signal}, score={snap.score}"
        )

    if news_items:
        lines += ["", "## Recent Headlines (top 5)"]
        for a in news_items[:5]:
            lines.append(f"  [{a['sentiment'].upper()}] {a['title']}")

    if metadata:
        lines += [
            "",
            "## Market Context",
            f"  Market cap rank: {metadata.get('market_cap_rank', 'n/a')}",
            f"  24h change: {metadata.get('price_change_24h', 'n/a')}%",
            f"  7d change: {metadata.get('price_change_7d', 'n/a')}%",
        ]

    lines += [
        "",
        "Respond in JSON only, no markdown:",
        '{"predictions": [{"timeframe": "1h", "direction": "bullish|bearish|neutral", '
        '"confidence": 0-100, "reasoning": "..."}, ...for 4h, 1d, 1w], '
        '"overall_direction": "bullish|bearish|neutral", '
        '"overall_confidence": 0-100, "summary": "2-sentence summary"}',
    ]
    return "\n".join(lines)


def _parse_openai_response(data: dict, symbol: str, price: Optional[float]) -> AnalysisResult:
    import json as _json

    try:
        content = data["choices"][0]["message"]["content"]
        parsed = _json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse OpenAI response: %s", exc)
        raise

    predictions = [
        TimeframePrediction(
            timeframe=p["timeframe"],
            direction=p.get("direction", "neutral"),
            confidence=int(p.get("confidence", 50)),
            reasoning=p.get("reasoning", ""),
        )
        for p in parsed.get("predictions", [])
    ]

    return AnalysisResult(
        symbol=symbol,
        current_price=price,
        predictions=predictions,
        overall_direction=parsed.get("overall_direction", "neutral"),
        overall_confidence=int(parsed.get("overall_confidence", 50)),
        ai_powered=True,
        summary=parsed.get("summary", ""),
    )


# ── public API ────────────────────────────────────────────────────────────────

def analyse(
    symbol: str,
    price: Optional[float],
    snapshots: dict[str, IndicatorSnapshot],
    news_items: list[dict],
    news_sentiment: dict,
    metadata: dict,
) -> AnalysisResult:
    """
    Return a full :class:`AnalysisResult` for *symbol*.

    Tries OpenAI first; falls back to rule-based scoring if the API
    key is missing or the call fails.
    """
    news_score = float(news_sentiment.get("score", 0))

    # Prefer the 1h snapshot for the overall technical score; fall back to any
    ref_snap = snapshots.get("1h") or next(iter(snapshots.values()), IndicatorSnapshot())
    tech_score = ref_snap.score

    if Config.OPENAI_API_KEY:
        try:
            result = _call_openai(symbol, price, snapshots, news_items, metadata)
            result.news_sentiment = news_sentiment.get("label", "neutral")
            result.news_score = news_score
            result.technical_score = tech_score
            return result
        except Exception as exc:
            logger.warning("OpenAI call failed, using rule-based fallback: %s", exc)

    # Rule-based fallback
    predictions = [
        _rule_based_prediction(tf, snapshots.get(tf, IndicatorSnapshot()), news_score)
        for tf in TIMEFRAMES
    ]

    scores = [p.confidence * (1 if p.direction == "bullish" else -1 if p.direction == "bearish" else 0)
              for p in predictions]
    avg_score = sum(scores) / len(scores) if scores else 0
    overall_dir = _direction_from_score(int(avg_score))
    overall_conf = _confidence_from_score(int(abs(avg_score)))

    summaries = []
    if overall_dir == "bullish":
        summaries.append(f"{symbol} shows bullish signals across multiple timeframes.")
    elif overall_dir == "bearish":
        summaries.append(f"{symbol} shows bearish signals across multiple timeframes.")
    else:
        summaries.append(f"{symbol} signals are mixed with no clear directional edge.")

    tech_parts = ref_snap.summary[:2] if ref_snap.summary else []
    if tech_parts:
        summaries.append(" ".join(tech_parts))

    return AnalysisResult(
        symbol=symbol,
        current_price=price,
        predictions=predictions,
        overall_direction=overall_dir,
        overall_confidence=overall_conf,
        news_sentiment=news_sentiment.get("label", "neutral"),
        news_score=news_score,
        technical_score=tech_score,
        ai_powered=False,
        summary=" ".join(summaries),
    )


def _call_openai(
    symbol: str,
    price: Optional[float],
    snapshots: dict[str, IndicatorSnapshot],
    news_items: list[dict],
    metadata: dict,
) -> AnalysisResult:
    from openai import OpenAI  # lazy import – only needed when key is present

    client = OpenAI(api_key=Config.OPENAI_API_KEY)
    prompt = _build_prompt(symbol, price, snapshots, news_items, metadata)

    response = client.chat.completions.create(
        model=Config.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert cryptocurrency analyst. "
                    "Always respond in valid JSON only. No markdown. No commentary."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=600,
    )

    raw = {
        "choices": [
            {
                "message": {
                    "content": response.choices[0].message.content
                }
            }
        ]
    }
    return _parse_openai_response(raw, symbol, price)
