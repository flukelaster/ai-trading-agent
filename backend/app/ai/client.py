"""
AI Client — wrapper for Claude Agent SDK (Max subscription).
AI is an optional layer — all calls return None on failure.
"""

import json
import re

from loguru import logger

MODEL = "claude-haiku-4-5-20251001"


class AIClient:
    """AI client using Claude Agent SDK. No API key needed — uses Max subscription."""

    async def complete_async(self, system_prompt: str, user_prompt: str, max_tokens: int = 256) -> str | None:
        try:
            from mcp_server.sdk_client import sdk_complete
            return await sdk_complete(user_prompt, system_prompt, model=MODEL)
        except Exception as e:
            logger.error(f"AI call failed: {e}")
            return None

    async def complete_json_async(self, system_prompt: str, user_prompt: str, max_tokens: int = 256) -> dict | None:
        text = await self.complete_async(system_prompt, user_prompt, max_tokens)
        if text is None:
            return None
        try:
            cleaned = text.strip()
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"AI JSON parse failed: {e}\nRaw: {text[:200]}")
            return None
