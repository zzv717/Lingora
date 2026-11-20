"""Locate the illustration of each dictionary headword on the ORIGINAL PDF page.

Some vocabulary books ("4000 Essential English Words" and similar) draw every
illustration into one full-page background image, so the PDF exposes no per-word
picture to copy. The word tells us exactly where to look: its headword line is known,
and its picture sits in the narrow column left of that line, vertically centred on the
headword. We render only that column and find the tight ink bounding box in it.

Nothing is invented: if the strip has no ink (or the geometry looks implausible) the
word simply gets no picture and the UI shows text only.
"""
import logging
from typing import Any

import fitz

log = logging.getLogger("lingora.dictionary_pictures")

# Column geometry, in PDF points, relative to the headword line.
STRIP_LEFT_MARGIN = 90.0    # how far left of the headword the picture column may start
STRIP_GAP = 6.0             # gap between the picture and the headword text
BAND_MARGIN = 30.0          # half-height searched around the headword centre
RENDER_ZOOM = 2.5           # ~180 DPI: enough to find an edge, cheap enough to scan
INK_THRESHOLD = 205         # <= this gray level counts as ink
MIN_WIDTH = 18.0            # points; smaller blobs are bullets/icons
MIN_HEIGHT = 18.0
MIN_INK_RATIO = 0.02
MIN_BAND = 22.0             # never search less than this around the headword


def _ink_bbox(pix: fitz.Pixmap, center_ratio: float = 0.5) -> tuple[int, int, int, int] | None:
    """Tight box of the illustration centred on the headword, in pixmap coordinates.

    Between two entries the book draws a thin vertical connector line and the arcs of the
    neighbouring circles. A row therefore only counts as "picture" when it covers a
    meaningful share of the strip width — a line or an arc corner never does.
    """
    from PIL import Image

    width, height = pix.width, pix.height
    if width <= 0 or height <= 0:
        return None
    image = Image.frombytes("L", (width, height), pix.samples)
    mask = image.point(lambda value: 255 if value < INK_THRESHOLD else 0)  # 255 = ink
    coverage = [sum(mask.crop((0, y, width, y + 1)).histogram()[255:]) for y in range(height)]
    # 5% of the strip width already excludes the thin connector line between entries
    # while keeping the full height of a round illustration.
    dense_threshold = max(3, int(width * 0.05))
    dense_rows = [y for y, count in enumerate(coverage) if count >= dense_threshold]
    if not dense_rows:
        return None
    groups: list[list[int]] = [[dense_rows[0], dense_rows[0]]]
    for y in dense_rows[1:]:
        if y - groups[-1][1] <= 4:  # a thin white gap inside one illustration is not a split
            groups[-1][1] = y
        else:
            groups.append([y, y])
    target = height * center_ratio
    candidates = [g for g in groups if abs((g[0] + g[1]) / 2 - target) <= height * 0.28]
    if not candidates:
        return None
    group = min(candidates, key=lambda g: abs((g[0] + g[1]) / 2 - target))
    if group[1] - group[0] < MIN_HEIGHT * RENDER_ZOOM:
        return None
    # Horizontal extent of the ink inside that vertical band.
    band = mask.crop((0, group[0], width, group[1] + 1))
    box = band.getbbox()
    if not box:
        return None
    left, _, right, _ = box
    if right - left < MIN_WIDTH * RENDER_ZOOM:
        return None
    # Illustrations are round: never let the band be taller than it is wide (that would
    # mean a neighbour's circle leaked in), and keep the window centred on the densest row.
    densest = max(range(group[0], group[1] + 1), key=lambda y: coverage[y])
    tallest = (right - left) * 1.15
    half = min((group[1] - group[0]) / 2, tallest / 2)
    centre = min(max((group[0] + group[1]) / 2, densest - half), densest + half)
    top = int(max(group[0], centre - half))
    bottom = int(min(group[1], centre + half))
    if bottom - top < MIN_HEIGHT * RENDER_ZOOM:
        return None
    return left, top, right, bottom


