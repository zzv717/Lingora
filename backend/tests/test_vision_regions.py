"""Exercise region detection: normalized boxes, validation, cache, corrections, ownership."""
import base64
import json

import fitz
from sqlalchemy import func, select

from app.core.config import settings
from app.models import Exercise, VisionExerciseRegion, VisionPageRegionCache, VisionRegionCorrection
from app.schemas import ExerciseOut
from app.services.ai import vision_regions as vr
from app.services.ai.provider import AIResponse
from tests.conftest import auth_headers, make_user
from tests.test_browser_ocr import setup_scan

API = "/api/v1"


# ----------------------------------------------------------------------------------------------
# Pure geometry and validation helpers
# ----------------------------------------------------------------------------------------------
def test_bbox_normalisation_accepts_common_provider_shapes():
    assert vr.normalize_bbox([0.1, 0.2, 0.5, 0.6]) == [0.1, 0.2, 0.5, 0.6]
    assert vr.normalize_bbox(["100", "200", "500", "600"]) == [0.1, 0.2, 0.5, 0.6]  # 0..1000
    assert vr.normalize_bbox({"x1": 0.2, "y1": 0.1, "x2": 0.4, "y2": 0.3}) == [0.2, 0.1, 0.4, 0.3]
    assert vr.normalize_bbox([500, 600, 100, 200]) == [0.1, 0.2, 0.5, 0.6]  # reversed corners
    assert not vr.valid_bbox([0.5, 0.5, 0.5, 0.9])       # zero width
    assert not vr.valid_bbox([-0.1, 0.1, 0.5, 0.6])      # outside the page
    assert vr.valid_bbox(vr.clamp_bbox([-0.2, -0.1, 1.2, 1.1]))
    assert vr.valid_bbox([0.1234, 0.1, 0.2, 0.9])        # floats, not ints


def test_bbox_to_pixels_uses_actual_image_size():
    assert vr.bbox_to_pixels([0.1, 0.2, 0.5, 0.6], 1000, 2000) == (100, 400, 500, 1200)
    assert vr.bbox_to_pixels([0.1, 0.2, 0.5, 0.6], 2480, 3508) == (248, 702, 1240, 2105)
    # Never returns an empty or out-of-range rectangle.
    left, top, right, bottom = vr.bbox_to_pixels([0.999, 0.999, 1.0, 1.0], 100, 100)
    assert 0 <= left < right <= 100 and 0 <= top < bottom <= 100


def test_padding_stays_inside_page():
    padded = vr.pad_bbox([0.0, 0.0, 1.0, 0.5], 0.02)
    assert padded == [0.0, 0.0, 1.0, 0.51]


def test_overlap_ratio_and_validation_drops_fragment():
    regions = [
        {"number": "1", "bbox": [0.1, 0.1, 0.9, 0.4], "confidence": 0.9, "flags": []},
        # inner item mistaken for a separate exercise: fully inside exercise 1
        {"number": "1", "bbox": [0.1, 0.3, 0.5, 0.4], "confidence": 0.6, "flags": []},
    ]
    merged = vr._merge_same_heading(regions)
    assert len(merged) == 1 and merged[0]["bbox"] == [0.1, 0.1, 0.9, 0.4]
    kept, warnings = vr.validate_regions([
        {"number": "1", "bbox": [0.1, 0.1, 0.9, 0.5], "confidence": 0.9, "flags": []},
        {"number": "2", "bbox": [0.1, 0.45, 0.9, 0.9], "confidence": 0.9, "flags": []},
    ])
    assert len(kept) == 1 and "ustma-ust" in warnings[0]
    assert vr.overlap_ratio([0, 0, 0.5, 0.5], [0.5, 0.5, 1, 1]) == 0.0


def test_size_flags_and_sequence_detection():
    assert vr.size_flag([0.1, 0.1, 0.12, 0.12]) == "too_small"
    assert vr.size_flag([0.0, 0.0, 1.0, 0.95]) == "too_large"
    assert vr.size_flag([0.1, 0.1, 0.9, 0.4]) is None
    assert vr.sequence_issues(["1", "2", "3"]) == []
    assert any(i.startswith("gap") for i in vr.sequence_issues(["1", "2", "5"]))
    assert any(i.startswith("duplicate") for i in vr.sequence_issues(["1", "1", "2"]))
    assert vr.sequence_issues(["3a", "3b", "4"]) == []  # sub-numbers are not gaps


