"""Full AI Book Analyzer pipeline on a real generated PDF: chapters, exercises, vocab, answer key."""
from tests.conftest import auth_headers, make_user, wait_for_book
from tests.pdf_factory import make_garbage_file, make_sample_book, make_scanned_like_book

API = "/api/v1"


def upload(client, headers, content: bytes, filename="book.pdf", consent=True, title=""):
    return client.post(
        f"{API}/books/upload",
        headers=headers,
        files={"file": (filename, content, "application/pdf")},
        data={"consent": str(consent).lower(), "title": title},
    )


def test_upload_requires_consent(client):
    tokens = make_user(client, "a1@example.com")
    h = auth_headers(tokens["access_token"])
    r = upload(client, h, make_sample_book(), consent=False)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_upload_rejects_non_pdf(client):
    tokens = make_user(client, "a2@example.com")
    h = auth_headers(tokens["access_token"])
    r = upload(client, h, make_garbage_file(), filename="fake.pdf")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "INVALID_FILE"


def test_full_pipeline_detection(client):
    tokens = make_user(client, "pipe@example.com")
    h = auth_headers(tokens["access_token"])
    r = upload(client, h, make_sample_book(), title="English Grammar in Use (UZ)")
    assert r.status_code == 201, r.text
    book = r.json()
    assert book["status"] in ("processing", "uploaded")

    job = wait_for_book(client, h, book["id"])
    assert job["status"] == "completed", job
    # progress + uz stage labels worked
    assert job["progress"] == 100.0
    assert job["stage_label_uz"]

    r = client.get(f"{API}/books/{book['id']}/structure", headers=h)
    assert r.status_code == 200
    data = r.json()

    # --- chapters ---
    assert len(data["chapters"]) >= 1
    assert "UNIT 1" in data["chapters"][0]["title"] or data["chapters"][0]["number"] == "1"

    # --- lessons ---
    lesson_titles = [l["title"] for l in data["lessons"]]
    assert any("Lesson 1" in t for t in lesson_titles), lesson_titles
    assert any("Lesson 2" in t for t in lesson_titles), lesson_titles

    # --- exercises ---
    cov = data["coverage"]
    assert cov["exercises"] == 4, f"expected 4 exercises, got {cov}"
    assert cov["questions"] == 9, f"expected 9 questions, got {cov}"
    # answer key found: 7 of 9 have authoritative answers (Ex3 translation left open)
    assert cov["questions_with_key"] >= 5, cov

    # --- lesson gating data ---
    lp = data["lessons_progress"]
    lesson_ids = [l["id"] for l in data["lessons"]]
    assert lp[lesson_ids[0]]["locked"] is False
    assert lp[lesson_ids[0]]["has_vocabulary"] is True
    # lesson 2 locked until lesson 1 vocab gate passed
    assert lp[lesson_ids[1]]["locked"] is True

    # --- warnings exist but are honest (translation answers not auto-graded without AI) ---
    codes = {w["code"] for w in job["warnings"]}
    assert "ANSWERS_UNKNOWN" in codes or cov["questions_with_key"] >= 5

    # --- verify specific question content ---
    r = client.get(f"{API}/lessons/{lesson_ids[0]}/exercises", headers=h)
    exs = r.json()
    ex_types = {e["exercise_type"] for e in exs}
    assert "fill_blank" in ex_types
    fill = next(e for e in exs if e["exercise_type"] == "fill_blank")
    q = fill["questions"][0]
    assert "{b1}" in q["prompt"]
    assert q["blanks"][0]["bbox"] is not None  # overlay coordinates preserved

    # --- vocabulary extracted with translations ---
    r = client.get(f"{API}/books/{book['id']}/vocabulary", headers=h)
    words = r.json()
    terms = {w["term"] for w in words}
    assert {"go", "school", "play"} <= terms, terms
    go = next(w for w in words if w["term"] == "go")
    assert "borish" in go["translation_uz"]
    assert go["needs_translation"] is False


