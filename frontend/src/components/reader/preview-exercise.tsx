"use client";

import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";
import { PdfViewer } from "./pdf-viewer";
import { Translator, type TranslationSeed } from "./translator";
import { usePdfPictureCrops, validPicture, type PictureRegion } from "./pdf-picture-crops";
import { PictureSelector } from "./picture-selector";
import { isPictureExercise } from "./auto-picture-locations";

export type PreviewExerciseData = { number: string; instruction: string; exercise_type: string; context: string; uncertainty: string;
  evidence_pages: number[]; depends_on_picture?: boolean; questions: { number: string; prompt: string; options: string[]; evidence_pages: number[]; picture?: PictureRegion | null }[] };
type Feedback = { index: number; correct: boolean | null; explanation_uz: string };

export function PreviewExercise({ bookId, ex, pages, answers, onChange, onPicturesChange, defaultShowPage = false, active = true, externalBusy = false }: {
  bookId: string; ex: PreviewExerciseData; pages: number[]; answers: string[]; onChange: (values: string[]) => void;
  onPicturesChange?: (updates: { index: number; picture: PictureRegion }[]) => void;
  defaultShowPage?: boolean; active?: boolean; externalBusy?: boolean;
}) {
  const [showPage, setShowPage] = useState(defaultShowPage);
  const sourceRef = useRef<HTMLDivElement>(null);
  const articleRef = useRef<HTMLElement>(null);
  const [nearViewport, setNearViewport] = useState(false);
  useEffect(() => {
    if (!articleRef.current) return;
    if (typeof IntersectionObserver === "undefined") { setNearViewport(true); return; }
    const observer = new IntersectionObserver(([entry]) => setNearViewport(entry.isIntersecting), { rootMargin: "800px" });
    observer.observe(articleRef.current);
    return () => observer.disconnect();
  }, []);
  const { pictures, error: pictureError } = usePdfPictureCrops(bookId, ex.questions, pages, nearViewport && active);
  const [page, setPage] = useState(ex.evidence_pages[0] || pages[0]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback[] | null>(null);
  const [error, setError] = useState("");
  const [translationSeed, setTranslationSeed] = useState<TranslationSeed>();
  const [selecting, setSelecting] = useState<number | null>(null);
  const [pictureConsent, setPictureConsent] = useState(false);
  const [locating, setLocating] = useState(false);
  const [pictureMessage, setPictureMessage] = useState("");
  const pictureExercise = isPictureExercise(ex, pages);
  const missingPictures = pictureExercise && ex.questions.some((q) => !validPicture(q, pages));
  async function locatePictures() {
    if (!pictureConsent || locating || busy || externalBusy || !onPicturesChange) return;
    setLocating(true); setPictureMessage("");
    try {
      const r = await post<{ locations: { index: number; picture: PictureRegion }[] }>(`/books/${bookId}/vision-topic/pictures`, {
        page_numbers: pages, consent_images_to_provider: true, number: ex.number, instruction: ex.instruction,
        questions: ex.questions.map((q) => ({ number: q.number, prompt: q.prompt, evidence_pages: q.evidence_pages })),
      });
      const updates = r.locations.filter(({ index, picture }) => Number.isInteger(index) && index >= 0 && index < ex.questions.length &&
        !validPicture(ex.questions[index], pages) && validPicture({ ...ex.questions[index], picture }, pages));
      onPicturesChange(updates);
      setPictureMessage(updates.length ? `${updates.length} ta rasm topildi. Joylashuvni asl sahifaga solishtiring.` : "AI rasm joyini ishonchli aniqlamadi. Savoldagi «Rasmni tanlash» bilan belgilang.");
    } catch (e) { setPictureMessage(e instanceof Error ? e.message : "Rasm joyini aniqlab bo'lmadi. Qo'lda tanlang."); }
    finally { setLocating(false); }
  }
  const prepareTranslation = (text: string) => setTranslationSeed((prev) => ({ text, id: (prev?.id || 0) + 1 }));

  async function check() {
    if (!consent || busy || externalBusy || !answers.some((a) => a?.trim())) return;
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
  const summary = feedback && ex.questions.reduce((counts, _, i) => {
    if (!answers[i]?.trim()) counts.unanswered++;
    else if (feedback[i]?.correct === true) counts.correct++;
    else if (feedback[i]?.correct === false) counts.wrong++;
    else counts.uncertain++;
    return counts;
  }, { correct: 0, wrong: 0, uncertain: 0, unanswered: 0 });

  const answeredCount = ex.questions.reduce((count, _, i) => count + (answers[i]?.trim() ? 1 : 0), 0);
  const progress = ex.questions.length ? Math.round(answeredCount / ex.questions.length * 100) : 0;
  const types: Record<string, string> = { cloze: "Bo'sh joyni to'ldirish", multiple_choice: "Variant tanlash", transformation: "Gapni o'zgartirish", error_correction: "Xatoni topish", matching: "Moslashtirish", categorization: "Guruhlash", dialogue: "Muloqot", writing: "Yozish", speaking: "Gapirish", other: "Mashq" };

  return <article ref={articleRef} className="mt-5 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900">
    <header className="relative overflow-hidden bg-gradient-to-br from-indigo-700 via-indigo-600 to-violet-600 px-4 py-5 text-white sm:px-6 sm:py-6">
      <div aria-hidden="true" className="pointer-events-none absolute -right-8 -top-14 h-40 w-40 rounded-full border-[24px] border-white/10" />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-[11px] font-bold uppercase tracking-[0.2em] text-indigo-100">O'rganish va mashq qilish</p>
          <h4 className="mt-1 text-xl font-bold sm:text-2xl">Mashq {ex.number || "raqami noma'lum"}</h4>
          <p className="mt-1 text-xs text-indigo-100">{types[ex.exercise_type] || "Mashq"} · PDF sahifa {ex.evidence_pages.join(", ")}</p></div>
        <div className="rounded-2xl border border-white/20 bg-white/10 px-4 py-2 text-right"><p className="text-lg font-bold">{answeredCount}<span className="text-sm font-normal text-indigo-100"> / {ex.questions.length}</span></p><p className="text-[11px] text-indigo-100">javob kiritildi</p></div>
      </div>
      <div className="relative mt-5 flex items-center gap-3"><div role="progressbar" aria-label="Javob kiritish jarayoni" aria-valuemin={0} aria-valuemax={ex.questions.length} aria-valuenow={answeredCount} className="h-2 flex-1 overflow-hidden rounded-full bg-white/20"><div className="h-full rounded-full bg-emerald-300 transition-all duration-300 motion-reduce:transition-none" style={{ width: `${progress}%` }} /></div><span className="text-xs font-semibold text-indigo-100">{progress}%</span></div>
      <p className="relative mt-1 text-[11px] text-indigo-100">Bu faqat to'ldirish jarayoni, baho emas.</p>
    </header>
    <div className="space-y-5 p-4 sm:p-6">
      <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-800/60">
        <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Topshiriq</p>
          {ex.instruction && <button type="button" onClick={() => prepareTranslation(ex.instruction)} className="rounded-lg px-2 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 dark:text-indigo-300 dark:hover:bg-indigo-900">Ko'rsatmani tarjima qilish ↗</button>}</div>
        <p className="mt-2 whitespace-pre-wrap text-sm font-medium leading-relaxed text-slate-800 dark:text-slate-100">{ex.instruction || "Ko'rsatma uchun asl PDF sahifasiga qarang."}</p>
        {ex.context && <p className="mt-3 whitespace-pre-wrap border-t border-slate-200 pt-3 text-sm leading-relaxed text-slate-600 dark:border-slate-700 dark:text-slate-300">{ex.context}</p>}
      </div>
      {ex.uncertainty && <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">Noaniqlik: {ex.uncertainty}</p>}
      <Translator seed={translationSeed} />
      {onPicturesChange && missingPictures && <div className="rounded-xl bg-indigo-50 px-4 py-3 text-xs text-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200">
        <p className="font-semibold">Rasmlar ko'rinmayaptimi?</p>
        <p className="mt-1">AI shu mashq rasmlarini topishga urinadi. Yoki har bir savolda rasmni o'zingiz tanlang. Javoblaringiz saqlanadi.</p>
        <label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={pictureConsent} disabled={locating || externalBusy} onChange={(e) => setPictureConsent(e.target.checked)} />PDF {pages.join(", ")}-sahifalari va mashq matnini tashqi AI xizmatiga yuborishga roziman; javoblar yuborilmaydi, xizmat haq olishi mumkin.</label>
        <Button type="button" size="sm" variant="secondary" className="mt-2" disabled={!pictureConsent || locating || busy || externalBusy} onClick={locatePictures}>{locating ? "Rasmlar qidirilmoqda…" : "Rasmlarni AI bilan topish"}</Button>
      </div>}
      {pictureMessage && <p className="text-xs text-slate-600 dark:text-slate-300" role="status">{pictureMessage}</p>}
      <div ref={sourceRef}><Button type="button" variant="secondary" size="sm" onClick={() => setShowPage(!showPage)} aria-expanded={showPage}>{showPage ? "PDF ni yashirish" : "Asl PDF va rasmlarni ko'rish"}</Button>
        {showPage && active && <><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Kitobning asl sahifasi. Matn va rasmlarni shu yerda o'zgartirmasdan ko'ring; quyidagi savollar AI talqini.</p>
          <div className="mt-3 h-[480px] overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">{nearViewport && <PdfViewer bookId={bookId} pageNumber={page} onGoTo={setPage} />}</div></>}
        {pictureError && <p role="alert" className="mt-2 text-xs text-amber-700 dark:text-amber-300">{pictureError}</p>}
      </div>
      <div className="space-y-3">{ex.questions.map((q, i) => {
        const verdict = feedback?.[i];
        const answered = !!answers[i]?.trim();
        return <div key={i} className={`rounded-2xl border p-4 transition-colors sm:p-5 ${verdict && answered && verdict.correct === true ? "border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20" : verdict && answered && verdict.correct === false ? "border-rose-300 bg-rose-50/40 dark:border-rose-800 dark:bg-rose-950/20" : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"}`}>
          <div className="flex items-start gap-3"><span className="grid h-9 min-w-9 shrink-0 place-items-center rounded-xl bg-indigo-100 px-2 text-sm font-bold text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200">{q.number || i + 1}</span>
            <div className="min-w-0 flex-1"><div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-start sm:gap-6"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-start justify-between gap-2"><p className="whitespace-pre-wrap text-sm font-semibold leading-relaxed text-slate-800 dark:text-slate-100">{q.prompt || "Rasmga qarang"}</p>
              {q.prompt && <button type="button" onClick={() => prepareTranslation(q.prompt)} className="rounded-lg px-2 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 dark:text-indigo-300 dark:hover:bg-indigo-950">Tarjima ↗</button>}</div>
              {validPicture(q, pages) && !pictures[i] && !pictureError && <p className="mt-2 text-xs text-slate-500">Asl rasm yuklanmoqda…</p>}
              <button type="button" onClick={() => { setPage(validPicture(q, pages)?.page || q.evidence_pages[0] || ex.evidence_pages[0] || pages[0]); setShowPage(true); setTimeout(() => sourceRef.current?.scrollIntoView?.({ block: "start" }), 0); }} className="mt-2 rounded-lg px-2 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 dark:text-indigo-300 dark:hover:bg-indigo-950">Asl sahifada ko'rish ↑</button>
              {q.options.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{q.options.map((opt, k) => ex.exercise_type === "multiple_choice" ? <button type="button" key={k} disabled={busy || externalBusy} aria-pressed={answers[i] === opt} onClick={() => { const next = ex.questions.map((_, j) => j === i ? opt : (answers[j] || "")); onChange(next); setFeedback(null); }} className={`rounded-xl border px-3 py-2 text-left text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 ${answers[i] === opt ? "border-indigo-500 bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-100" : "border-slate-200 text-slate-600 hover:border-indigo-300 dark:border-slate-600 dark:text-slate-300"}`}>{opt}</button> : <span key={k} className="rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">{opt}</span>)}</div>}
              <label className="mt-4 block text-xs font-semibold text-slate-500 dark:text-slate-400">Javob <span className="font-normal">· shu brauzerda saqlanadi</span>
                <textarea rows={2} maxLength={2000} disabled={busy || externalBusy} value={answers[i] || ""} onChange={(e) => {
                  const next = ex.questions.map((_, j) => j === i ? e.target.value : (answers[j] || "")); onChange(next); setFeedback(null);
                }} placeholder="Javobingizni shu yerga yozing…" className="mt-2 block w-full resize-y rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm font-normal text-slate-900 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-2 focus:ring-indigo-100 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:focus:ring-indigo-900" />
              </label>
              {verdict && <p className="mt-3 rounded-xl bg-white/80 p-3 text-xs leading-relaxed text-slate-700 dark:bg-slate-800 dark:text-slate-200" role="status"><strong>{!answered ? "Javob kiritilmagan" : verdict.correct === null ? "Noaniq" : verdict.correct ? "AI: to'g'ri" : "AI: xato"}.</strong> {verdict.explanation_uz}</p>}
            </div>
            {pictures[i] && <figure className="w-fit max-w-full shrink-0 sm:w-44"><img src={pictures[i]} alt={`${q.number || i + 1}-savol uchun asl PDFdan rasm qirqimi`} className="max-h-48 max-w-full rounded-lg object-contain sm:ml-auto" /><figcaption className="sr-only">Asl PDF qirqimi. AI tanlagan joyni asl sahifa bilan solishtiring.</figcaption></figure>}
            </div>
            {onPicturesChange && <button type="button" disabled={externalBusy || locating} onClick={() => setSelecting(selecting === i ? null : i)} className="mt-3 rounded-lg text-xs font-semibold text-indigo-700 hover:underline disabled:opacity-50 dark:text-indigo-300">{validPicture(q, pages) ? "Rasmni o'zgartirish" : "Rasmni tanlash"}</button>}
            {selecting === i && onPicturesChange && <PictureSelector bookId={bookId} pages={pages} initialPage={q.evidence_pages[0] || pages[0]} onCancel={() => setSelecting(null)} onSave={(picture) => { onPicturesChange([{ index: i, picture }]); setSelecting(null); }} />}
            </div>
          </div>
        </div>;
      })}</div>
      {ex.questions.length > 0 && <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-900 dark:bg-indigo-950/20">
        <p className="text-sm font-bold text-indigo-950 dark:text-indigo-100">Tayyor bo'ldingizmi?</p>
        <p className="mt-1 text-xs leading-relaxed text-indigo-800 dark:text-indigo-300">Javoblaringizni asl sahifa bilan birga AI yordamida tekshiring.</p>
        <label className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300"><input type="checkbox" className="mt-0.5" checked={consent} disabled={busy || externalBusy} onChange={(e) => setConsent(e.target.checked)} />
          <span>PDF {pages.join(", ")}-sahifalari va ushbu mashq javoblarim tashqi AI xizmatiga yuborilishiga roziman. Xizmat ma'lumotdan foydalanishi yoki haq olishi mumkin.</span></label>
        <Button className="mt-3" type="button" size="sm" disabled={!consent || busy || externalBusy || !answers.some((a) => a?.trim())} onClick={check}>{busy ? "Tekshirilmoqda..." : "AI bilan tekshirish"}</Button>
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">AI bahosi taxminiy, javob kaliti emas; asl sahifa bilan solishtiring. Baholar dars natijalariga qo'shilmaydi.</p>
      </div>}
      {error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{error}</p>}
      {summary && <div role="status" aria-label="Mashq natijasi" className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-700 dark:bg-slate-800">
        <p className="font-bold text-slate-900 dark:text-white">Ushbu mashq natijasi <span className="font-normal text-slate-500">· AI taxmini</span></p>
        <p className="mt-2 font-medium">To'g'ri: {summary.correct} · Xato: {summary.wrong} · Noaniq: {summary.uncertain} · Javob berilmagan: {summary.unanswered}</p>
        <p className="mt-1 text-xs text-slate-500">Jami: {ex.questions.length} ta savol. Noaniq va javob berilmagan savollar to'g'ri yoki xato hisobiga kirmaydi.</p>
      </div>}
    </div>
  </article>;
}
