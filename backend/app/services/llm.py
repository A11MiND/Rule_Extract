from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import requests

from ..config import settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str = "OpenAI-compatible",
    ) -> None:
        self.api_base = (api_base or settings.llm_api_base).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.provider = provider or "OpenAI-compatible"

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("LLM API key is required for real rule extraction.")
        payload = self.build_chat_payload(system_prompt, user_prompt)
        last_error = "unknown transport error"
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=120,
                )
            except requests.RequestException as exc:
                last_error = f"network error ({type(exc).__name__})"
                if attempt < 2:
                    time.sleep((2 ** attempt) * (1.0 + random.random()))
                    continue
                raise LLMError(f"LLM request failed after 3 attempts: {last_error}") from exc

            if response.status_code >= 500:
                last_error = f"provider server error (HTTP {response.status_code})"
                if attempt < 2:
                    time.sleep((2 ** attempt) * (1.0 + random.random()))
                    continue
                raise LLMError(f"LLM request failed after 3 attempts: {last_error}")
            if response.status_code >= 400:
                raise LLMError(f"LLM request was rejected by the provider (HTTP {response.status_code}).")
            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return parse_json_content(content)
            except LLMError:
                raise
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise LLMError("LLM provider returned an invalid response payload.") from exc
        raise LLMError(f"LLM request failed after 3 attempts: {last_error}")

    def build_chat_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        return payload


DoubaoClient = LLMClient


def parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise LLMError("LLM response did not contain a JSON object.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Malformed LLM JSON: {exc}") from exc