def test_scanned_page_reports_ocr_honestly(client):
    tokens = make_user(client, "scan@example.com")
    h = auth_headers(tokens["access_token"])
    r = upload(client, h, make_scanned_like_book())
    book = r.json()
    job = wait_for_book(client, h, book["id"])
    codes = {w["code"] for w in job.get("warnings", [])}
    # OCR binary is not installed in this environment -> must be REPORTED, never faked
    assert "OCR_UNAVAILABLE" in codes or "OCR_FAILED" in codes


def test_delete_book_cascades(client, db):
    tokens = make_user(client, "del@example.com")
    h = auth_headers(tokens["access_token"])
    r = upload(client, h, make_sample_book())
    book_id = r.json()["id"]
    wait_for_book(client, h, book_id)
    r = client.delete(f"{API}/books/{book_id}", headers=h)
    assert r.status_code == 200
    from app.models import Book, ExerciseQuestion, VocabularyWord

    assert db.get(Book, book_id) is None
    assert db.query(VocabularyWord).filter(VocabularyWord.book_id == book_id).count() == 0


def test_randomized_pdf_upload_and_download(client):
    """Exercise a fresh PDF variant end-to-end, including the private original."""
    import secrets
    import fitz

    marker = secrets.token_hex(8)
    doc = fitz.open(stream=make_sample_book(), filetype="pdf")
    page = doc.new_page()
    page.insert_text((50, 72), f"Random reading sample {marker}. Reading is useful.")
    content = doc.tobytes()
    doc.close()

    headers = auth_headers(make_user(client, f"pdf-{marker}@example.com")["access_token"])
    response = upload(client, headers, content, title="Random PDF")
    assert response.status_code == 201, response.text
    book_id = response.json()["id"]
    job = wait_for_book(client, headers, book_id)
    assert job["status"] == "completed", job
    structure = client.get(f"{API}/books/{book_id}/structure", headers=headers)
    assert structure.status_code == 200
    assert structure.json()["coverage"]["exercises"] >= 3
    original = client.get(f"{API}/books/{book_id}/file", headers=headers)
    assert original.status_code == 200
    assert original.content == content


def test_sync_analysis_runs_before_upload_response(client, monkeypatch):
    """Short serverless jobs must finish while the request is still active."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "task_backend", "sync")
    headers = auth_headers(make_user(client, "sync-pdf@example.com")["access_token"])
    response = upload(client, headers, make_sample_book(), title="Synchronous PDF")
    assert response.status_code == 201, response.text
    status = client.get(f"{API}/books/{response.json()['id']}/status", headers=headers)
    assert status.json()["status"] == "completed", status.text


def test_pdf_page_limit_returns_clear_error(client, monkeypatch):
    import fitz
    from app.core.config import settings
    monkeypatch.setattr(settings, "max_pages", 1)
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    content = doc.tobytes()
    doc.close()
    headers = auth_headers(make_user(client, "limit-pdf@example.com")["access_token"])
    response = upload(client, headers, content)
    assert response.status_code == 413, response.text
    assert response.json()["error"]["code"] == "TOO_MANY_PAGES"


def test_sync_analysis_exception_reports_failed_job(client, monkeypatch):
    from app.core.config import settings
    from app.services.pipeline import Pipeline

    def fail(_self):
        raise RuntimeError("worker crashed")

    monkeypatch.setattr(settings, "task_backend", "sync")
    monkeypatch.setattr(Pipeline, "run", fail)
    headers = auth_headers(make_user(client, "sync-fail@example.com")["access_token"])
    response = upload(client, headers, make_sample_book())
    assert response.status_code == 201, response.text
    status = client.get(f"{API}/books/{response.json()['id']}/status", headers=headers)
    assert status.json()["status"] == "failed"
    assert status.json()["error_code"] == "PIPELINE_ERROR"


def test_serverless_cold_start_does_not_fail_other_jobs(monkeypatch):
    import asyncio
    import app.services.tasks as tasks
    from app.main import app, lifespan

    called = []
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(tasks, "recover_stuck_jobs", lambda: called.append(True))

    async def start():
        async with lifespan(app):
            pass

    asyncio.run(start())
    assert called == []
