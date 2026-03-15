"""Database engine and session management."""
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Store the SQLite file next to this package
DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "psanalysis.db"

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # Create all tables on first access
        from models.schema import Base  # noqa: F401
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    """Return a new database session. Caller is responsible for closing it."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=True, autocommit=False)
    return _SessionLocal()


def init_db():
    """Explicitly initialise DB tables (idempotent)."""
    from models.schema import Base  # noqa: F401
    Base.metadata.create_all(get_engine())
