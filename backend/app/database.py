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
