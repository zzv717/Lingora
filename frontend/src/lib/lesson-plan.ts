export type PlanOption = {
  id: string;
  progress: { locked: boolean; status: string; last_visited_at: string | null };
};

/** A transparent rule-based suggestion, not an AI recommendation. */
export function suggestLessons<T extends PlanOption>(lessons: T[], count: number): string[] {
  const rank = (status: string) => status === "in_progress" ? 0 : status === "not_started" ? 1 : status === "exercises_done" ? 2 : 3;
  return lessons.map((lesson, index) => ({ lesson, index }))
    .filter(({ lesson }) => !lesson.progress.locked)
    .sort((a, b) => rank(a.lesson.progress.status) - rank(b.lesson.progress.status) ||
      (b.lesson.progress.last_visited_at || "").localeCompare(a.lesson.progress.last_visited_at || "") || a.index - b.index)
    .slice(0, Math.max(0, Math.min(20, count))).map(({ lesson }) => lesson.id);
}

/** Never trust a plan from a URL: ignore duplicates, unknown IDs and locked lessons. */
export function validPlan<T extends { id: string }>(raw: string | null, lessons: T[], progress: Record<string, { locked?: boolean }>): string[] {
  const known = new Set(lessons.map((lesson) => lesson.id));
  const seen = new Set<string>();
  return (raw || "").split(",").filter((id) => {
    if (!id || seen.has(id) || !known.has(id) || progress[id]?.locked) return false;
    seen.add(id);
    return true;
  }).slice(0, 20);
}

export function planUrl(bookId: string, lessonId: string, ids: string[]): string {
  const query = new URLSearchParams({ lesson: lessonId, plan: ids.join(",") });
  return `/reader/${encodeURIComponent(bookId)}?${query.toString()}`;
}
