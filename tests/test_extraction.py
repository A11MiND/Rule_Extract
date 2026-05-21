import json

from backend.app.config import settings
from backend.app.services.extraction import append_llm_window_log, llm_windows_path


def test_append_llm_window_log_writes_jsonl_with_path_storage(tmp_path):
    previous_storage_root = settings.storage_root
    object.__setattr__(settings, "storage_root", tmp_path)
    try:
        append_llm_window_log(42, {"kind": "extraction", "status": "failed", "error": "rate limit"})

        path = llm_windows_path(42)
        payload = json.loads(path.read_text(encoding="utf-8").strip())
    finally:
        object.__setattr__(settings, "storage_root", previous_storage_root)

    assert path.name == "llm_windows.jsonl"
    assert payload["kind"] == "extraction"
    assert payload["status"] == "failed"
    assert payload["error"] == "rate limit"
    assert "timestamp" in payload
