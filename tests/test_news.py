"""Tests for bot/news.py (sentiment scoring, aggregation)."""

import pytest

from bot.news import _score_text, get_aggregate_sentiment, score_to_label


class TestScoreText:
    def test_bullish_keywords(self):
        score = _score_text("Bitcoin surges to new record high bullish rally")
        assert score > 0

    def test_bearish_keywords(self):
        score = _score_text("Bitcoin crash dump bear sell warning risk")
        assert score < 0

    def test_neutral_text(self):
        score = _score_text("Bitcoin traded sideways today")
        assert score == 0

    def test_mixed_text(self):
        """Both bullish and bearish words cancel out partially."""
        score = _score_text("rally but crash later")
        # one bullish ('rally'), one bearish ('crash') → 0
        assert score == 0

    def test_empty_string(self):
        assert _score_text("") == 0

    def test_punctuation_stripped(self):
        """Punctuation around keywords should not prevent matching."""
        score = _score_text("surge!")
        assert score > 0


class TestScoreToLabel:
    def test_positive_is_bullish(self):
        assert score_to_label(3) == "bullish"

    def test_negative_is_bearish(self):
        assert score_to_label(-2) == "bearish"

    def test_zero_is_neutral(self):
        assert score_to_label(0) == "neutral"


class TestGetAggregateSentiment:
    def _make_articles(self, sentiments: list[str]) -> list[dict]:
        mapping = {"bullish": 2, "bearish": -2, "neutral": 0}
        return [
            {"sentiment": s, "sentiment_score": mapping[s]}
            for s in sentiments
        ]

    def test_empty_list(self):
        result = get_aggregate_sentiment([])
        assert result["label"] == "neutral"
        assert result["score"] == 0

    def test_all_bullish(self):
        articles = self._make_articles(["bullish"] * 5)
        result = get_aggregate_sentiment(articles)
        assert result["label"] == "bullish"
        assert result["bullish"] == 5
        assert result["bearish"] == 0

    def test_all_bearish(self):
        articles = self._make_articles(["bearish"] * 4)
        result = get_aggregate_sentiment(articles)
        assert result["label"] == "bearish"

    def test_mixed(self):
        articles = self._make_articles(["bullish", "bearish", "neutral"])
        result = get_aggregate_sentiment(articles)
        assert result["bullish"] == 1
        assert result["bearish"] == 1
        assert result["neutral"] == 1

    def test_counts_sum_to_total(self):
        articles = self._make_articles(["bullish", "bearish", "neutral", "bullish"])
        result = get_aggregate_sentiment(articles)
        total = result["bullish"] + result["bearish"] + result["neutral"]
        assert total == len(articles)
