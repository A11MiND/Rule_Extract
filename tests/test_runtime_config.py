from __future__ import annotations

from backend.app.runtime_config import clamp_concurrency, public_runtime_config, update_runtime_config
import pytest
import requests

from backend.app.services.llm import LLMClient, LLMError
from backend.app.services.mineru import MinerUClient


def test_public_runtime_config_redacts_keys():
    config = update_runtime_config(mineru_api_token="mineru-secret", llm_api_key="llm-secret")

    public = public_runtime_config(config)

    assert public["mineru_configured"] is True
    assert public["llm_configured"] is True
    assert "mineru_api_token" not in public
    assert "llm_api_key" not in public


def test_concurrency_is_capped_at_twenty():
    assert clamp_concurrency(0) == 1
    assert clamp_concurrency(25) == 20
    assert clamp_concurrency("12") == 12


def test_llm_client_builds_openai_compatible_payload():
    client = LLMClient(api_base="https://example.com/v1", api_key="key", model="demo-model")

    payload = client.build_chat_payload("system", "user")

    assert payload["model"] == "demo-model"
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == "user"
    assert payload["response_format"] == {"type": "json_object"}


def test_mineru_submit_payload_uses_runtime_model_version():
    client = MinerUClient(api_base="https://mineru.example", token="token", model_version="vlm-test")

    assert client.build_submit_payload("https://example.com/file.pdf") == {
        "url": "https://example.com/file.pdf",
        "model_version": "vlm-test",
    }


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_llm_client_does_not_retry_client_errors(monkeypatch):
    calls = 0

    def reject(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(401)

    monkeypatch.setattr(requests, "post", reject)
    client = LLMClient(api_base="https://example.com/v1", api_key="secret", model="demo")

    with pytest.raises(LLMError, match="HTTP 401"):
        client.complete_json("system", "user")

    assert calls == 1


def test_llm_client_retries_server_errors_without_exposing_response(monkeypatch):
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(503, {"secret": "provider response body"})

    monkeypatch.setattr(requests, "post", fail)
    monkeypatch.setattr("backend.app.services.llm.time.sleep", lambda *_args: None)
    client = LLMClient(api_base="https://example.com/v1", api_key="secret", model="demo")

    with pytest.raises(LLMError) as error:
        client.complete_json("system", "user")

    assert calls == 3
    assert "provider response body" not in str(error.value)
