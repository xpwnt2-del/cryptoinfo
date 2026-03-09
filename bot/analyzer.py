"""
bot/analyzer.py – Multi-timeframe AI analysis engine.

Primary path  : OpenAI GPT (if OPENAI_API_KEY is configured).
Fallback path : Deterministic rule-based scoring from technicals + news.

Agent modes:
  'auto'       – OpenAI if API key set, else rule-based (original behaviour)
  'openai'     – Force OpenAI (errors if key missing)
  'rule-based' – Always use rule-based scoring
  'both'       – Run both and include combined results
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

# Valid agent identifiers
AGENTS = ("auto", "openai", "rule-based", "both")

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
    source: str = "rule-based"  # 'openai' | 'rule-based' | 'combined'


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
    agent: str = "rule-based"  # which agent produced this result
    summary: str = ""
    # When agent='both', these hold each engine's individual predictions
    openai_predictions: list[TimeframePrediction] = field(default_factory=list)
    rule_based_predictions: list[TimeframePrediction] = field(default_factory=list)


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
        source="rule-based",
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
            source="openai",
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
    agent: str = "auto",
) -> AnalysisResult:
    """
    Return a full :class:`AnalysisResult` for *symbol*.

    *agent* controls which analysis engine is used:
      - ``'auto'``       – OpenAI if API key is set, else rule-based (default)
      - ``'openai'``     – Force OpenAI GPT analysis
      - ``'rule-based'`` – Always use rule-based scoring
      - ``'both'``       – Run both engines and return combined/compared result
    """
    news_score = float(news_sentiment.get("score", 0))

    # Prefer the 1h snapshot for the overall technical score; fall back to any
    ref_snap = snapshots.get("1h") or next(iter(snapshots.values()), IndicatorSnapshot())
    tech_score = ref_snap.score

    # Normalise unknown agent values to 'auto'
    if agent not in AGENTS:
        agent = "auto"

    if agent == "both":
        return _analyse_both(symbol, price, snapshots, news_items, news_sentiment, metadata)

    if agent == "rule-based":
        return _rule_based_result(symbol, price, snapshots, news_items, news_sentiment, metadata)

    # agent == 'openai' or 'auto'
    if Config.OPENAI_API_KEY:
        try:
            result = _call_openai(symbol, price, snapshots, news_items, metadata)
            result.news_sentiment = news_sentiment.get("label", "neutral")
            result.news_score = news_score
            result.technical_score = tech_score
            result.agent = "openai"
            return result
        except Exception as exc:
            if agent == "openai":
                logger.warning("OpenAI call failed: %s", exc)
                raise
            logger.warning("OpenAI call failed, using rule-based fallback: %s", exc)
    elif agent == "openai":
        raise ValueError("OPENAI_API_KEY is not configured")

    return _rule_based_result(symbol, price, snapshots, news_items, news_sentiment, metadata)


def _rule_based_result(
    symbol: str,
    price: Optional[float],
    snapshots: dict[str, IndicatorSnapshot],
    news_items: list[dict],
    news_sentiment: dict,
    metadata: dict,
) -> AnalysisResult:
    """Build a full AnalysisResult using the rule-based engine only."""
    news_score = float(news_sentiment.get("score", 0))
    ref_snap = snapshots.get("1h") or next(iter(snapshots.values()), IndicatorSnapshot())
    tech_score = ref_snap.score

    predictions = [
        _rule_based_prediction(tf, snapshots.get(tf, IndicatorSnapshot()), news_score)
        for tf in TIMEFRAMES
    ]

    scores = [
        p.confidence * (1 if p.direction == "bullish" else -1 if p.direction == "bearish" else 0)
        for p in predictions
    ]
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
        agent="rule-based",
        summary=" ".join(summaries),
        rule_based_predictions=predictions,
    )


def _analyse_both(
    symbol: str,
    price: Optional[float],
    snapshots: dict[str, IndicatorSnapshot],
    news_items: list[dict],
    news_sentiment: dict,
    metadata: dict,
) -> AnalysisResult:
    """
    Run both OpenAI and rule-based engines, return a combined result.
    If OpenAI is unavailable the result gracefully degrades to rule-based only.
    """
    news_score = float(news_sentiment.get("score", 0))
    ref_snap = snapshots.get("1h") or next(iter(snapshots.values()), IndicatorSnapshot())
    tech_score = ref_snap.score

    # Rule-based is always available
    rb_result = _rule_based_result(symbol, price, snapshots, news_items, news_sentiment, metadata)

    openai_result: Optional[AnalysisResult] = None
    if Config.OPENAI_API_KEY:
        try:
            openai_result = _call_openai(symbol, price, snapshots, news_items, metadata)
            openai_result.news_sentiment = news_sentiment.get("label", "neutral")
            openai_result.news_score = news_score
            openai_result.technical_score = tech_score
            openai_result.agent = "openai"
            # Tag predictions with source
            for p in openai_result.predictions:
                p.source = "openai"
        except Exception as exc:
            logger.warning("OpenAI call failed in 'both' mode, using rule-based only: %s", exc)

    if openai_result is None:
        # Only rule-based available
        rb_result.agent = "rule-based"
        return rb_result

    # Combine predictions: average confidence, keep the direction with higher average
    combined_predictions = _combine_predictions(
        openai_result.predictions, rb_result.predictions
    )

    # Combined overall: average confidence between the two engines
    combined_conf = (openai_result.overall_confidence + rb_result.overall_confidence) // 2
    # Direction: prefer agreement; fall back to higher-confidence engine
    if openai_result.overall_direction == rb_result.overall_direction:
        combined_dir = openai_result.overall_direction
    elif openai_result.overall_confidence >= rb_result.overall_confidence:
        combined_dir = openai_result.overall_direction
    else:
        combined_dir = rb_result.overall_direction

    summary = (
        f"[ChatGPT] {openai_result.summary} "
        f"[Rule-based] {rb_result.summary}"
    )

    return AnalysisResult(
        symbol=symbol,
        current_price=price,
        predictions=combined_predictions,
        overall_direction=combined_dir,
        overall_confidence=combined_conf,
        news_sentiment=news_sentiment.get("label", "neutral"),
        news_score=news_score,
        technical_score=tech_score,
        ai_powered=True,
        agent="both",
        summary=summary,
        openai_predictions=openai_result.predictions,
        rule_based_predictions=rb_result.predictions,
    )


def _combine_predictions(
    openai_preds: list[TimeframePrediction],
    rb_preds: list[TimeframePrediction],
) -> list[TimeframePrediction]:
    """Merge two prediction lists by averaging confidence per timeframe."""
    rb_by_tf = {p.timeframe: p for p in rb_preds}
    combined = []
    for gpt_pred in openai_preds:
        rb_pred = rb_by_tf.get(gpt_pred.timeframe)
        if rb_pred is None:
            combined.append(gpt_pred)
            continue
        avg_conf = (gpt_pred.confidence + rb_pred.confidence) // 2
        # Agree on direction or pick higher-confidence
        if gpt_pred.direction == rb_pred.direction:
            direction = gpt_pred.direction
        elif gpt_pred.confidence >= rb_pred.confidence:
            direction = gpt_pred.direction
        else:
            direction = rb_pred.direction
        reasoning = f"ChatGPT: {gpt_pred.reasoning} | Rule-based: {rb_pred.reasoning}"
        combined.append(
            TimeframePrediction(
                timeframe=gpt_pred.timeframe,
                direction=direction,
                confidence=avg_conf,
                reasoning=reasoning,
                source="combined",
            )
        )
    return combined


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
