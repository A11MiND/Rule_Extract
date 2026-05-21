from backend.app.runtime_config import clamp_concurrency, public_runtime_config, update_runtime_config
from backend.app.services.llm import LLMClient
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
