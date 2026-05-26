from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///./storage/nec4_demo.db"
    )
    storage_root: Path = Path(os.getenv("STORAGE_ROOT", "./storage")).resolve()

    llm_api_base: str = os.getenv("LLM_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "doubao-seed-2-0-pro-260215")

    mineru_api_base: str = os.getenv("MINERU_API_BASE", "https://mineru.net/api/v4")
    mineru_api_token: str = os.getenv("MINERU_API_TOKEN", "")
    mineru_model_version: str = os.getenv("MINERU_MODEL_VERSION", "vlm")
    mineru_poll_interval_seconds: int = _int_env("MINERU_POLL_INTERVAL_SECONDS", 2)
    mineru_max_poll_attempts: int = _int_env("MINERU_MAX_POLL_ATTEMPTS", 60)
    mineru_download_retry_count: int = _int_env("MINERU_DOWNLOAD_RETRY_COUNT", 3)
    mineru_download_retry_delay_seconds: int = _int_env("MINERU_DOWNLOAD_RETRY_DELAY_SECONDS", 2)


settings = Settings()
