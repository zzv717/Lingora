"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";
import { PdfViewer } from "./pdf-viewer";

export type PreviewExerciseData = { number: string; instruction: string; exercise_type: string; context: string; uncertainty: string;
  evidence_pages: number[]; questions: { number: string; prompt: string; options: string[]; evidence_pages: number[] }[] };
type Feedback = { index: number; correct: boolean | null; explanation_uz: string };

export function PreviewExercise({ bookId, ex, pages, answers, onChange }: {
  bookId: string; ex: PreviewExerciseData; pages: number[]; answers: string[]; onChange: (values: string[]) => void;
}) {
  const [showPage, setShowPage] = useState(false);
  const [page, setPage] = useState(ex.evidence_pages[0] || pages[0]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback[] | null>(null);
  const [error, setError] = useState("");

  async function check() {
    if (!consent || busy || !answers.some((a) => a?.trim())) return;
    setBusy(true); setError(""); setFeedback(null);
    try {
      const r = await post<{ verdicts: Feedback[] }>(`/books/${bookId}/vision-topic/check`, {
        page_numbers: pages, consent_to_provider: true, number: ex.number, instruction: ex.instruction,
        context: ex.context, questions: ex.questions.map((q, i) => ({ number: q.number, prompt: q.prompt,
          options: q.options, answer: answers[i] || "" })),
      });
      setFeedback(r.verdicts);
    } catch (e) { setError(e instanceof Error ? e.message : "Tekshirish amalga oshmadi."); }
    finally { setBusy(false); }
  }
  return <div className="mt-3 border-t border-slate-200 pt-2 dark:border-slate-700">
    <p className="font-medium">Mashq {ex.number || "raqami noma'lum"} · {ex.exercise_type} · {ex.questions.length} savol · PDF sahifa {ex.evidence_pages.join(", ")}</p>
    <p>{ex.instruction}</p>{ex.context && <p className="mt-1 whitespace-pre-wrap">{ex.context}</p>}
    {ex.uncertainty && <p className="text-xs text-amber-700 dark:text-amber-300">Noaniqlik: {ex.uncertainty}</p>}
    <Button className="mt-2" variant="secondary" size="sm" onClick={() => setShowPage(!showPage)}>{showPage ? "PDF ni yashirish" : "Asl PDF va rasmlarni ko'rish"}</Button>
    {showPage && <div className="mt-2 h-[480px]"><PdfViewer bookId={bookId} pageNumber={page} onGoTo={setPage} /></div>}
    {ex.questions.map((q, i) => <div key={i} className="my-2 rounded border border-slate-200 p-2 text-xs dark:border-slate-700">
      <label><span>{q.number ? `${q.number}. ` : ""}{q.prompt || "Rasmga qarang"}</span>{q.options.map((opt, k) => <span key={k} className="block">{opt}</span>)}
        <span className="block text-slate-500">Javob (shu brauzerda saqlanadi)</span><textarea rows={2} maxLength={2000} disabled={busy} value={answers[i] || ""} onChange={(e) => {
          const next = ex.questions.map((_, j) => j === i ? e.target.value : (answers[j] || ""));
          onChange(next); setFeedback(null);
        }} className="mt-1 block w-full rounded border border-slate-300 bg-white p-1 dark:border-slate-600 dark:bg-slate-800" />
      </label>
      {feedback?.[i] && <p className="mt-1" role="status"><strong>{feedback[i].correct === null ? "Noaniq" : feedback[i].correct ? "AI: to'g'ri" : "AI: xato"}.</strong> {feedback[i].explanation_uz}</p>}
    </div>)}
    {ex.questions.length > 0 && <>
      <label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
        <span>PDF {pages.join(", ")}-sahifalari va ushbu mashq javoblarim tashqi AI xizmatiga yuborilishiga roziman. Xizmat ma'lumotdan foydalanishi yoki haq olishi mumkin.</span></label>
      <Button className="mt-2" size="sm" variant="secondary" disabled={!consent || busy || !answers.some((a) => a?.trim())} onClick={check}>{busy ? "Tekshirilmoqda..." : "AI bilan tekshirish"}</Button>
      <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">AI bahosi taxminiy, javob kaliti emas; asl sahifa bilan solishtiring. Baholar dars natijalariga qo'shilmaydi.</p>
    </>}
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
  </div>;
}
