"""Groq LLM adapter for the NexaFreight AI copilot (ultra-fast inference).

Follows the same minimal interface as GeminiAdapter and OllamaAdapter:
  adapter.available -> bool
  await adapter.complete(prompt) -> str | None

NEVER raises — returns None on any error so callers fall back cleanly to
Gemini, Ollama, or deterministic rule-based answers.
"""

from __future__ import annotations

import logging
import os
import httpx

logger = logging.getLogger(__name__)

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqAdapter:
    """Async adapter calling Groq Cloud's OpenAI-compatible completions API."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self._model = model or os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)

    @property
    def available(self) -> bool:
        """True when a non-empty API key is present."""
        return bool(self._api_key and self._api_key.strip())

    async def complete(self, prompt: str) -> str | None:
        """Get a completion from Groq. Returns None on any error (never raises)."""
        if not self.available:
            return None

        headers = {
            "Authorization": f"Bearer {self._api_key.strip()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are NexaFreight AI Copilot, an expert logistics and supply chain assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(GROQ_API_URL, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                else:
                    logger.warning("Groq API returned status %d: %s", resp.status_code, resp.text[:200])
                    return None
        except Exception as exc:
            logger.warning("Groq completion failed: %s", exc)
            return None

        return None

