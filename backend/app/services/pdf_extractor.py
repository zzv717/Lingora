"""PDF text/layout extraction with PyMuPDF, plus optional OCR.

Every page yields lines WITH bounding boxes and font sizes — the structure detector
uses these to find chapters, exercises and answer blanks, and the interactive reader
uses them to position answer overlays on top of the original page.
"""
import io
import logging
from typing import Any, Callable

import fitz  # PyMuPDF

from app.core.config import settings
from app.core.errors import ApiError

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
    lines: list[dict[str, Any]] = []
    try:
        raw = page.get_text("dict")
    except Exception:
        return lines
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = " ".join(s["text"].strip() for s in spans).strip()
            if not text:
                continue
            sizes = [s.get("size", 10.0) for s in spans]
            fonts = " ".join({s.get("font", "") for s in spans})
            lines.append({
                "text": text,
                "bbox": [round(v, 2) for v in line["bbox"]],
                "size": round(max(sizes), 2),
                "bold": any("bold" in f.lower() or "black" in f.lower() for f in fonts.split()),
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


def ocr_page(page: fitz.Page, dpi: int = 200) -> str:
    """Rasterize + OCR one page. Returns '' if OCR is unavailable (callers report honestly)."""
    if not ocr_available():
        return ""
    import numpy as np  # pytesseract needs PIL images only; numpy optional
    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return pytesseract.image_to_string(img, lang="eng+uzb")
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(img, lang="eng")


def extract_document(doc: fitz.Document, progress_cb: Callable[[float, str], None] | None = None,
                     start: float = 0.0, end: float = 100.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (pages, warnings). pages have stable page_number (1-based) and layout data."""
    pages: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    total = doc.page_count
    for i, page in enumerate(doc):
        progress_cb and progress_cb(start + (end - start) * i / max(total, 1), "extracting")
        lines = _extract_lines(page)
        text = page.get_text("text").strip()
        needs_ocr = len(text) < MIN_TEXT_CHARS_FOR_OCR
        ocr_used = False
        page_text = text
        if needs_ocr:
            ocr_text = ocr_page(page)
            if ocr_text.strip():
                page_text = ocr_text.strip()
                ocr_used = True
                needs_ocr = False
                lines = [
                    {"text": ln, "bbox": [0, 0, round(page.rect.width, 2), round(page.rect.height, 2)],
                     "size": 10.0, "bold": False, "x0": 0}
                    for ln in page_text.splitlines() if ln.strip()
                ]
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
            "width": round(page.rect.width, 2),
            "height": round(page.rect.height, 2),
            "text": page_text,
            "lines": lines,
            "images": _extract_images(page),
            "needs_ocr": needs_ocr and not ocr_used,
            "ocr_used": ocr_used,
        })
    return pages, warnings