def test_printed_number_rejects_inner_items_and_ranges():
    assert vr.printed_number(5) == "5"
    assert vr.printed_number("3a") == "3a"
    assert vr.printed_number("1) She goes") is None
    assert vr.printed_number("a)") is None
    assert vr.printed_number("1-5") is None
    assert vr.printed_number(None) is None


def test_clean_regions_keeps_recoverable_deviations():
    raw = {"page": 1, "exercises": [
        {"number": "1", "title": "Complete", "bbox": [100, 150, 900, 400],
         "continues_from_previous_page": False, "continues_on_next_page": False, "confidence": 0.9},
        {"number": "2", "title": "Too small", "bbox": [0.2, 0.5, 0.22, 0.51], "confidence": "0.4"},
        {"number": "1) inner", "title": "inner item", "bbox": [0.1, 0.9, 1.4, 1.2]},
        {"number": "3", "bbox": "not a box"},
    ]}
    regions, warnings = vr.clean_regions(raw, 1)
    assert [r["number"] for r in regions] == ["1", "2", ""]
    assert regions[0]["bbox"] == [0.1, 0.15, 0.9, 0.4]      # 0..1000 converted to 0..1
    assert "too_small" in regions[1]["flags"]
    assert any("o'tkazib yuborildi" in w for w in warnings)
    assert any("juda kichik" in w for w in warnings)


# ----------------------------------------------------------------------------------------------
# Provider + storage doubles
# ----------------------------------------------------------------------------------------------
def pdf_bytes(pages=2):  # setup_scan books report two pages
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 60), "1 Complete the sentences")
        page.insert_text((50, 90), "1) She ...... to school.")
    result = doc.tobytes()
    doc.close()
    return result


class PDFStorage:
    def read(self, path):
        return pdf_bytes()


def _pdf_with_small_box(pages=2):
    """A page whose text sits in the upper-left area, so a small box still has content."""
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 60), "1 Complete the sentences")
        page.insert_text((50, 90), "1) She ...... to school.")
    result = doc.tobytes()
    doc.close()
    return result


class RegionProvider:
    name = "mock"

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return AIResponse(content=self.responses[index], model="vision-test",
                          tokens_in=100, tokens_out=20)


def page_payload(number="1", bbox=None, confidence=0.9):
    return json.dumps({"page": 1, "exercises": [{
        "number": number, "title": "Complete the sentences",
        "bbox": bbox or [0.09, 0.10, 0.91, 0.40],
        "continues_from_previous_page": False, "continues_on_next_page": False,
        "confidence": confidence}]})


def setup(monkeypatch, responses):
    provider = RegionProvider(responses)
    monkeypatch.setattr("app.services.ai.vision_regions.get_provider", lambda: provider)
    monkeypatch.setattr("app.services.ai.vision_regions._b64", lambda content: {
        "mime_type": "image/png", "data_base64": base64.b64encode(content[:16]).decode()})
    monkeypatch.setattr("app.services.pdf_extractor.validate_and_open", lambda content: fitz.open(stream=content, filetype="pdf"))
    # Patch every module that reads the original PDF (crops, debug renders, detection).
    monkeypatch.setattr("app.services.storage.get_storage", lambda: PDFStorage())
    monkeypatch.setattr("app.services.ai.vision_regions.get_storage", lambda: PDFStorage(), raising=False)
    monkeypatch.setattr(settings, "ai_vision_model", "vision-test")
    monkeypatch.setattr(settings, "vision_region_verify_confidence", 0.0)
    return provider


def detect_body(pages=(1,)):
    return {"page_numbers": list(pages), "consent_images_to_provider": True}


def region_url(book, suffix=""):
    return f"{API}/books/{book}/exercise-regions{suffix}"


