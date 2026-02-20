import logging
import time

import requests

from agent.models import NewsSentiment, SentimentClass

logger = logging.getLogger(__name__)


def classify_sentiment(score: float) -> SentimentClass:
    if score > 0.35:
        return SentimentClass.BULLISH
    elif score < -0.15:
        return SentimentClass.BEARISH
    return SentimentClass.NEUTRAL


class NewsSentinelAlphaVantage:
    """Fetch news sentiment from Alpha Vantage."""

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._request_count = 0

    def get_sentiment(self, ticker: str) -> NewsSentiment | None:
        if self._request_count >= 25:
            logger.warning("Alpha Vantage daily quota reached (25 requests)")
            return None

        try:
            resp = requests.get(
                self.BASE_URL,
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": ticker,
                    "apikey": self.api_key,
                },
                timeout=15,
            )
            self._request_count += 1
            data = resp.json()

            if "feed" not in data:
                logger.warning("No news feed for %s: %s", ticker, data.get("Note", ""))
                return None

            articles = data["feed"]
            sentiments = []
            for article in articles:
                for ts in article.get("ticker_sentiment", []):
                    if ts["ticker"].upper() == ticker.upper():
                        sentiments.append(float(ts["ticker_sentiment_score"]))

            if not sentiments:
                return NewsSentiment(
                    ticker=ticker,
                    mean_score=0,
                    classification=SentimentClass.NEUTRAL,
                    article_count=len(articles),
                    top_headline=articles[0]["title"] if articles else "",
                    source="alphavantage",
                )

            mean_score = sum(sentiments) / len(sentiments)
            return NewsSentiment(
                ticker=ticker,
                mean_score=round(mean_score, 4),
                classification=classify_sentiment(mean_score),
                article_count=len(articles),
                top_headline=articles[0]["title"] if articles else "",
                source="alphavantage",
            )
        except Exception as e:
            logger.error("Alpha Vantage error for %s: %s", ticker, e)
            return None


class NewsSentinelFinnhub:
    """Fallback news sentiment from Finnhub."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_sentiment(self, ticker: str) -> NewsSentiment | None:
        try:
            from datetime import datetime, timedelta

            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

            resp = requests.get(
                f"{self.BASE_URL}/company-news",
                params={
                    "symbol": ticker,
                    "from": from_date,
                    "to": to_date,
                    "token": self.api_key,
                },
                timeout=15,
            )
            articles = resp.json()

            if not isinstance(articles, list) or not articles:
                return None

            # Finnhub doesn't provide sentiment scores, so we use a neutral estimate
            # based on article volume (more articles = more attention = slight positive bias)
            article_count = len(articles)
            estimated_score = min(0.1 * (article_count / 10), 0.3)

            return NewsSentiment(
                ticker=ticker,
                mean_score=round(estimated_score, 4),
                classification=classify_sentiment(estimated_score),
                article_count=article_count,
                top_headline=articles[0].get("headline", "") if articles else "",
                source="finnhub",
            )
        except Exception as e:
            logger.error("Finnhub error for %s: %s", ticker, e)
            return None


class NewsSentinel:
    """Aggregates news sentiment from multiple sources."""

    def __init__(self, alpha_vantage_key: str = "", finnhub_key: str = ""):
        self.av = NewsSentinelAlphaVantage(alpha_vantage_key) if alpha_vantage_key else None
        self.fh = NewsSentinelFinnhub(finnhub_key) if finnhub_key else None

    def get_sentiment(self, ticker: str) -> NewsSentiment | None:
        # Try Alpha Vantage first
        if self.av:
            result = self.av.get_sentiment(ticker)
            if result:
                return result

        # Fallback to Finnhub
        if self.fh:
            result = self.fh.get_sentiment(ticker)
            if result:
                return result

        logger.warning("No sentiment data available for %s", ticker)
        return None

    def get_sentiments(
        self, tickers: list[str], max_tickers: int = 15
    ) -> dict[str, NewsSentiment]:
        """Fetch sentiment for multiple tickers with rate limiting."""
        results = {}
        for ticker in tickers[:max_tickers]:
            result = self.get_sentiment(ticker)
            if result:
                results[ticker] = result
            time.sleep(0.5)  # Rate limiting
        return results
