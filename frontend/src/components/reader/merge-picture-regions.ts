import { validPicture } from "./pdf-picture-crops";
import type { PreviewExerciseData } from "./preview-exercise";

// Only attach new locations when both exercise and question identity match uniquely.
// Never replace original extracted content, answers, or previously found locations.
export function mergePictureRegions(current: PreviewExerciseData[], fresh: PreviewExerciseData[], pages: number[]) {
  const exKey = (ex: PreviewExerciseData) => JSON.stringify([ex.number.trim(), ex.instruction.trim(), [...ex.evidence_pages].sort((a, b) => a - b)]);
  const qKey = (q: PreviewExerciseData['questions'][number]) => JSON.stringify([q.number.trim(), q.prompt.trim(), [...q.evidence_pages].sort((a, b) => a - b)]);
  const occurrences = <T,>(items: T[], key: (value: T) => string, id: string) => items.filter((item) => key(item) === id);
  let added = 0;
  const exercises = current.map((ex) => {
    if (!ex.number.trim()) return ex;
    const id = exKey(ex);
    const candidates = occurrences(fresh, exKey, id);
    if (candidates.length !== 1 || occurrences(current, exKey, id).length !== 1) return ex;
    const candidate = candidates[0];
    return { ...ex, questions: ex.questions.map((q) => {
      if (validPicture(q, pages) || !q.number.trim()) return q;
      const qid = qKey(q);
      const matches = occurrences(candidate.questions, qKey, qid);
      if (matches.length !== 1 || occurrences(ex.questions, qKey, qid).length !== 1) return q;
      const picture = validPicture(matches[0], pages);
      if (!picture) return q;
      added++;
      return { ...q, picture };
    }) };
  });
  return { exercises, added };
}
