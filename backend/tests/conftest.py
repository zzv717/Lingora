"""Shared test fixtures: isolated DB, rate-limit off, TestClient, sample PDF factory."""
import os
import pathlib

# Test env BEFORE importing app modules
BACKEND_DIR = pathlib.Path(__file__).resolve().parent.parent
TEST_DB = BACKEND_DIR / "data" / "test_lingora.db"
TEST_STORAGE = BACKEND_DIR / "data" / "test_storage"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["STORAGE_DIR"] = str(TEST_STORAGE)
os.environ["AI_PROVIDER"] = "none"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ["ENV"] = "test"
os.environ["FREE_MAX_BOOKS"] = "10"
os.environ["UPLOAD_MAX_MB"] = "20"

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

if TEST_DB.exists():
    TEST_DB.unlink()
if TEST_STORAGE.exists():
    shutil.rmtree(TEST_STORAGE, ignore_errors=True)

import app.core.rate_limit as rate_limit_module  # noqa: E402
import app.main as main_module  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402
import app.services.tasks as tasks_module  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db_setup():
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db():
    yield
    # wipe all data between tests for isolation
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(rate_limit_module, "check_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "check_rate_limit", lambda *a, **k: None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


AUTH = "/api/v1/auth"


def make_user(client: TestClient, email: str, password: str = "Parol12345", name: str = "Test") -> dict:
    r = client.post(f"{AUTH}/register", json={"email": email, "password": password, "full_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def wait_for_book(client: TestClient, headers: dict, book_id: str, timeout: float = 60.0) -> dict:
    import time

    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = client.get(f"/api/v1/books/{book_id}/status", headers=headers)
        last = r.json()
        if last and last.get("status") in ("completed", "failed"):
            return last
        time.sleep(0.4)
    raise AssertionError(f"Book processing timed out; last job={last}")