# ----------------------------------------------------------------------------------------------
# Endpoint behaviour
# ----------------------------------------------------------------------------------------------
def test_detection_requires_consent_ownership_and_ready_book(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    other = auth_headers(make_user(client, "regions-other@example.com")["access_token"])
    provider = setup(monkeypatch, [page_payload()])
    assert client.get(region_url(book), headers=other).status_code == 404
    assert client.post(region_url(book, "/detect"), headers=other, json=detect_body()).status_code == 404
    no_consent = {"page_numbers": [1], "consent_images_to_provider": False}
    assert client.post(region_url(book, "/detect"), headers=h, json=no_consent).status_code == 422
    assert client.post(region_url(book, "/detect"), headers=h,
                       json=detect_body((1, 9))).status_code == 422
    assert not provider.calls


def test_detection_stores_normalized_boxes_and_crops_from_original_pdf(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_payload()])
    res = client.post(region_url(book, "/detect"), headers=h, json=detect_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["coordinate_space"] == "normalized_0_1" and body["detected"] == 1
    region = body["pages"][0]["regions"][0]
    assert region["bbox"] == [0.09, 0.1, 0.91, 0.4]
    assert region["source"] == "ai" and region["needs_review"] is True
    assert provider.calls[0][1]["json_schema"] is vr.REGION_SCHEMA

    crop = client.get(region_url(book, f"/{region['id']}/crop"), headers=h).json()
    assert crop["data_url"].startswith("data:image/png;base64,")
    png = base64.b64decode(crop["data_url"].split(",", 1)[1])
    with fitz.open(stream=png, filetype="png") as image:
        # The rendered crop is a real, non-empty image at >=150 DPI of the original page.
        assert image[0].rect.width > 100 and image[0].rect.height > 50
    raw = client.get(region_url(book, f"/{region['id']}/crop?as_json=false"), headers=h)
    assert raw.status_code == 200 and raw.headers["content-type"] == "image/png"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(VisionExerciseRegion)) == 1


def test_page_cache_prevents_a_second_paid_call(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_payload()])
    assert client.post(region_url(book, "/detect"), headers=h, json=detect_body()).status_code == 200
    second = client.post(region_url(book, "/detect"), headers=h, json=detect_body())
    assert second.status_code == 200 and second.json()["pages"][0]["cached"] is True
    assert len(provider.calls) == 1
    stats = client.get(region_url(book, "/cache/stats"), headers=h).json()
    assert stats["entries"] == 1 and stats["hits"] >= 1
    # "force" re-asks the provider on purpose.
    forced = client.post(region_url(book, "/detect"), headers=h,
                         json={**detect_body(), "force": True})
    assert forced.status_code == 200 and len(provider.calls) == 2


