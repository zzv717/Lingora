export function previewColumns(width: number, height: number) {
  const mid = Math.floor(width / 2);
  return [{ x: 0, y: 0, width: mid, height }, { x: mid, y: 0, width: width - mid, height }];
}

export function offsetOcrBox(box: { x0: number; y0: number; x1: number; y1: number }, x: number, y: number) {
  return { x0: box.x0 + x, y0: box.y0 + y, x1: box.x1 + x, y1: box.y1 + y };
}

/** Convert canvas coordinates to unrotated, crop-relative PDF points (top-left origin). */
export function ocrBoxToPdf(
  box: { x0: number; y0: number; x1: number; y1: number },
  viewport: { convertToPdfPoint: (x: number, y: number) => number[] },
  view: number[],
): [number, number, number, number] {
  const points = [
    viewport.convertToPdfPoint(box.x0, box.y0), viewport.convertToPdfPoint(box.x1, box.y0),
    viewport.convertToPdfPoint(box.x0, box.y1), viewport.convertToPdfPoint(box.x1, box.y1),
  ].map(([x, y]) => [x - view[0], view[3] - y]);
  const clamp = (value: number, max: number) => Math.min(max, Math.max(0, value));
  const xs = points.map((p) => clamp(p[0], view[2] - view[0]));
  const ys = points.map((p) => clamp(p[1], view[3] - view[1]));
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
