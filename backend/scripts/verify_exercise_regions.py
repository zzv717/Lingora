"""Verify exercise-region detection on real pages and print a review table.

Run it against a book already stored by Lingora (no upload is needed):

    cd backend
    python -m scripts.verify_exercise_regions --book <book_id> --pages 1-10 --out ./data/verify

What it prints, per page and per exercise:
    page  number  bbox(x1,y1,x2,y2)  confidence  source  flags

and a second table of failed/wrong cases with the reason (page, exercise, cause):
    * PDF/render problems      -> PDF_PAGE_MISMATCH, PAGE_RENDER_FAILED
    * model output unusable    -> AI_BAD_OUTPUT (after one repair retry)
    * sequence gaps/duplicates -> Uzbek warning from ``sequence_issues``
    * overlapping boxes        -> the smaller box is dropped
    * too small / too large    -> flagged for manual "Tuzatish"
    * low confidence           -> second verification pass result

With ``--debug`` it also writes ``page-XXXX.png`` files with the boxes drawn on them,
so the crops can be checked visually without the app.

This script only reads the stored PDF and never changes exercises, answers or progress.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.errors import ApiError  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Book, Exercise, User  # noqa: E402
from app.services.ai import vision_regions  # noqa: E402
from app.services.ai.provider import AINotConfigured, get_provider  # noqa: E402


class _MockProvider:
    """Deterministic stand-in used only by ``--mock`` to exercise the whole pipeline offline."""

    name = "mock-offline"

    def complete(self, messages, model=None, max_tokens=3000, temperature=0.1,
                 json_mode=False, json_schema=None):
        from app.services.ai.provider import AIResponse

        payload = {}
        try:
            payload = json.loads(messages[1].content)
        except Exception:
            payload = {}
        page = int(payload.get("page") or 1)
        if messages[0].content and "corrected_bbox" in (messages[0].content or ""):
            return AIResponse(content=json.dumps({"complete": True, "corrected_bbox": None,
                                                  "confidence": 0.9, "reason": "mock"}),
                              model="mock-vision", tokens_in=10, tokens_out=10)
        # Page 1 gets three exercises (one low-confidence), others two; every 4th page a gap
        # and a too-small box so the failure table has something to show.
        exercises = [
            {"number": str(page * 2 - 1), "title": "Complete the sentences",
             "bbox": [0.08, 0.08, 0.92, 0.36], "continues_from_previous_page": False,
             "continues_on_next_page": False, "confidence": 0.93},
            {"number": str(page * 2), "title": "Put the verbs into the correct form",
             "bbox": [0.08, 0.39, 0.47, 0.86], "continues_from_previous_page": False,
             "continues_on_next_page": False, "confidence": 0.74 if page % 4 else 0.55},
            {"number": str(page * 2 + 1), "title": "Match the columns",
             "bbox": [0.52, 0.39, 0.92, 0.72], "continues_from_previous_page": False,
             "continues_on_next_page": False, "confidence": 0.81},
        ]
        if page % 4 == 0:
            exercises[1]["number"] = str(page * 2 + 4)  # deliberate gap for the failure table
            exercises[2]["bbox"] = [0.52, 0.39, 0.54, 0.41]  # deliberately too small
        return AIResponse(content=json.dumps({"page": page, "exercises": exercises}),
                          model="mock-vision", tokens_in=100, tokens_out=50)


def parse_pages(text: str, page_count: int) -> list[int]:
    pages: list[int] = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = (int(v) for v in chunk.split("-", 1))
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(chunk))
    return sorted({p for p in pages if 1 <= p <= page_count})


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify normalized exercise crops on real pages.")
    parser.add_argument("--book", required=True, help="book id (as in the app URL)")
    parser.add_argument("--pages", default="1-10", help="e.g. 1-10 or 3,7,12 (default: 1-10)")
    parser.add_argument("--user-email", default=None, help="owner email, required for ambiguous books")
    parser.add_argument("--out", default="./data/verify", help="output directory for the report")
    parser.add_argument("--debug", action="store_true", help="also write pages with boxes drawn")
    parser.add_argument("--workers", type=int, default=4, help="parallel pages (default 4)")
    parser.add_argument("--limit", type=int, default=60, help="maximum pages to process")
    parser.add_argument("--json", action="store_true", help="print the JSON report instead of tables")
    parser.add_argument("--mock", action="store_true",
                        help="offline self-test with a deterministic fake provider (NOT an accuracy result)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        book = db.get(Book, args.book)
        if not book:
            parser.error(f"book {args.book} not found")
        if args.user_email:
            owner = db.query(User).filter(User.email == args.user_email).one_or_none()
            if not owner or owner.id != book.user_id:
                parser.error("the book does not belong to that user")
        pages = parse_pages(args.pages, book.page_count)[: args.limit]
        if not pages:
            parser.error(f"no pages in range 1..{book.page_count}")

        provider = None
        if args.mock:
            provider = _MockProvider()
            print("SELF-TEST MODE: a deterministic offline provider is used. These boxes test the"
                  " pipeline (validation, cache, flags, tables), NOT the model's accuracy.\n")
        else:
            try:
                get_provider()
                vision_regions.vision_model()
            except (AINotConfigured, ApiError) as exc:
                print(f"AI provider is not configured: {getattr(exc, 'message_uz', exc)}")
                print("Set AI_PROVIDER, AI_API_KEY, AI_MODEL and AI_VISION_MODEL in .env first.")
                return 2

        user_id = book.user_id
        outcomes = vision_regions.detect_book(db, user_id, book, pages, workers=args.workers,
                                              provider=provider,
                                              model="mock-vision" if args.mock else None)

        rows: list[dict] = []
        failures: list[dict] = []
        os.makedirs(args.out, exist_ok=True)
        for outcome in outcomes:
            if outcome.error:
                failures.append({"page": outcome.page, "exercise": "-", "reason": outcome.error,
                                 "code": outcome.error_code})
                continue
            for warning in outcome.warnings:
                if "uzilish" in warning or "takrorlanadi" in warning or "ustma-ust" in warning:
                    failures.append({"page": outcome.page, "exercise": "-", "reason": warning,
                                     "code": "SEQUENCE_OR_OVERLAP"})
            for region in outcome.exercises:
                rows.append({
                    "page": outcome.page, "number": region["number"] or "?",
                    "bbox": [round(v, 3) for v in region["bbox"]],
                    "confidence": region["confidence"], "source": region["source"],
                    "flags": ",".join(region.get("flags") or []) or "-",
                    "cached": outcome.cached,
                })
                if "too_small" in (region.get("flags") or []):
                    failures.append({"page": outcome.page, "exercise": region["number"],
                                     "reason": "bbox < 3% of the page", "code": "BOX_TOO_SMALL"})
                elif "too_large" in (region.get("flags") or []):
                    failures.append({"page": outcome.page, "exercise": region["number"],
                                     "reason": "bbox > 90% of the page", "code": "BOX_TOO_LARGE"})
                elif region["confidence"] < 0.7:
                    failures.append({"page": outcome.page, "exercise": region["number"],
                                     "reason": f"low confidence {region['confidence']:.2f} "
                                               f"(verification: {region.get('verification_reason', 'not conclusive')})",
                                     "code": "LOW_CONFIDENCE"})
            if not outcome.exercises:
                failures.append({"page": outcome.page, "exercise": "-",
                                 "reason": "no exercise detected", "code": "NO_EXERCISE"})
            if args.debug:
                corrections = []
                try:
                    from app.models import VisionExerciseRegion
                    corrections = [{"bbox": r.bbox} for r in db.query(VisionExerciseRegion).filter(
                        VisionExerciseRegion.book_id == book.id,
                        VisionExerciseRegion.page_number == outcome.page,
                        VisionExerciseRegion.source == "manual").all()]
                except Exception:
                    corrections = []
                path = vision_regions.save_debug_image(book, outcome.page, outcome.exercises, corrections)
                if path:
                    print(f"debug image: {path}")

        stored = db.query(Exercise).filter(Exercise.book_id == book.id,
                                           Exercise.page_number.in_(pages)).all()
        report = {
            "book_id": book.id,
            "book_title": book.title,
            "page_count": book.page_count,
            "pages_tested": pages,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider.name if provider else getattr(get_provider(), "name", "unknown"),
            "vision_model": vision_regions.vision_model() if not args.mock else "mock-vision",
            "self_test": bool(args.mock),
            "dpi": vision_regions.settings.vision_region_dpi,
            "rows": rows,
            "failures": failures,
            "existing_saved_exercises_on_pages": len(stored),
            "note": "Detection only: nothing is saved, graded or answered by this script.",
        }
        report_path = os.path.join(args.out, "regions-report.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        print(f"\nBook: {book.title[:60]} ({book.page_count} pages) · model: {report['vision_model']}"
              f" · {report['dpi']} DPI")
        print(f"Pages: {pages[0]}..{pages[-1]} ({len(pages)} pages)\n")
        header = f"{'page':>5}  {'ex':>4}  {'bbox (x1,y1,x2,y2)':<28} {'conf':>5}  {'src':<7} flags"
        print(header)
        print("-" * len(header) + "-----")
        for row in rows:
            box = ",".join(f"{v:.3f}" for v in row["bbox"])
            print(f"{row['page']:>5}  {row['number']:>4}  {box:<28} {row['confidence']:>5.2f}  "
                  f"{row['source']:<7} {row['flags']}")
        print(f"\n{len(rows)} exercises on {len({r['page'] for r in rows})} pages")

        print("\nFailed / suspicious cases")
        print("-" * 44)
        if not failures:
            print("none")
        for item in failures:
            print(f"{item['page']:>5}  {str(item['exercise']):>4}  {item['code']:<20} {item['reason']}")

        print(f"\nReport written to {report_path}")
        print("Existing saved exercises on these pages were NOT modified:"
              f" {report['existing_saved_exercises_on_pages']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
