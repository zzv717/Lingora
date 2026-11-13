"""Read-only visual evidence for OCR review, NOT a verified exercise parser.

The OCR line boxes are real observations. Grouping is speculative and never writes
exercise, answer or progress records. Full-page scan images are not illustrations.
"""
from dataclasses import dataclass
import re
from typing import Any

_NUMBER_AND_TEXT = re.compile(r"^(\d{1,3})\s*[.)\-:]?\s+(.+)$")
_NUMBER_ONLY = re.compile(r"^(\d{1,3})\s*[.)\-:]?$")
# Instruction words are only one signal; location, numbers and neighboring
# blocks are also considered. This list is not a universal language model.
_ACTION = re.compile(r"^(?:(?:in pairs|in groups|with a partner)\s*[,;:]?\s*)?"
                     r"(?:put|complete|choose|match|fill|rewrite|read|answer|correct|"
                     r"write|use|form|make|ask|look|place|sort|classify|group|find|"
                     r"underline|circle|replace|change|give|describe|work)\b", re.I)
_ITEM = re.compile(r"^\s*(\d{1,3})(?:\s*[.)\-:]\s*|\s+)(\S.*)$")


@dataclass(frozen=True)
class _Anchor:
    index: int
    number: str
    instruction: str
    instruction_index: int


def _find_anchor(lines: list[dict[str, Any]], index: int, page_width: float) -> _Anchor | None:
    line = lines[index]
    text = line['text'].strip()
    combined = _NUMBER_AND_TEXT.match(text)
    if combined and _ACTION.match(combined.group(2).strip()):
        return _Anchor(index, combined.group(1), combined.group(2).strip(), index)
    standalone = _NUMBER_ONLY.match(text)
    if not standalone:
        return None
    x0, y0, x1, y1 = line['bbox']
    height = max(y1 - y0, 1.0)
    # OCR can return the exercise number as a separate block. Associate it only
    # with a nearby right-hand or next-line instruction, never a distant region.
    candidates = []
    for i, other in enumerate(lines):
        if i <= index or not _ACTION.match(other['text'].strip()):
            continue
        a, b, _, d = other['bbox']
        same_row = abs((b + d) / 2 - (y0 + y1) / 2) <= max(height, d - b) * 0.8
        right = same_row and 0 <= a - x1 <= min(page_width * 0.10, 60)
        below = 0 <= b - y1 <= height * 1.5 and abs(a - x0) <= min(page_width * 0.08, 40)
        if right or below:
            candidates.append((abs(b - y0) + abs(a - x1), i))
    if len(candidates) != 1:
        return None  # ambiguous neighbors need human review
    _, found = candidates[0]
    return _Anchor(index, standalone.group(1), lines[found]['text'].strip(), found)


def _bbox(lines: list[dict[str, Any]]) -> list[float]:
    return [min(line['bbox'][0] for line in lines), min(line['bbox'][1] for line in lines),
            max(line['bbox'][2] for line in lines), max(line['bbox'][3] for line in lines)]


def visual_candidates(lines: list[dict[str, Any]], width: float, height: float,
                      images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Propose page-local regions using number, instruction and geometry evidence.

    Ordering, columns and question boundaries are heuristic, not proof. Even
    individual OCR lines can merge text from unrelated regions. Compare to the
    original page before using any proposed region.
    """
    if width <= 0 or height <= 0:
        return {'candidates': [], 'warnings': ['INVALID_PAGE_SIZE']}
    anchors = [a for i in range(len(lines)) if (a := _find_anchor(lines, i, width))]
    candidates = []
    for pos, anchor in enumerate(anchors):
        end = anchors[pos + 1].index if pos + 1 < len(anchors) else len(lines)
        # An instruction starting in the right half is strong evidence that a
        # much further left line belongs to a different region. This does NOT
        # detect tables or unmixed OCR lines and stays review-only.
        anchor_x = lines[anchor.index]['bbox'][0]
        left_limit = max(0, anchor_x - width * 0.04) if anchor_x >= width * 0.4 else 0
        section = [line for line in lines[anchor.index:end] if line['bbox'][0] >= left_limit]
        if not section:
            continue
        region = _bbox(section)
        numbered_items = []
        current_item = None
        for i in range(anchor.index + 1, end):
            line = lines[i]
            if i == anchor.instruction_index or line['bbox'][0] < left_limit:
                continue
            m = _ITEM.match(line['text'])
            if m:
                current_item = {'number': m.group(1), 'text': line['text'],
                                'bbox': line['bbox'], 'continuation_lines': []}
                numbered_items.append(current_item)
            elif current_item is not None:
                current_item['continuation_lines'].append(line['text'])
        # Only observations of non-page-sized image boxes are reported. Embedded
        # scan backgrounds do not prove where textbook pictures or tables are.
        overlaps = []
        for image in images or []:
            if not isinstance(image, dict):
                continue
            box = image.get('bbox')
            if not isinstance(box, list) or len(box) != 4 or any(not isinstance(v, (int, float)) for v in box):
                continue
            x0, y0, x1, y1 = box
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                continue
            if (x1-x0) * (y1-y0) >= width * height * 0.65:
                continue
            if x0 < region[2] and x1 > region[0] and y0 < region[3] and y1 > region[1]:
                overlaps.append({'bbox': box, 'relationship': 'overlaps_region_unverified'})
        candidates.append({'number': anchor.number, 'instruction': anchor.instruction,
            'bbox': region, 'normalized_bbox': [region[0] / width, region[1] / height,
                                               region[2] / width, region[3] / height],
            'lines': [{'text': line['text'], 'bbox': line['bbox'], 'confidence': line.get('confidence')}
                      for line in section],
            'numbered_item_candidates': numbered_items, 'image_candidates': overlaps,
            'evidence': ['number', 'instruction', 'proximity'] if anchor.index != anchor.instruction_index
                        else ['number', 'instruction'],
            'needs_review': True})
    return {'candidates': candidates,
            'warnings': ['HEURISTIC_REGIONS_REQUIRE_REVIEW', 'CROSS_PAGE_GROUPING_NOT_AVAILABLE']}
