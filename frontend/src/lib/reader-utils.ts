/** Pure geometry and selection helpers shared by the reader. */
export type PageGeometry = { scale: number; width: number; height: number; rotation: number };
export function overlayRect(b: [number, number, number, number], g: PageGeometry) {
  const rotate = (x: number, y: number) => {
    switch (g.rotation) {
      case 90: return [g.height - y, x];
      case 180: return [g.width - x, g.height - y];
      case 270: return [y, g.width - x];
      default: return [x, y];
    }
  };
  const points = [rotate(b[0], b[1]), rotate(b[2], b[1]), rotate(b[0], b[3]), rotate(b[2], b[3])];
  const xs = points.map((p) => p[0] * g.scale), ys = points.map((p) => p[1] * g.scale);
  return { left: Math.min(...xs), top: Math.min(...ys), width: Math.max(1, Math.max(...xs) - Math.min(...xs)), height: Math.max(1, Math.max(...ys) - Math.min(...ys)) };
}

export function fitScale(width: number, height: number, pageWidth: number, pageHeight: number, zoom: number) {
  return Math.max(0.05, Math.min((width - 24) / pageWidth, (height - 24) / pageHeight)) * zoom;
}

export function chooseLesson<T extends { id: string }>(lessons: T[], progress: Record<string, { locked?: boolean; last_visited_at?: string | null }>, requested: string | null): T | undefined {
  const open = lessons.filter((l) => !progress[l.id]?.locked);
  if (requested) {
    const selected = open.find((l) => l.id === requested);
    if (selected) return selected;
  }
  return [...open].filter((l) => progress[l.id]?.last_visited_at)
    .sort((a, b) => (progress[b.id].last_visited_at || "").localeCompare(progress[a.id].last_visited_at || ""))[0] || open[0];
}

/** Legacy proportional boxes are not safe to overlay; preserve their answers in cards. */
export function trustedBlank(b: { bbox: number[] | null; geometry?: string }): boolean {
  return (b.geometry === "native_chars" || b.geometry === "manual") && !!b.bbox && b.bbox.length === 4 && b.bbox.every(Number.isFinite);
}