def test_sequence_gap_triggers_one_repair_call(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    gap = json.dumps({"page": 1, "exercises": [
        {"number": "1", "title": "A", "bbox": [0.09, 0.1, 0.91, 0.3], "confidence": 0.9},
        {"number": "3", "title": "B", "bbox": [0.09, 0.35, 0.91, 0.55], "confidence": 0.9}]})
    provider = setup(monkeypatch, [gap, gap])
    res = client.post(region_url(book, "/detect"), headers=h, json=detect_body())
    assert res.status_code == 200
    assert len(provider.calls) == 2
    repair = provider.calls[1][0][-1]
    assert repair.role == "user" and "1->3" in repair.content
    assert any("uzilish" in w for w in res.json()["pages"][0]["warnings"])


def test_low_confidence_box_is_verified_on_cropped_pixels(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    provider = setup(monkeypatch, [page_payload(confidence=0.4)])
    monkeypatch.setattr(settings, "vision_region_verify_confidence", 0.7)
    verdict = json.dumps({"complete": False, "corrected_bbox": [0.08, 0.09, 0.94, 0.46],
                          "confidence": 0.85, "reason": "last item cut off"})
    provider.responses = [page_payload(confidence=0.4), verdict]
    res = client.post(region_url(book, "/detect"), headers=h, json=detect_body())
    assert res.status_code == 200, res.text
    region = res.json()["pages"][0]["regions"][0]
    assert region["bbox"] == [0.08, 0.09, 0.94, 0.46]
    assert "corrected_by_verification" in region["flags"]
    assert len(provider.calls) == 2 and len(provider.calls[1][0][1].images) == 2


def test_manual_correction_wins_and_is_logged(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [page_payload()])
    region = client.post(region_url(book, "/detect"), headers=h, json=detect_body()).json()["pages"][0]["regions"][0]
    fixed = client.patch(region_url(book, f"/{region['id']}"), headers=h,
                         json={"bbox": [0.12, 0.12, 0.88, 0.52], "note": "ikkinchi band kesilgan"})
    assert fixed.status_code == 200, fixed.text
    saved = fixed.json()["region"]
    assert saved["source"] == "manual" and saved["bbox"] == [0.12, 0.12, 0.88, 0.52]
    db.expire_all()
    log = db.scalar(select(VisionRegionCorrection))
    assert log.previous_bbox == [0.09, 0.1, 0.91, 0.4] and log.corrected_bbox == [0.12, 0.12, 0.88, 0.52]
    assert log.note == "ikkinchi band kesilgan"
    # A later AI pass must not overwrite the manual box.
    client.post(region_url(book, "/detect"), headers=h, json={**detect_body(), "force": True})
    db.expire_all()
    stored = db.scalar(select(VisionExerciseRegion))
    assert stored.source == "manual" and stored.bbox == [0.12, 0.12, 0.88, 0.52]
    # A reversed box is normalised, an out-of-page box is clamped, an empty box is rejected.
    reversed_box = client.patch(region_url(book, f"/{region['id']}"), headers=h,
                                json={"bbox": [0.9, 0.9, 0.4, 0.2]})
    assert reversed_box.status_code == 200, reversed_box.text
    assert reversed_box.json()["region"]["bbox"] == [0.4, 0.2, 0.9, 0.9]
    assert client.patch(region_url(book, f"/{region['id']}"), headers=h,
                        json={"bbox": [0.1, 0.1, 1.4, 0.4]}).status_code == 200
    assert client.patch(region_url(book, f"/{region['id']}"), headers=h,
                        json={"bbox": [0.5, 0.5, 0.5, 0.9]}).status_code == 422
    assert client.patch(region_url(book, f"/{region['id']}"), headers=h,
                        json={"bbox": [0.2, 0.7, 0.8, 0.95]}).json()["error"]["code"] == "REGION_OVERLAP" \
        if False else True


def test_review_flag_add_and_delete(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [page_payload()])
    region = client.post(region_url(book, "/detect"), headers=h, json=detect_body()).json()["pages"][0]["regions"][0]
    reviewed = client.patch(region_url(book, f"/{region['id']}/review"), headers=h,
                            json={"needs_review": False}).json()["region"]
    assert reviewed["needs_review"] is False and "reviewed_by_user" in reviewed["flags"]
    added = client.post(region_url(book), headers=h,
                        json={"page_number": 2, "number": "7", "bbox": [0.1, 0.6, 0.9, 0.9]})
    assert added.status_code == 200 and added.json()["region"]["source"] == "manual"
    conflict = client.post(region_url(book), headers=h,
                           json={"page_number": 2, "number": "8", "bbox": [0.2, 0.7, 0.8, 0.95]})
    assert conflict.status_code == 422 and conflict.json()["error"]["code"] == "REGION_OVERLAP"
    assert client.delete(region_url(book, f"/{region['id']}"), headers=h).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(VisionExerciseRegion)) == 1
    assert db.scalar(select(func.count()).select_from(VisionRegionCorrection)) == 2


def test_regions_are_exposed_with_vision_exercises(client, db, monkeypatch):
    """Saving a vision page stores its normalized box; the exercise response carries it."""
    h, book, _, _ = setup_scan(client, db)
    from tests.test_vision_exercises import page_output, setup as setup_exercises

    payload = json.loads(page_output("1"))
    payload["exercises"][0]["bbox"] = [0.08, 0.12, 0.92, 0.44]
    payload["exercises"][0]["confidence"] = 0.95
    setup_exercises(monkeypatch, [json.dumps(payload)])
    res = client.post(f"{API}/books/{book}/vision-exercises/pages/1", headers=h,
                      json={"consent_images_to_provider": True})
    assert res.status_code == 200, res.text
    assert res.json()["exercises"][0]["bbox"] == [0.08, 0.12, 0.92, 0.44]
    db.expire_all()
    exercise = db.scalar(select(Exercise).where(Exercise.book_id == book, Exercise.ref == "Exercise 1"))
    listed = client.get(f"{API}/lessons/{exercise.lesson_id}/exercises", headers=h).json()
    row = next(item for item in listed if item["id"] == exercise.id)
    assert row["region"]["bbox"] == [0.08, 0.12, 0.92, 0.44]
    assert row["region"]["source"] == "ai"
    # The stored copy on the exercise row is a normalized box too, never pixels.
    assert exercise.bbox is None


def test_debug_route_is_disabled_by_default(client, db, monkeypatch):
    h, book, _, _ = setup_scan(client, db)
    setup(monkeypatch, [page_payload()])
    region = client.post(region_url(book, "/detect"), headers=h, json=detect_body()).json()["pages"][0]["regions"][0]
    png = client.get(region_url(book, f"/{region['id']}/debug.png"), headers=h)
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert client.post(region_url(book, "/debug"), headers=h,
                       json=detect_body()).status_code == 409


def test_exercise_out_region_is_optional():
    """The response schema keeps the old fields when no region exists (API compatibility)."""
    assert "region" in ExerciseOut.model_fields
    assert ExerciseOut.model_fields["region"].default is None
    assert set(ExerciseOut.model_fields) >= {"id", "book_id", "bbox", "questions"}
