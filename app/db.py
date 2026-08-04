from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://career_os:career_os@localhost:5432/career_os"


def build_engine(database_url: str | None = None) -> Engine:
    resolved_url = database_url or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    connect_args = {"connect_timeout": 1} if resolved_url.startswith("postgresql") else {}
    return create_engine(resolved_url, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
