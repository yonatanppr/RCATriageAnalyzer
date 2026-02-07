import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_iats.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/9")
os.environ.setdefault("FIXTURE_MODE", "true")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("REPO_BASE_PATH", str(Path(__file__).resolve().parents[2] / "repos"))
os.environ.setdefault("LLM_PROVIDER", "local")

from app.config import get_settings  # noqa: E402
from app.storage.database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def pytest_sessionstart(session):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def pytest_sessionfinish(session, exitstatus):
    db_file = Path("test_iats.db")
    if db_file.exists():
        db_file.unlink()
