from collections.abc import Generator
from typing import Any
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool
from app.config import settings

engine_kwargs: dict[str, Any] = {}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine_kwargs["poolclass"] = StaticPool
else:
    # Serverless / Cloud PostgreSQL (Neon / PgBouncer pooler) best practices:
    # - pool_pre_ping: validates connections before checkout, recovering from scale-to-zero suspension
    # - pool_recycle: recycles idle connections before firewall/proxy dropouts
    engine_kwargs["pool_size"] = 20
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_timeout"] = 30
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300
    if "-pooler" in settings.DATABASE_URL or "neon.tech" in settings.DATABASE_URL:
        # Avoid prepared statement collision across PgBouncer transaction-pooled connections
        engine_kwargs["connect_args"] = {"prepare_threshold": None}

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for acquiring and releasing database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
