"""
News Sentiment Analyzer — analyzes news headlines with Claude Haiku, caches in Redis.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as redis
from loguru import logger

from app.ai.client import AIClient
from app.ai.prompts import get_enhanced_sentiment_prompt, get_sentiment_prompt
from app.db.models import NewsSentiment
from app.db.session import async_session


SENTIMENT_CACHE_TTL = 900  # 15 minutes


@dataclass
class SentimentResult:
    label: str = "neutral"
    score: float = 0.0
    confidence: float = 0.0
    key_factors: list[str] = field(default_factory=list)
    source_count: int = 0
    analyzed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "score": self.score,
            "confidence": self.confidence,
            "key_factors": self.key_factors,
            "source_count": self.source_count,
            "analyzed_at": self.analyzed_at,
        }


class NewsSentimentAnalyzer:
    def __init__(self, ai_client: AIClient, db_session, redis_client: redis.Redis):
        self.ai = ai_client
        self.db = db_session  # kept for backward compat (read path)
        self.redis = redis_client

    async def analyze(self, news_items: list[dict], context: dict | None = None, symbol: str = "GOLD") -> SentimentResult:
        now = datetime.now(timezone.utc).isoformat()

        if not news_items:
            return SentimentResult(analyzed_at=now)

        # Build prompt from headlines
        headlines = "\n".join(f"{i+1}. {item['title']}" for i, item in enumerate(news_items))
        user_prompt = f"Analyze these {symbol} market headlines:\n\n{headlines}"

        # Enrich with context if available
        system_prompt = get_sentiment_prompt(symbol)
        if context:
            system_prompt = get_enhanced_sentiment_prompt(symbol)
            sections = []
            if context.get("price_action"):
                sections.append(f"--- PRICE ACTION ---\n{context['price_action']}")
            if context.get("trade_patterns"):
                sections.append(f"--- TRADE HISTORY ---\n{context['trade_patterns']}")
            if context.get("historical_patterns"):
                sections.append(f"--- HISTORICAL PATTERNS ---\n{context['historical_patterns']}")
            if context.get("macro_context"):
                sections.append(f"--- MACRO DATA ---\n{context['macro_context']}")
            if sections:
                user_prompt += "\n\n" + "\n\n".join(sections)

        result = await self.ai.complete_json_async(system_prompt, user_prompt)

        if result is None:
            logger.warning("AI sentiment analysis failed, returning neutral")
            return SentimentResult(analyzed_at=now, source_count=len(news_items))

        sentiment = SentimentResult(
            label=result.get("sentiment", "neutral"),
            score=float(result.get("score", 0.0)),
            confidence=float(result.get("confidence", 0.0)),
            key_factors=result.get("key_factors", []),
            source_count=len(news_items),
            analyzed_at=now,
        )

        # Save to DB — use a fresh session to avoid shared session corruption
        try:
            async with async_session() as db:
                for item in news_items:
                    record = NewsSentiment(
                        headline=item["title"],
                        source=item.get("source", ""),
                        published_at=datetime.fromisoformat(item["published"]).replace(tzinfo=None) if item.get("published") else None,
                        sentiment_label=sentiment.label,
                        sentiment_score=sentiment.score,
                        confidence=sentiment.confidence,
                        raw_response=json.dumps(result),
                    )
                    db.add(record)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to save sentiment to DB: {e}")

        # Cache in Redis
        try:
            await self.redis.set(
                f"sentiment:latest:{symbol}",
                json.dumps(sentiment.to_dict()),
                ex=SENTIMENT_CACHE_TTL,
            )
        except Exception as e:
            logger.error(f"Failed to cache sentiment in Redis: {e}")

        return sentiment

    async def get_latest_sentiment(self, symbol: str = "GOLD") -> SentimentResult:
        # Try Redis cache first
        try:
            cached = await self.redis.get(f"sentiment:latest:{symbol}")
            if cached:
                data = json.loads(cached)
                result = SentimentResult(**data)

                # Apply time decay — sentiment loses relevance over time
                if result.analyzed_at:
                    try:
                        analyzed_at = datetime.fromisoformat(result.analyzed_at.replace("Z", "+00:00"))
                        if analyzed_at.tzinfo is None:
                            analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)
                        age_minutes = (datetime.now(timezone.utc) - analyzed_at).total_seconds() / 60
                        # 10% confidence decay per hour, floor at 50%
                        decay = max(1.0 - (age_minutes / 60) * 0.1, 0.5)
                        result.confidence *= decay
                        result.score *= decay

                        # Too old — treat as neutral
                        if result.confidence < 0.3:
                            return SentimentResult(analyzed_at=datetime.now(timezone.utc).isoformat())
                    except (ValueError, TypeError):
                        pass

                return result
        except Exception as e:
            logger.error(f"Redis cache read failed: {e}")

        # No cache — return neutral (caller should trigger analyze if needed)
        return SentimentResult(analyzed_at=datetime.now(timezone.utc).isoformat())
