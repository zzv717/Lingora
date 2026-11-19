"""PDF text/layout extraction with PyMuPDF, plus optional OCR.

Every page yields lines WITH bounding boxes and font sizes — the structure detector
uses these to find chapters, exercises and answer blanks, and the interactive reader
uses them to position answer overlays on top of the original page.
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import fitz  # PyMuPDF

from app.core.config import settings
from app.core.errors import ApiError
from app.services.ocr_layout import order_ocr_lines

log = logging.getLogger("lingora.pdf")

MIN_TEXT_CHARS_FOR_OCR = 24


class PdfValidationError(ApiError):
    pass


def validate_and_open(content: bytes) -> fitz.Document:
    if len(content) < 100 or not content[:1024].lstrip().startswith(b"%PDF"):
        raise PdfValidationError("INVALID_FILE", "Yuklangan fayl haqiqiy PDF emas.", 415)
    max_bytes = settings.upload_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise PdfValidationError(
            "FILE_TOO_LARGE",
            f"Fayl hajmi juda katta ({len(content) // (1024*1024)} MB). Ruxsat etilgan chegara: {settings.upload_max_mb} MB.",
            413,
        )
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:
        raise PdfValidationError("PDF_CORRUPTED", f"PDF fayl ochilmadi (buzilgan bo'lishi mumkin): {type(e).__name__}", 422)
    if doc.page_count == 0:
        doc.close()
        raise PdfValidationError("PDF_EMPTY", "PDF faylda sahifalar yo'q.", 422)
    if doc.page_count > settings.max_pages:
        n = doc.page_count
        doc.close()
        raise PdfValidationError(
            "TOO_MANY_PAGES",
            f"Kitob {n} sahifadan iborat. Hozircha ko'pi bilan {settings.max_pages} sahifa qabul qilinadi.",
            413,
        )
    return doc


def _extract_lines(page: fitz.Page) -> list[dict[str, Any]]:
    """Native glyph boxes in unrotated, crop-relative PDF points (top-left origin).

    Each entry in ``chars`` corresponds to exactly one codepoint in ``text``.
    Missing glyph geometry must never become an overlay location.
    """
    lines: list[dict[str, Any]] = []
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return lines
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text_parts: list[str] = []
            chars: list[list[float] | None] = []
            sizes = []
            fonts = []
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    value = char.get("c", "")
                    box = char.get("bbox")
                    for c in value:
                        text_parts.append(c)
                        chars.append([round(v, 2) for v in box] if box else None)
                sizes.append(span.get("size", 10.0))
                fonts.append(span.get("font", ""))
            text = "".join(text_parts)
            left = len(text) - len(text.lstrip())
            right = len(text.rstrip())
            text = text[left:right]
            chars = chars[left:right]
            if not text:
                continue
            lines.append({
                "text": text, "chars": chars,
                "bbox": [round(v, 2) for v in line["bbox"]],
                "size": round(max(sizes, default=10.0), 2),
                "bold": any("bold" in f.lower() or "black" in f.lower() for f in fonts),
                "x0": round(line["bbox"][0], 2),
            })
    lines.sort(key=lambda l: (round(l["bbox"][1], 1), l["bbox"][0]))
    return lines


def _extract_images(page: fitz.Page) -> list[dict[str, Any]]:
    out = []
    try:
        for img in page.get_image_info():
            bbox = img.get("bbox")
            if bbox and (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 2500:  # skip icons/noise
                out.append({"bbox": [round(v, 2) for v in bbox]})
    except Exception:
        pass
    return out


_TESS_AVAILABLE: bool | None = None


def ocr_available() -> bool:
    global _TESS_AVAILABLE
    if _TESS_AVAILABLE is None:
        try:
            import pytesseract  # noqa: F401

            pytesseract.get_tesseract_version()
            _TESS_AVAILABLE = True
        except Exception:
            _TESS_AVAILABLE = False
    return _TESS_AVAILABLE


def ocr_page_lines(page: fitz.Page, dpi: int = 200) -> list[dict[str, Any]]:
    """Tesseract word/line boxes mapped back to unrotated crop-relative PDF points.

    Word boxes are retained for inspection; they are not character-level blank geometry.
    """
    if not ocr_available():
        return []
    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi, alpha=False)
    # Convert straight from the pixmap samples; a PNG encode/decode round trip
    # per page was pure overhead (same pixels, same OCR result).
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        try:
            data = pytesseract.image_to_data(img, lang="eng+uzb", output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(img, lang="eng", output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractError, RuntimeError):
        log.warning("Local OCR failed on page %s", page.number + 1)
        return []
    scale = dpi / 72.0
    groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for i, raw in enumerate(data.get("text", [])):
        text = str(raw).strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
            x, y = data["left"][i] / scale, data["top"][i] / scale
            w, h = data["width"][i] / scale, data["height"][i] / scale
            rect = fitz.Rect(x, y, x + w, y + h) * page.derotation_matrix
            box = [round(v, 2) for v in rect]
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if conf < 0 or w <= 0 or h <= 0:
            continue
        groups.setdefault(key, []).append({"text": text, "bbox": box, "confidence": conf})
    lines = []
    for words in groups.values():
        box = [min(w["bbox"][0] for w in words), min(w["bbox"][1] for w in words),
               max(w["bbox"][2] for w in words), max(w["bbox"][3] for w in words)]
        lines.append({"text": " ".join(w["text"] for w in words), "bbox": box, "words": words,
                      "confidence": sum(w["confidence"] for w in words) / len(words),
                      "size": 10.0, "bold": False, "x0": box[0]})
    return lines


def _run_ocr_parallel(doc: fitz.Document, needed: list[int],
                      progress_cb: Callable[[float, str], None] | None,
                      start: float, end: float, total: int,
                      source_bytes: bytes | None = None) -> dict[int, list[dict[str, Any]]]:
    """Recognize OCR-needed pages concurrently.

    Tesseract runs as a subprocess and releases the GIL, so pages are recognized
    in parallel threads. PyMuPDF Document/Page objects must not be shared
    between threads, so each worker opens its own document from one serialized
    copy of the PDF. Results are keyed by 0-based page index; a worker failure
    yields no lines (the caller then reports OCR_FAILED, as before).
    """
    results: dict[int, list[dict[str, Any]]] = {}
    workers = min(4, os.cpu_count() or 1, len(needed)) if ocr_available() else 1
    # Bound the extra memory held by worker document copies. The pipeline can
    # pass its already-loaded bytes so this does not serialize a large PDF again.
    max_parallel_bytes = 128 * 1024 * 1024
    pdf_bytes = source_bytes
    if workers > 1 and pdf_bytes is not None:
        workers = min(workers, max(1, max_parallel_bytes // max(len(pdf_bytes), 1)))
    if workers > 1 and pdf_bytes is None:
        try:
            pdf_bytes = doc.tobytes()
            workers = min(workers, max(1, max_parallel_bytes // max(len(pdf_bytes), 1)))
        except Exception:
            pdf_bytes = None
    if workers <= 1 or pdf_bytes is None:
        # Single worker (or serialization failed): sequential on the shared doc.
        for index in needed:
            try:
                results[index] = ocr_page_lines(doc[index])
            except Exception:
                log.warning("OCR failed on page %s", index + 1)
                results[index] = []
        return results

    thread_state = threading.local()
    worker_docs: list[fitz.Document] = []
    worker_docs_lock = threading.Lock()

    def _ocr_one(index: int) -> tuple[int, list[dict[str, Any]]]:
        try:
            worker_doc = getattr(thread_state, "doc", None)
            if worker_doc is None:
                worker_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                thread_state.doc = worker_doc
                with worker_docs_lock:
                    worker_docs.append(worker_doc)
            return index, ocr_page_lines(worker_doc[index])
        except Exception:
            log.warning("OCR failed on page %s", index + 1)
            return index, []

    done = 0
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lingora-ocr") as pool:
            futures = {pool.submit(_ocr_one, index): index for index in needed}
            for future in as_completed(futures):
                index, lines = future.result()
                results[index] = lines
                done += 1
                progress_cb and progress_cb(start + (end - start) * done / max(total, 1), "extracting")
    finally:
        for worker_doc in worker_docs:
            worker_doc.close()
    return results


def extract_document(doc: fitz.Document, progress_cb: Callable[[float, str], None] | None = None,
                     start: float = 0.0, end: float = 100.0,
                     source_bytes: bytes | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (pages, warnings). pages have stable page_number (1-based) and layout data."""
    total = doc.page_count
    # Phase 1: native extraction for every page (sequential; PyMuPDF objects are
    # not shared between threads). Keep canonical page text and geometry lines
    # separate so the detector retains the established reading-order semantics.
    raw_pages: list[dict[str, Any]] = []
    for i, page in enumerate(doc):
        progress_cb and progress_cb(start + (end - start) * i / max(total, 1), "extracting")
        lines = _extract_lines(page)
        # Keep PyMuPDF's canonical text stream for detector compatibility; rawdict
        # line ordering is optimized for geometry, not necessarily reading order.
        text = page.get_text("text").strip()
        images = _extract_images(page)
        # This is a layout indicator, not proof that an image contains text.
        # A text layer over a scanned page is also mixed and must be reviewed.
        page_type = "mixed" if text and images else "text" if text else "scanned" if images else "blank"
        raw_pages.append({
            "index": i, "lines": lines, "text": text, "images": images,
            "page_type": page_type, "needs_ocr": len(text) < MIN_TEXT_CHARS_FOR_OCR,
            "width": round(page.cropbox.width, 2), "height": round(page.cropbox.height, 2),
            "crop_width": page.cropbox.width,
        })

    # Phase 2: OCR for pages that need it (never for mixed pages — their native
    # layer must not be overwritten with unverified OCR).
    needed = [r["index"] for r in raw_pages if r["needs_ocr"] and r["page_type"] != "mixed"]
    ocr_results: dict[int, list[dict[str, Any]]] = {}
    if needed:
        # Always run the wrapper: it preserves the established empty-result and
        # OCR_FAILED behavior when Tesseract is absent, while remaining testable.
        ocr_results = _run_ocr_parallel(doc, needed, progress_cb, start, end, total, source_bytes)

    # Phase 3: assemble pages and warnings in page order.
    pages: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for r in raw_pages:
        i = r["index"]
        lines = r["lines"]
        page_text = r["text"]
        needs_ocr = r["needs_ocr"]
        ocr_used = False
        if r["page_type"] == "mixed":
            warnings.append({"page": i + 1, "code": "MIXED_PAGE_REVIEW_REQUIRED",
                "message_uz": f"{i + 1}-sahifada matn va rasm bor; rasm ichidagi matn ko'rib chiqilishi kerak."})
        # Never overwrite the native layer of a mixed page with unverified OCR.
        # A short native layer leaves the page pending for manual preview.
        if needs_ocr and r["page_type"] != "mixed":
            ocr_lines = ocr_results.get(i, [])
            ocr_lines, layout = order_ocr_lines(ocr_lines, r["crop_width"])
            if layout != "original":
                warnings.append({"page": i + 1, "code": "OCR_LAYOUT_REVIEW",
                                 "message_uz": f"{i + 1}-sahifaning ustun/jadval tartibi tekshirilishi kerak."})
            ocr_text = "\n".join(line["text"] for line in ocr_lines)
            confidence = sum(line.get("confidence", 0) for line in ocr_lines) / max(len(ocr_lines), 1)
            if len(ocr_text.strip()) >= MIN_TEXT_CHARS_FOR_OCR and confidence >= 40:
                page_text = ocr_text.strip()
                ocr_used = True
                needs_ocr = False
                lines = ocr_lines
                warnings.append({"page": i + 1, "code": "OCR_REVIEW_REQUIRED",
                                 "message_uz": f"{i + 1}-sahifaning OCR matni tekshirilishi kerak."})
            else:
                warnings.append({
                    "page": i + 1,
                    "code": "OCR_UNAVAILABLE" if not ocr_available() else "OCR_FAILED",
                    "message_uz": (
                        f"{i + 1}-sahifa matnsiz (skanerlangan). OCR xizmati sozlanmagan "
                        "yoki ishlamadi — bu sahifa tahlil qilinmadi."
                    ),
                })
        pages.append({
            "page_number": i + 1,
            "width": r["width"],
            "height": r["height"],
            "text": page_text,
            "lines": lines,
            "images": r["images"],
            "page_type": r["page_type"],
            "needs_ocr": needs_ocr and not ocr_used,
            "ocr_used": ocr_used,
        })
    return pages, warnings
