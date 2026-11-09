"""Database engine, session factory, and declarative Base using SQLAlchemy 2.0."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# SQLite requires check_same_thread=False for multi-threaded FastAPI access
connect_args: dict[str, Any] = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

if settings.DATABASE_URL.startswith("sqlite") and ":memory:" not in settings.DATABASE_URL:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
        """Let readers and one writer work at the same time, and wait instead of failing.

        A proposal takes minutes (the model call) while managers keep approving other
        exceptions, so the default rollback journal would raise "database is locked".
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy 2.0 ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a database session and guarantees closure upon exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
