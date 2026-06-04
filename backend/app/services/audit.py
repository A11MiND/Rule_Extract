from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from .. import models


REDACTED_KEYS = {
    "api_key",
    "llm_api_key",
    "mineru_api_token",
    "token",
    "password",
    "artifact_manifest",
    "mineru_artifacts",
    "content",
    "source_window",
}


def model_snapshot(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        raw = value
    else:
        raw = {
            column.key: getattr(value, column.key)
            for column in inspect(value).mapper.column_attrs
        }
    return {key: _safe_value(key, item) for key, item in raw.items()}


def record_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    summary: str,
    before: Any = None,
    after: Any = None,
    actor: str = "Demo User",
) -> models.AuditEvent:
    event = models.AuditEvent(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        summary=summary[:500],
        before_json=model_snapshot(before),
        after_json=model_snapshot(after),
    )
    db.add(event)
    return event


def _safe_value(key: str, value: Any) -> Any:
    if key.lower() in REDACTED_KEYS:
        return "[redacted]"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value if len(value) <= 500 else f"{value[:500]}…"
    if isinstance(value, list):
        return [_safe_value("", item) for item in value[:25]]
    if isinstance(value, dict):
        return {
            item_key: _safe_value(item_key, item_value)
            for item_key, item_value in list(value.items())[:25]
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)
