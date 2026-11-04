"""Klien LLM. Semua panggilan LLM di pipeline lewat modul ini.

LLM_PROVIDER:
  mock               jawaban dari fixture data sintetis (tanpa API key, untuk tes dan demo)
  deepseek           API DeepSeek (kompatibel OpenAI). Butuh LLM_API_KEY.
  openai_compatible  server lain yang kompatibel OpenAI. Butuh LLM_BASE_URL, LLM_MODEL, LLM_API_KEY.

API key hanya dibaca dari variabel lingkungan (.env), tidak pernah ditulis ke log.
Catatan: sebelum pilot dengan data nyata, cek ulang lokasi pemrosesan data penyedia LLM.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model_version: str

    def complete_json(self, system: str, user: str, *, task: str, context: dict[str, Any]) -> str:
        """Kembalikan teks jawaban (diharapkan JSON). `task` dan `context` dipakai mode mock."""


class OpenAICompatibleClient:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 120.0, max_retries: int = 2):
        if not api_key:
            raise LLMError("LLM_API_KEY belum diisi di .env")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.model_version = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries

    def complete_json(self, system: str, user: str, *, task: str, context: dict[str, Any]) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self._timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise LLMError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                self.model_version = data.get("model") or self.model
                return data["choices"][0]["message"]["content"] or ""
            except (httpx.HTTPError, LLMError, KeyError, ValueError) as exc:
                last_error = exc
                log.warning("Panggilan LLM gagal (%s), percobaan %s", type(exc).__name__, attempt + 1)
                time.sleep(2**attempt)
        raise LLMError(f"LLM tidak bisa dihubungi: {last_error}")


PROVIDER_DEFAULTS = {
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}


def get_llm_client() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider == "mock":
        from mab_pipeline.llm.mock import MockLLMClient

        return MockLLMClient()
    base_default, model_default = PROVIDER_DEFAULTS.get(provider, ("", ""))
    base_url = os.getenv("LLM_BASE_URL") or base_default
    model = os.getenv("LLM_MODEL") or model_default
    if provider not in ("deepseek", "openai_compatible") or not base_url or not model:
        raise LLMError(f"LLM_PROVIDER '{provider}' tidak dikenal atau LLM_BASE_URL/LLM_MODEL kosong")
    return OpenAICompatibleClient(base_url, model, os.getenv("LLM_API_KEY", ""))


def parse_json(text: str) -> Any:
    """Parse JSON, toleran terhadap pagar ```json ... ```."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned)
