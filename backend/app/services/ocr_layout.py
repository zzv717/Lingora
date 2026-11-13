"""Conservative two-column OCR ordering; uncertain layouts are not rearranged.

This is not table recognition. All detected exercise content remains review-only.
"""
from typing import Any


def order_ocr_lines(lines: list[dict[str, Any]], width: float) -> tuple[list[dict[str, Any]], str]:
    if width <= 0 or len(lines) < 6:
        return lines, "original"
    middle = width / 2
    gutter = width * 0.015
    left = [line for line in lines if line["bbox"][2] <= middle - gutter]
    right = [line for line in lines if line["bbox"][0] >= middle + gutter]
    spanning = [line for line in lines if line not in left and line not in right]
    if len(left) < 3 or len(right) < 3:
        return lines, "original"
    l0, l1 = min(x["bbox"][1] for x in left), max(x["bbox"][3] for x in left)
    r0, r1 = min(x["bbox"][1] for x in right), max(x["bbox"][3] for x in right)
    start, end = max(l0, r0), min(l1, r1)
    if end <= start or end - start < 0.25 * min(l1 - l0, r1 - r0):
        return lines, "original"
    # A spanning line crossing the columns can be a table or a section break;
    # do not reorder it. Headers/footers outside the shared band are safe to retain.
    if any(x["bbox"][1] < end and x["bbox"][3] > start for x in spanning):
        return lines, "ambiguous"
    # Many aligned rows can be a table or matching exercise, not two columns.
    aligned = 0
    for a in left:
        for b in right:
            tolerance = max(2.0, min(a["bbox"][3] - a["bbox"][1], b["bbox"][3] - b["bbox"][1]) * 0.35)
            if abs(a["bbox"][1] - b["bbox"][1]) <= tolerance:
                aligned += 1
                break
    if aligned >= 0.5 * min(len(left), len(right)):
        return lines, "ambiguous"
    key = lambda x: (x["bbox"][1], x["bbox"][0])
    top = sorted((x for x in spanning if x["bbox"][3] <= start), key=key)
    bottom = sorted((x for x in spanning if x["bbox"][1] >= end), key=key)
    return top + sorted(left, key=key) + sorted(right, key=key) + bottom, "two_columns"
