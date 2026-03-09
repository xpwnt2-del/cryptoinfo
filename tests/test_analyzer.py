"""Tests for bot/analyzer.py (rule-based path, no OpenAI required)."""

import pytest

from bot.analyzer import (
    AGENTS,
    TIMEFRAMES,
    AnalysisResult,
    TimeframePrediction,
    _blend_score,
    _confidence_from_score,
    _direction_from_score,
    _rule_based_prediction,
    analyse,
)
from bot.technical import IndicatorSnapshot


# ── helpers ───────────────────────────────────────────────────────────────────

def make_snap(score: int = 0) -> IndicatorSnapshot:
    snap = IndicatorSnapshot()
    snap.score = score
    snap.rsi = 50
    snap.rsi_signal = "neutral"
    snap.macd_signal = "neutral"
    snap.ma_signal = "neutral"
    return snap


# ── _direction_from_score ─────────────────────────────────────────────────────

class TestDirectionFromScore:
    def test_bullish(self):
        assert _direction_from_score(50) == "bullish"

    def test_bearish(self):
        assert _direction_from_score(-50) == "bearish"

    def test_neutral_zero(self):
        assert _direction_from_score(0) == "neutral"

    def test_boundary_just_bullish(self):
        assert _direction_from_score(15) == "bullish"

    def test_boundary_just_bearish(self):
        assert _direction_from_score(-15) == "bearish"


# ── _confidence_from_score ────────────────────────────────────────────────────

class TestConfidenceFromScore:
    def test_zero_score(self):
        assert _confidence_from_score(0) == 0

    def test_max(self):
        assert _confidence_from_score(100) == 100

    def test_clamp_above_100(self):
        assert _confidence_from_score(200) == 100

    def test_negative_score(self):
        assert _confidence_from_score(-60) == 60


# ── _blend_score ──────────────────────────────────────────────────────────────

class TestBlendScore:
    def test_1h_mostly_technical(self):
        # For 1h, tech weight = 0.85; news_score = 0 shouldn't affect much
        blended = _blend_score(60, 0, "1h")
        assert blended > 40  # mostly technical

    def test_1w_mostly_news(self):
        # For 1w, news weight = 0.70; strong positive news should dominate
        blended = _blend_score(0, 4.0, "1w")
        assert blended > 30

    def test_clamped(self):
        blended = _blend_score(200, 10, "1h")
        assert blended <= 100
        blended2 = _blend_score(-200, -10, "1h")
        assert blended2 >= -100


# ── _rule_based_prediction ────────────────────────────────────────────────────

class TestRuleBasedPrediction:
    def test_returns_timeframe_prediction(self):
        snap = make_snap(50)
        pred = _rule_based_prediction("1h", snap, news_score=1.0)
        assert isinstance(pred, TimeframePrediction)

    def test_timeframe_preserved(self):
        for tf in TIMEFRAMES:
            pred = _rule_based_prediction(tf, make_snap(30), 0)
            assert pred.timeframe == tf

    def test_bullish_snap_bullish_pred(self):
        pred = _rule_based_prediction("1h", make_snap(80), news_score=2.0)
        assert pred.direction == "bullish"
        assert pred.confidence > 0

    def test_bearish_snap_bearish_pred(self):
        pred = _rule_based_prediction("1h", make_snap(-80), news_score=-2.0)
        assert pred.direction == "bearish"

    def test_confidence_0_to_100(self):
        for score in (-100, -50, 0, 50, 100):
            pred = _rule_based_prediction("4h", make_snap(score), 0)
            assert 0 <= pred.confidence <= 100


# ── analyse (integration) ─────────────────────────────────────────────────────

class TestAnalyse:
    def _run(self, score=40, news_score=1.5):
        snap = make_snap(score)
        snapshots = {"1h": snap, "4h": snap}
        news = [
            {"sentiment": "bullish", "sentiment_score": 2},
            {"sentiment": "neutral", "sentiment_score": 0},
        ]
        sentiment = {"label": "bullish", "score": news_score}
        return analyse("BTC", 50000.0, snapshots, news, sentiment, {})

    def test_returns_analysis_result(self):
        result = self._run()
        assert isinstance(result, AnalysisResult)

    def test_symbol_preserved(self):
        result = self._run()
        assert result.symbol == "BTC"

    def test_price_preserved(self):
        result = self._run()
        assert result.current_price == 50000.0

    def test_predictions_cover_all_timeframes(self):
        result = self._run()
        tfs = {p.timeframe for p in result.predictions}
        for tf in TIMEFRAMES:
            assert tf in tfs

    def test_overall_direction_valid(self):
        result = self._run()
        assert result.overall_direction in ("bullish", "bearish", "neutral")

    def test_overall_confidence_range(self):
        result = self._run()
        assert 0 <= result.overall_confidence <= 100

    def test_bullish_snap_overall_bullish(self):
        result = self._run(score=80, news_score=2.0)
        assert result.overall_direction == "bullish"

    def test_bearish_snap_overall_bearish(self):
        result = self._run(score=-80, news_score=-2.0)
        assert result.overall_direction == "bearish"

    def test_no_openai_key_uses_rule_based(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run()
        assert result.ai_powered is False


# ── agent parameter ──────────────────────────────────────────────────────────

class TestAnalyseAgent:
    def _run(self, agent="auto", score=40, news_score=1.5):
        snap = make_snap(score)
        snapshots = {"1h": snap, "4h": snap}
        news = [{"sentiment": "bullish", "sentiment_score": 2}]
        sentiment = {"label": "bullish", "score": news_score}
        return analyse("BTC", 50000.0, snapshots, news, sentiment, {}, agent=agent)

    def test_rule_based_agent_returns_rule_based(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "sk-fake")
        result = self._run(agent="rule-based")
        assert result.ai_powered is False
        assert result.agent == "rule-based"

    def test_rule_based_agent_has_rule_based_predictions(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "sk-fake")
        result = self._run(agent="rule-based")
        for p in result.predictions:
            assert p.source == "rule-based"

    def test_auto_without_key_uses_rule_based(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="auto")
        assert result.agent == "rule-based"
        assert result.ai_powered is False

    def test_unknown_agent_treated_as_auto(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="invalid-agent")
        assert isinstance(result, AnalysisResult)

    def test_both_without_openai_key_returns_rule_based(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="both")
        # Gracefully degrades to rule-based
        assert isinstance(result, AnalysisResult)
        assert result.agent == "rule-based"
        assert result.ai_powered is False

    def test_both_without_openai_has_rule_based_predictions(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="both")
        assert len(result.predictions) > 0

    def test_agents_constant_contains_valid_values(self):
        assert "auto" in AGENTS
        assert "openai" in AGENTS
        assert "rule-based" in AGENTS
        assert "both" in AGENTS

    def test_result_has_agent_field(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="rule-based")
        assert hasattr(result, "agent")

    def test_result_has_openai_and_rule_based_preds_fields(self, monkeypatch):
        monkeypatch.setattr("bot.analyzer.Config.OPENAI_API_KEY", "")
        result = self._run(agent="both")
        assert hasattr(result, "openai_predictions")
        assert hasattr(result, "rule_based_predictions")
