"""Tests for SQLAlchemy 2.0 database engine, session factory, and get_db dependency."""

from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session

from app.database import Base, SessionLocal, engine, get_db


def test_declarative_base() -> None:
    """Verify Base is a subclass of DeclarativeBase and has valid metadata."""
    assert issubclass(Base, DeclarativeBase)
    assert hasattr(Base, "metadata")


def test_engine_connection() -> None:
    """Verify engine can connect and execute a basic query."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_session_local() -> None:
    """Verify SessionLocal instantiates a valid SQLAlchemy session."""
    session = SessionLocal()
    assert isinstance(session, Session)
    try:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        session.close()


def test_get_db_yields_and_closes() -> None:
    """Verify get_db generator yields an active session and closes it afterwards."""
    generator = get_db()
    session = next(generator)
    assert isinstance(session, Session)
    assert session.is_active

    # Closing generator should trigger the finally block
    try:
        next(generator)
    except StopIteration:
        pass

    # In SQLAlchemy, after close(), the session transaction is inactive / closed
    assert not session.is_active or session.get_transaction() is None
