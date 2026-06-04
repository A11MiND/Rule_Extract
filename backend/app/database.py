from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_connect_args: dict = {}
_kwargs: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    _kwargs["pool_pre_ping"] = True

engine = create_engine(settings.database_url, connect_args=_connect_args, **_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Keep the local demo database forward-compatible without destroying extracted data.
    if settings.database_url.startswith("sqlite"):
        import sqlite3
        db_path = settings.database_url.replace("sqlite:///", "")
        try:
            conn = sqlite3.connect(db_path)
            upgrades = {
                "documents": {
                    "grouping_level": "INTEGER NOT NULL DEFAULT 2",
                },
                "sections": {
                    "page_range": "VARCHAR(64)",
                    "coordinates": "JSON NOT NULL DEFAULT '[]'",
                },
                "rules": {
                    "severity": "VARCHAR(32) NOT NULL DEFAULT 'recommended'",
                    "applicability": "JSON NOT NULL DEFAULT '{}'",
                    "evidence_requirements": "JSON NOT NULL DEFAULT '[]'",
                    "validation_method": "VARCHAR(32) NOT NULL DEFAULT 'llm_judgement'",
                    "references": "JSON NOT NULL DEFAULT '[]'",
                    "mapping_status": "VARCHAR(32) NOT NULL DEFAULT 'unmapped'",
                },
                "source_documents": {
                    "slot_id": "TEXT",
                    "description": "TEXT NOT NULL DEFAULT ''",
                    "text_review_status": "VARCHAR(32) NOT NULL DEFAULT 'pending'",
                    "text_verified_at": "DATETIME",
                    "content_fingerprint": "TEXT NOT NULL DEFAULT ''",
                },
                "template_fields": {
                    "part_ref": "TEXT NOT NULL DEFAULT ''",
                    "filled_by": "VARCHAR(64) NOT NULL DEFAULT 'unknown'",
                    "confidence": "FLOAT NOT NULL DEFAULT 0.0",
                    "rationale": "TEXT NOT NULL DEFAULT ''",
                    "source_window": "JSON NOT NULL DEFAULT '{}'",
                    "check_intent": "TEXT NOT NULL DEFAULT ''",
                    "structured_schema": "JSON NOT NULL DEFAULT '{}'",
                    "normalization": "JSON NOT NULL DEFAULT '{}'",
                    "evidence_locator": "JSON NOT NULL DEFAULT '{}'",
                },
            }
            for table, columns in upgrades.items():
                existing = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
                for name, definition in columns.items():
                    if existing and name not in existing:
                        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
            conn.commit()
            conn.close()
        except Exception:
            pass
