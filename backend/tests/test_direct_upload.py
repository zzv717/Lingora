"""Direct upload reservation and finalization with a fake storage service."""
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core.config import settings
from app.db.mixins import utcnow
from app.models import Book, ProcessingJob
from app.services.storage import SupabaseStorage
from tests.conftest import make_user, auth_headers
from tests.pdf_factory import make_sample_book

class FakeSupabase(SupabaseStorage):
    def __init__(self):
        self.objects = {}
        self.signed = []
    def require_private_upload_limit(self):
        pass
    def create_signed_upload(self, path):
        self.signed.append(path)
        return "upload-token"
    def read_limited(self, path, max_bytes):
        from app.core.errors import ApiError
        if path not in self.objects:
            raise ApiError("FILE_NOT_FOUND", "Fayl topilmadi", 404)
        content = self.objects[path]
        if len(content) > max_bytes:
            raise ApiError("FILE_TOO_LARGE", "Fayl juda katta", 413)
        return content
    def read(self, path):
        return self.objects[path]
    def delete(self, path):
        self.objects.pop(path, None)

@pytest.fixture
def direct(monkeypatch):
    import app.api.v1.books as books
    fake = FakeSupabase()
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_direct_upload_enabled", True)
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_publishable_key", "sb_publishable_example")
    monkeypatch.setattr(settings, "supabase_service_key", "sb_secret_private")
    monkeypatch.setattr(settings, "upload_max_mb", 50)
    monkeypatch.setattr(books, "get_storage", lambda: fake)
    monkeypatch.setattr(books, "enqueue_book_analysis", lambda *_: None)
    return fake

def headers(client, email):
    return auth_headers(make_user(client, email)["access_token"])

def prepare(client, auth, size, **kw):
    return client.post("/api/v1/books/upload/prepare", headers=auth,
                       json={"filename": "sample.pdf", "title": "Test", "size_bytes": size,
                             "consent": True, **kw})

def test_direct_upload_complete_and_ownership(client, db, direct):
    owner = headers(client, "owner@example.com")
    other = headers(client, "other@example.com")
    pdf = make_sample_book()
    r = prepare(client, owner, len(pdf))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["direct"] and data["token"] == "upload-token"
    assert data["public_key"] == "sb_publishable_example"
    assert "sb_secret_private" not in r.text
    assert data["path"] == direct.signed[0]
    assert client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=other).status_code == 404
    assert client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner).status_code == 404
    direct.objects[data["path"]] = pdf
    done = client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "processing"
    assert done.json()["page_count"] == 6
    assert client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner).status_code == 200
    assert len(db.scalars(select(ProcessingJob)).all()) == 1

def test_upload_validation_and_expiry(client, db, direct):
    owner = headers(client, "validation@example.com")
    assert prepare(client, owner, 50 * 1024 * 1024 + 1).status_code == 413
    assert prepare(client, owner, 100, consent=False).status_code == 400
    assert prepare(client, owner, 100, filename="not.pdf.exe").status_code == 415
    r = prepare(client, owner, 200)
    data = r.json()
    direct.objects[data["path"]] = b"x" * 200
    assert client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner).status_code == 415
    assert client.delete(f"/api/v1/books/{data['book_id']}", headers=owner).status_code == 409
    book = db.get(Book, data["book_id"])
    book.created_at = utcnow() - timedelta(hours=3)
    db.commit()
    assert client.delete(f"/api/v1/books/{data['book_id']}", headers=owner).status_code == 200
    assert data["path"] not in direct.objects

def test_actual_just_under_50_mib(client, direct):
    owner = headers(client, "large@example.com")
    pdf = make_sample_book()
    content = pdf + b" " * (50 * 1024 * 1024 - len(pdf) - 1)
    r = prepare(client, owner, len(content))
    assert r.status_code == 200, r.text
    data = r.json()
    direct.objects[data["path"]] = content
    r = client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner)
    assert r.status_code == 200, r.text
    assert r.json()["file_size_bytes"] == len(content)

def test_dont_expose_service_key(client, monkeypatch, direct):
    owner = headers(client, "keys@example.com")
    monkeypatch.setattr(settings, "supabase_publishable_key", "sb_secret_private")
    r = prepare(client, owner, 100)
    assert r.status_code == 503
    assert "sb_secret_private" not in r.text
    assert direct.signed == []


def test_near_50_mib_analysis_end_to_end_locally(client, direct, monkeypatch):
    import app.api.v1.books as books
    import app.services.pipeline as pipeline
    from app.services.tasks import _run_pipeline_job
    monkeypatch.setattr(books, "enqueue_book_analysis", _run_pipeline_job)
    monkeypatch.setattr(pipeline, "get_storage", lambda: direct)
    owner = headers(client, "fullflow@example.com")
    pdf = make_sample_book()
    content = pdf + b" " * (49 * 1024 * 1024 - len(pdf))
    start = prepare(client, owner, len(content))
    assert start.status_code == 200, start.text
    data = start.json()
    direct.objects[data["path"]] = content
    complete = client.post(f"/api/v1/books/upload/{data['book_id']}/complete", headers=owner)
    assert complete.status_code == 200, complete.text
    job = client.get(f"/api/v1/books/{data['book_id']}/status", headers=owner).json()
    assert job["status"] == "completed", job
    book = client.get(f"/api/v1/books/{data['book_id']}", headers=owner).json()
    assert book["status"] == "ready" and book["page_count"] == 6


def test_pending_cannot_be_downloaded_or_reanalysed(client, direct):
    owner = headers(client, "pending@example.com")
    data = prepare(client, owner, 100).json()
    book_id = data["book_id"]
    assert client.get(f"/api/v1/books/{book_id}/file", headers=owner).status_code == 409
    assert client.post(f"/api/v1/books/{book_id}/reanalyze", headers=owner).status_code == 409
    assert client.delete("/api/v1/auth/account", headers=owner).status_code == 409


def test_bucket_limit_and_signing_protocol(monkeypatch):
    import httpx
    from app.core.errors import ApiError
    monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_key", "server-secret")
    monkeypatch.setattr(settings, "supabase_storage_bucket", "private-books")
    monkeypatch.setattr(settings, "upload_max_mb", 50)
    seen = []
    def get(url, headers, timeout):
        seen.append((url, headers))
        return httpx.Response(200, json={"public": False, "file_size_limit": 50 * 1024 * 1024}, request=httpx.Request("GET", url))
    def post(url, headers, json, timeout):
        seen.append((url, headers))
        return httpx.Response(200, json={"url": "/object/upload/sign/private-books/a.pdf?token=abc.def"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    storage = SupabaseStorage()
    storage.require_private_upload_limit()
    assert storage.create_signed_upload("a.pdf") == "abc.def"
    assert seen[0][0] == "https://example.supabase.co/storage/v1/bucket/private-books"
    assert seen[1][0] == "https://example.supabase.co/storage/v1/object/upload/sign/private-books/a.pdf"
    assert all(item[1]["apikey"] == "server-secret" for item in seen)
    def bad_get(url, headers, timeout):
        return httpx.Response(200, json={"public": False, "file_size_limit": None}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", bad_get)
    with pytest.raises(ApiError) as err:
        storage.require_private_upload_limit()
    assert err.value.code == "UPLOAD_BUCKET_LIMIT"


def test_feature_off_uses_original_upload(client, monkeypatch):
    owner = headers(client, "featureoff@example.com")
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_direct_upload_enabled", False)
    assert prepare(client, owner, 100).json() == {"direct": False}