def picture_box_for(doc: fitz.Document, page_number: int, headword_bbox: list[float],
                    band: float | None = None) -> list[float] | None:
    """Normalized [x1, y1, x2, y2] of the illustration beside one headword line.

    ``band`` is the half-height searched around the headword. Callers pass half the
    distance to the neighbouring entry so one word's crop can never include the next
    word's illustration on tightly spaced word-list pages.
    """
    if not 1 <= page_number <= doc.page_count:
        return None
    page = doc[page_number - 1]
    area = page.rect
    x0 = float(headword_bbox[0])
    center_y = (float(headword_bbox[1]) + float(headword_bbox[3])) / 2
    strip_left = max(4.0, x0 - STRIP_LEFT_MARGIN)
    strip_right = max(strip_left + 8.0, x0 - STRIP_GAP)
    half = min(BAND_MARGIN, max(MIN_BAND, band)) if band else BAND_MARGIN
    top = max(area.y0, center_y - half)
    bottom = min(area.y1, center_y + half)
    if strip_right - strip_left < 8 or bottom - top < 8:
        return None
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM),
                              clip=fitz.Rect(strip_left, top, strip_right, bottom),
                              colorspace=fitz.csGRAY, alpha=False)
    except Exception:  # pragma: no cover - a damaged page must not fail analysis
        log.warning("Could not render picture strip for page %s", page_number)
        return None
    box = _ink_bbox(pix)
    if not box:
        return None
    left, upper, right, lower = box
    if right - left < MIN_WIDTH * RENDER_ZOOM or lower - upper < MIN_HEIGHT * RENDER_ZOOM:
        return None
    if (right - left) * (lower - upper) < MIN_INK_RATIO * pix.width * pix.height:
        return None
    # Back to PDF points, then to page-normalized coordinates.
    pad = 1.5
    x1 = strip_left + left / RENDER_ZOOM - pad
    y1 = top + upper / RENDER_ZOOM - pad
    x2 = strip_left + right / RENDER_ZOOM + pad
    y2 = top + lower / RENDER_ZOOM + pad
    if area.width <= 0 or area.height <= 0:
        return None
    return [round(max(0.0, min(1.0, (x1 - area.x0) / area.width)), 4),
            round(max(0.0, min(1.0, (y1 - area.y0) / area.height)), 4),
            round(max(0.0, min(1.0, (x2 - area.x0) / area.width)), 4),
            round(max(0.0, min(1.0, (y2 - area.y0) / area.height)), 4)]


def _page_bands(vocabulary: list[dict[str, Any]]) -> dict[int, list[tuple[float, float]]]:
    """Per page: (headword centre, half the distance to the nearest other entry)."""
    centres: dict[int, list[float]] = {}
    for entry in vocabulary:
        box, page = entry.get("bbox"), entry.get("page_number")
        if not box or len(box) != 4 or not page:
            continue
        centres.setdefault(int(page), []).append((float(box[1]) + float(box[3])) / 2)
    bands: dict[int, list[tuple[float, float]]] = {}
    for page, values in centres.items():
        values.sort()
        bands[page] = [(value, 0.46 * min([abs(value - other) for other in values if other != value] or [BAND_MARGIN * 2]))
                      for value in values]
    return bands


def attach_word_pictures(doc: fitz.Document, vocabulary: list[dict[str, Any]]) -> int:
    """Fill ``picture`` for entries that carry a headword box but no picture yet."""
    found = 0
    bands = _page_bands(vocabulary)
    for entry in vocabulary:
        if entry.get("picture"):
            continue
        headword = entry.get("bbox")
        page_number = entry.get("page_number")
        if not headword or len(headword) != 4 or not page_number:
            continue
        centre = (float(headword[1]) + float(headword[3])) / 2
        band = next((half for value, half in bands.get(int(page_number), [])
                     if abs(value - centre) < 0.5), None)
        box = picture_box_for(doc, int(page_number), headword, band)
        if not box:
            continue
        entry["picture"] = {"page_number": int(page_number), "bbox": box}
        found += 1
    return found
