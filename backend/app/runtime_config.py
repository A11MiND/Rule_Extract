from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock

from .config import settings


DEFAULT_LLM_CONCURRENCY = 8
MAX_LLM_CONCURRENCY = 20


@dataclass
class RuntimeConfig:
    mineru_api_base: str = settings.mineru_api_base
    mineru_api_token: str = ""
    mineru_model_version: str = settings.mineru_model_version
    llm_provider: str = "OpenAI-compatible"
    llm_api_base: str = settings.llm_api_base
    llm_api_key: str = ""
    llm_model: str = settings.llm_model
    llm_concurrency: int = DEFAULT_LLM_CONCURRENCY


_runtime_config = RuntimeConfig()
_lock = Lock()


def get_runtime_config() -> RuntimeConfig:
    with _lock:
        return RuntimeConfig(**asdict(_runtime_config))


def update_runtime_config(**values: object) -> RuntimeConfig:
    with _lock:
        for key, value in values.items():
            if value in (None, ""):
                continue
            if key == "llm_concurrency":
                value = clamp_concurrency(value)
            if hasattr(_runtime_config, key):
                setattr(_runtime_config, key, value)
        return RuntimeConfig(**asdict(_runtime_config))


def public_runtime_config(config: RuntimeConfig | None = None) -> dict:
    config = config or get_runtime_config()
    return {
        "mineru_api_base": config.mineru_api_base,
        "mineru_model_version": config.mineru_model_version,
        "mineru_configured": bool(config.mineru_api_token or settings.mineru_api_token),
        "llm_provider": config.llm_provider,
        "llm_api_base": config.llm_api_base,
        "llm_model": config.llm_model,
        "llm_configured": bool(config.llm_api_key or settings.llm_api_key),
        "llm_concurrency": clamp_concurrency(config.llm_concurrency),
        "max_llm_concurrency": MAX_LLM_CONCURRENCY,
    }


def effective_mineru_token(config: RuntimeConfig | None = None) -> str:
    config = config or get_runtime_config()
    return config.mineru_api_token or settings.mineru_api_token


def effective_llm_key(config: RuntimeConfig | None = None) -> str:
    config = config or get_runtime_config()
    return config.llm_api_key or settings.llm_api_key


def clamp_concurrency(value: object) -> int:
    try:
        concurrency = int(value)
    except (TypeError, ValueError):
        concurrency = DEFAULT_LLM_CONCURRENCY
    return max(1, min(MAX_LLM_CONCURRENCY, concurrency))
