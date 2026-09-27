"""Gemini Flash LLM adapter for the AI copilot (Definitive Plan Phase 7).

NEVER raises — returns None on any error so callers fall back to
rule-based answers. Needs `google-generativeai` installed at runtime to
activate; import is lazy (soft optional dependency for tests).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class GeminiAdapter:
    """Thin async adapter over `google-generativeai`.

    Available when both lib AND API key are present.
    """

    def __init__(self, model_name: str | None = None, api_key: str | None = None):
        """Create adapter from env config; model resolved lazily."""
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        # gemini-2.0-flash: 1.5 models are retired for newer API keys (404 on
        # generate) — the default tracks a currently served model; override
        # with GEMINI_MODEL.
        self._model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self._model = None

    @property
    def available(self) -> bool:
        """True when a real API key is configured (library check is lazy)."""
        if not self._api_key:
            return False
        try:
            import google.generativeai  # noqa: F401

            return True
        except ImportError:
            logger.debug("google-generativeai not installed; Gemini adapter unavailable")
            return False

    def _get_model(self):
        """Lazy configured model; returns None on any failure (never raises)."""
        if self._model is not None:
            return self._model
        try:
            import google.generativeai as genai

            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
            return self._model
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini model initialization failed: %s", exc)
            return None

    async def complete(self, prompt: str) -> str | None:
        """Get a completion. Returns None on any error (never raises)."""
        import asyncio

        model = self._get_model()
        if model is None:
            return None
        try:
            response = await asyncio.to_thread(
                model.generate_content,
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 512},
            )
            return str(response.text).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini complete failed: %s", exc)
            return None
