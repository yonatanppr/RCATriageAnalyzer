"""Database setup and session helpers."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative model base."""


settings = get_settings()
engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def init_db() -> None:
    """Create all database tables."""

    from app.storage import db_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _apply_postgres_compat_migrations()


def _apply_postgres_compat_migrations() -> None:
    """Apply lightweight schema compatibility updates for local prototype upgrades."""

    if engine.dialect.name != "postgresql":
        return

    statements = [
        text("ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(255)"),
        text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(255)"),
        text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS service_version VARCHAR(128)"),
        text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS git_sha VARCHAR(128)"),
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'incidentstatus') THEN
                IF NOT EXISTS (
                  SELECT 1
                  FROM pg_enum e
                  JOIN pg_type t ON t.oid = e.enumtypid
                  WHERE t.typname = 'incidentstatus' AND e.enumlabel = 'awaiting_human_review'
                ) THEN
                  ALTER TYPE incidentstatus ADD VALUE 'awaiting_human_review';
                END IF;
                IF NOT EXISTS (
                  SELECT 1
                  FROM pg_enum e
                  JOIN pg_type t ON t.oid = e.enumtypid
                  WHERE t.typname = 'incidentstatus' AND e.enumlabel = 'mitigated'
                ) THEN
                  ALTER TYPE incidentstatus ADD VALUE 'mitigated';
                END IF;
                IF NOT EXISTS (
                  SELECT 1
                  FROM pg_enum e
                  JOIN pg_type t ON t.oid = e.enumtypid
                  WHERE t.typname = 'incidentstatus' AND e.enumlabel = 'resolved'
                ) THEN
                  ALTER TYPE incidentstatus ADD VALUE 'resolved';
                END IF;
                IF NOT EXISTS (
                  SELECT 1
                  FROM pg_enum e
                  JOIN pg_type t ON t.oid = e.enumtypid
                  WHERE t.typname = 'incidentstatus' AND e.enumlabel = 'postmortem_required'
                ) THEN
                  ALTER TYPE incidentstatus ADD VALUE 'postmortem_required';
                END IF;
              END IF;
            END$$
            """
        ),
    ]

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(stmt)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for DB session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
