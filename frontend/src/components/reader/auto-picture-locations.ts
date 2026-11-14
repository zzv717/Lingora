import { post } from "@/lib/api";
import { validPicture, type PictureRegion } from "./pdf-picture-crops";
import type { PreviewExerciseData } from "./preview-exercise";

// Each call sends the consented pages again. Keep time, cost and provider load bounded.
export const MAX_PICTURE_CALLS = 5;
type TopicResult = { sampled_pages: number[]; exercises: PreviewExerciseData[] };
type LocateResponse = { locations: { index: number; picture: PictureRegion }[] };

function picturePriority(ex: PreviewExerciseData, pages: number[]): number {
  if (ex.depends_on_picture === true || /\b(picture|pictures|image|images|illustration|photo|photos|drawing|drawings)\b|rasm/i.test(ex.instruction) || ex.questions.some((q) => !!validPicture(q, pages))) return 2;
  // Old saved previews may have no explicit picture metadata, just numbered empty prompts.
  return ex.questions.some((q) => /^[.\s_…-]*$/.test(q.prompt)) ? 1 : 0;
}
export function isPictureExercise(ex: PreviewExerciseData, pages: number[]): boolean {
  return picturePriority(ex, pages) > 0;
}

/** Explicitly consented scan only; caller commits each successful batch immediately. */
export async function autoLocatePictures<T extends TopicResult>(bookId: string, initial: T, opts: {
  isCurrent: () => boolean;
  onUpdate: (result: T, processed: number, total: number) => void;
}): Promise<{ result: T; attempted: number; added: number; remaining: number; failed: boolean; cancelled: boolean }> {
  let current = initial, attempted = 0, added = 0, failed = false;
  const candidates = initial.exercises.map((ex, i) => ({ ex, i, priority: picturePriority(ex, initial.sampled_pages) })).filter(({ ex, priority }) => ex.questions.length > 0 &&
    priority > 0 && ex.questions.some((q) => !validPicture(q, initial.sampled_pages)))
    .sort((a, b) => b.priority - a.priority || a.i - b.i);
  const chosen = candidates.slice(0, MAX_PICTURE_CALLS);
  for (const { i } of chosen) {
    if (!opts.isCurrent()) return { result: current, attempted, added, remaining: candidates.length - attempted, failed, cancelled: true };
    const ex = current.exercises[i];
    attempted++;
    try {
      const response = await post<LocateResponse>(`/books/${bookId}/vision-topic/pictures`, {
        page_numbers: current.sampled_pages, consent_images_to_provider: true, number: ex.number, instruction: ex.instruction,
        questions: ex.questions.map((q) => ({ number: q.number, prompt: q.prompt, evidence_pages: q.evidence_pages })),
      });
      if (!opts.isCurrent()) return { result: current, attempted, added, remaining: candidates.length - attempted, failed, cancelled: true };
      if (!Array.isArray(response.locations)) throw new Error("invalid locations");
      const seen = new Set<number>(), duplicates = new Set<number>();
      for (const item of response.locations) {
        if (seen.has(item.index)) duplicates.add(item.index);
        seen.add(item.index);
      }
      const questions = ex.questions.map((q, index) => {
        if (validPicture(q, current.sampled_pages) || duplicates.has(index)) return q;
        const item = response.locations.find((loc) => loc.index === index);
        if (!item || !validPicture({ ...q, picture: item.picture }, current.sampled_pages)) return q;
        added++;
        return { ...q, picture: item.picture };
      });
      current = { ...current, exercises: current.exercises.map((item, j) => j === i ? { ...item, questions } : item) };
      opts.onUpdate(current, attempted, chosen.length);
    } catch {
      failed = true;
      break; // Avoid spending more or repeating provider/rate errors.
    }
  }
  return { result: current, attempted, added, remaining: candidates.length - attempted, failed, cancelled: false };
}
