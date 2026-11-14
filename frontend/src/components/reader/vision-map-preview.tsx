"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { PreviewExercise, type PreviewExerciseData } from "./preview-exercise";
import { validPicture } from "./pdf-picture-crops";
import { autoLocatePictures, isPictureExercise, MAX_PICTURE_CALLS } from "./auto-picture-locations";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";

type Topic = { title: string; page_start: number | null; page_end: number | null;
  evidence_pages: number[]; content_types: string[]; uncertainty: string };
type Result = { sampled_pages: number[]; total_pages: number; partial: boolean; title: string;
  author: string; topics: Topic[]; warnings: string[]; provider: string; model: string };
type TopicResult = { topic: string; sampled_pages: number[]; provider: string; model: string; warnings: string[];
  theory: { text: string; evidence_pages: number[] }[];
  exercises: PreviewExerciseData[] };

function pagesContain(pages: number[], page: number) { return pages.includes(page); }

function parsePages(text: string, pageCount: number): number[] | null {
  const tokens = text.split(",").map((s) => s.trim());
  const numbers = tokens.map(Number);
  if (tokens.some((s) => !/^\d+$/.test(s)) || numbers.length > 5 || new Set(numbers).size !== numbers.length ||
      numbers.some((n) => !Number.isSafeInteger(n) || n < 1 || n > pageCount)) return null;
  return numbers;
}

export function VisionMapPreview({ bookId, pageCount, initialTopicCount = 2 }: { bookId: string; pageCount: number; initialTopicCount?: number }) {
  const { me } = useAuth();
  const storageKey = me ? `lingora.vision-map.${me.id}.${bookId}` : "";
  const [storageError, setStorageError] = useState("");
  const [pages, setPages] = useState(Array.from({ length: Math.min(5, pageCount) }, (_, i) => i + 1).join(", "));
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [topicBusy, setTopicBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [selected, setSelected] = useState<number[]>([]);

  useEffect(() => {
    setResult(null); setSelected([]);
    if (!storageKey) return;
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const data = JSON.parse(saved) as Result;
        if (Array.isArray(data.topics)) { setResult(data); setSelected(data.topics.map((_, i) => i)); }
      }
    } catch { setStorageError("Brauzerdagi xaritani tiklab bo'lmadi."); }
  }, [storageKey]);

  async function run() {
    if (!consent) return;
    const numbers = parsePages(pages, pageCount);
    if (!numbers) { setError(`1–5 ta takrorlanmagan sahifa kiriting (1–${pageCount}).`); return; }
    if (result && !window.confirm("Yangi xarita joriy xarita tanlovini almashtiradi. Davom etasizmi?")) return;
    setBusy(true); setError("");
    try {
      const data = await post<Result>(`/books/${bookId}/vision-map/preview`,
        { page_numbers: numbers, consent_images_to_provider: true });
      setResult(data);
      try { if (!storageKey) throw new Error(); localStorage.setItem(storageKey, JSON.stringify(data)); setStorageError(""); }
      catch { setStorageError("Xaritani brauzerda saqlab bo'lmadi."); }
      setSelected(data.topics.slice(0, Math.max(1, Math.min(20, initialTopicCount))).map((_, i) => i));
    } catch (e) { setError(e instanceof Error ? e.message : "Vision sinovi bajarilmadi."); }
    finally { setBusy(false); }
  }

  return <section className="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm dark:border-indigo-900 dark:bg-indigo-950/30">
    <h3 className="font-semibold">Vision AI: qisman kitob xaritasini sinash</h3>
    <p className="mt-1 text-slate-600 dark:text-slate-300">Muqova va mundarijaga yaqin 1–5 ta PDF sahifasini tanlang. Bu butun kitob xaritasi emas; mavzu chegaralari taxminiy. Oldingi kitob ma'lumotlari o'zgarmaydi.</p>
    <label className="mt-3 block">PDF sahifalari (vergul bilan)
      <input className="mt-1 block w-full max-w-sm rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" value={pages} disabled={busy || topicBusy} onChange={(e) => { setPages(e.target.value); setConsent(false); }} />
    </label>
    <label className="mt-3 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy || topicBusy} onChange={(e) => setConsent(e.target.checked)} />
      <span>Tanlangan sahifalar rasmlari sozlangan tashqi Vision AI xizmatiga yuborilishiga roziman. Provayder ma'lumotni qayta ishlashi va haq olishi mumkin; maxfiy yoki yuborishga huquqim bo'lmagan sahifalarni tanlamayman.</span>
    </label>
    <Button className="mt-3" variant="secondary" size="sm" disabled={!consent || busy || topicBusy || !pageCount} onClick={run}>{busy ? "Vision AI tahlil qilmoqda..." : "Tanlangan sahifalarni sinash"}</Button>
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    {result && <div className="mt-3 rounded-lg bg-white p-3 dark:bg-slate-900">
      <p className="font-medium">Qisman, tekshirilmagan natija · {result.provider} / {result.model}</p>
      <p className="text-xs">Yuborilgan PDF sahifalari: {result.sampled_pages.join(", ")} / {result.total_pages}. Xarita shu brauzerda saqlanadi.</p>
      <p className="mt-2">Nomi: {result.title || "aniqlanmadi"} · Muallif: {result.author || "aniqlanmadi"}</p>
      <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">Dastlabki tanlov faqat qulaylik uchun; bu shaxsiy AI tavsiyasi emas. Tanlov serverga saqlanmaydi. Har bir mavzu uchun sahifalarni alohida tasdiqlang va sinang.</p>
      {!result.topics.length && <p className="mt-2">Tanlangan sahifalarda mavzu aniqlanmadi; boshqa sahifalarni sinang.</p>}
      {result.topics.map((topic, i) => <label key={i} className="mt-2 flex items-start gap-2 border-t border-slate-200 pt-2 dark:border-slate-700">
        <input type="checkbox" checked={selected.includes(i)} disabled={topicBusy || busy} onChange={(e) => setSelected(e.target.checked ? [...selected, i] : selected.filter((v) => v !== i))} />
        <span><strong>{topic.title}</strong><br />PDF chegaralari: {topic.page_start ?? "noma'lum"}–{topic.page_end ?? "noma'lum"} · Manba sahifalari: {topic.evidence_pages.join(", ")}<br />
          Turlari: {topic.content_types.join(", ") || "aniqlanmadi"} · {topic.uncertainty || "AI qo'shimcha noaniqlik bildirmadi; tekshiring."}</span>
      </label>)}
      {result.warnings.map((w, i) => <p key={i} className="mt-1 text-xs text-amber-700 dark:text-amber-300">{w}</p>)}
      {storageError && <p role="alert" className="text-red-600">{storageError}</p>}
      {result.topics.map((topic, i) => <div key={i} hidden={!selected.includes(i)}>
        <TopicSample bookId={bookId} pageCount={pageCount} topic={topic} active={selected.includes(i)} busy={busy || topicBusy} setBusy={setTopicBusy} />
      </div>)}
    </div>}
  </section>;
}

function TopicSample({ bookId, pageCount, topic, active, busy, setBusy }: { bookId: string; pageCount: number; topic: Topic; active: boolean; busy: boolean; setBusy: (value: boolean) => void }) {
  const { me } = useAuth();
  const storageKey = me ? `lingora.vision-topic.${me.id}.${bookId}.${encodeURIComponent(JSON.stringify([topic.title, topic.page_start, topic.page_end, topic.evidence_pages]))}` : "";
  const [pages, setPages] = useState("");
  const [answers, setAnswers] = useState<string[][]>([]);
  const [storageError, setStorageError] = useState("");
  const [revision, setRevision] = useState(0);
  const [consent, setConsent] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<TopicResult | null>(null);
  const [autoConsent, setAutoConsent] = useState(false);
  const [pictureStatus, setPictureStatus] = useState("");
  const generation = useRef(0);
  const latest = useRef({ result, answers, storageKey });
  latest.current = { result, answers, storageKey };

  useEffect(() => {
    const generationRef = generation;
    generationRef.current++;
    setResult(null); setAnswers([]); setConsent(false); setAutoConsent(false); setPictureStatus("");
    if (!storageKey) return () => { generationRef.current++; };
    try {
      const saved = localStorage.getItem(storageKey);
      if (saved) {
        const data = JSON.parse(saved) as { result: TopicResult; answers: string[][] };
        if (Array.isArray(data.result?.exercises) && Array.isArray(data.answers)) {
          setResult(data.result); setAnswers(data.answers); setPages(data.result.sampled_pages.join(", "));
        }
      }
    } catch { setStorageError("Brauzerdagi natijani tiklab bo'lmadi."); }
    return () => { generationRef.current++; };
  }, [storageKey]);

  function saveLocally(nextResult: TopicResult, nextAnswers: string[][]) {
    try {
      if (!storageKey) throw new Error();
      localStorage.setItem(storageKey, JSON.stringify({ result: nextResult, answers: nextAnswers }));
      setStorageError("");
    } catch { setStorageError("Brauzerga saqlab bo'lmadi; sahifani yopmang va xotira sozlamalarini tekshiring."); }
  }

  async function findAutomaticPictures(data: TopicResult, runGeneration: number) {
    const isCurrent = () => generation.current === runGeneration;
    const outcome = await autoLocatePictures(bookId, data, {
      isCurrent,
      onUpdate: (next, processed, total) => {
        if (!isCurrent()) return;
        const current = latest.current;
        if (!current.result || current.storageKey !== storageKey) return;
        // Preserve edits made while a provider request was in flight, including manual crops.
        const merged = { ...current.result, exercises: current.result.exercises.map((ex, i) => ({ ...ex,
          questions: ex.questions.map((q, j) => {
            const candidate = next.exercises[i]?.questions[j]?.picture;
            return !validPicture(q, current.result!.sampled_pages) && candidate && validPicture({ ...q, picture: candidate }, current.result!.sampled_pages)
              ? { ...q, picture: candidate } : q;
          }) })) };
        latest.current = { ...current, result: merged };
        setResult(merged); saveLocally(merged, current.answers);
        setPictureStatus(`Rasmlar aniqlanmoqda: ${processed}/${total} mashq.`);
      },
    });
    if (!isCurrent()) return;
    const extra = outcome.remaining ? ` Yana ${outcome.remaining} ta mashq qoldi; har birida AI bilan qidirish mumkin.` : "";
    setPictureStatus(outcome.failed
      ? `Rasm qidirish to'xtadi; ${outcome.added} ta rasm qo'shildi. Saqlangan mashq va javoblar o'zgarmadi. Qayta urinib ko'ring.${extra}`
      : outcome.attempted
        ? `${outcome.added} ta rasm topildi. AI joylashuvini asl sahifa bilan solishtiring.${extra}`
        : "Qo'shimcha rasm qidirishni talab qiladigan mashq aniqlanmadi.");
  }

  async function run() {
    if (!consent || busy) return;
    const numbers = parsePages(pages, pageCount);
    if (!numbers) { setError(`1–5 ta takrorlanmagan sahifa kiriting (1–${pageCount}).`); return; }
    if (result && !window.confirm("Qayta sinash ushbu mavzudagi saqlangan natija va javoblarni almashtiradi. Davom etasizmi?")) return;
    setWorking(true); setBusy(true); setError(""); setPictureStatus("");
    const runGeneration = generation.current;
    try {
      const data = await post<TopicResult>(`/books/${bookId}/vision-topic/preview`,
        { page_numbers: numbers, topic: topic.title, consent_images_to_provider: true });
      if (generation.current !== runGeneration) return;
      const empty = data.exercises.map((ex) => ex.questions.map(() => ""));
      latest.current = { result: data, answers: empty, storageKey };
      setResult(data); setAnswers(empty); setRevision((n) => n + 1); saveLocally(data, empty);
      await findAutomaticPictures(data, runGeneration);
    } catch (e) { if (generation.current === runGeneration) setError(e instanceof Error ? e.message : "Mavzu sinovi bajarilmadi."); }
    finally { if (generation.current === runGeneration) setWorking(false); setBusy(false); }
  }
  async function locateSaved() {
    if (!autoConsent || !result || busy) return;
    setWorking(true); setBusy(true); setPictureStatus("");
    const runGeneration = generation.current;
    try { await findAutomaticPictures(result, runGeneration); }
    finally { if (generation.current === runGeneration) setWorking(false); setBusy(false); }
  }
  const hasMissingPictures = result?.exercises.some((ex) => isPictureExercise(ex, result.sampled_pages) && ex.questions.some((q) => !validPicture(q, result.sampled_pages)));
  return <div className="mt-4 border-t border-slate-300 pt-3 dark:border-slate-700">
    <h4 className="font-semibold">«{topic.title}»: sahifalarni sinash</h4>
    <p className="mt-1 text-xs">1–5 ta sahifani belgilang. Bu butun mavzuning yakuniy tahlili emas; davom etuvchi mashq uchun qo'shni sahifalarni ham tanlang. Natija va javoblar faqat shu qurilma brauzerida saqlanadi; boshqa qurilmaga ko'chmaydi. Umumiy qurilmada boshqalar ularni ko'rishi mumkin.</p>
    <label className="mt-2 block">Mavzu PDF sahifalari (vergul bilan)
      <input value={pages} disabled={busy} onChange={(e) => { setPages(e.target.value); setConsent(false); }} className="mt-1 block w-full max-w-sm rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" />
    </label>
    <label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />Tanlangan sahifalar rasmlari tashqi Vision AI xizmatiga yuborilishiga roziman. Rasmli mashqlarni avtomatik bog'lash uchun sahifalar va mashq matnlari yana yuborilishi mumkin (ko'pi bilan {MAX_PICTURE_CALLS} qo'shimcha so'rov); provayder haq olishi mumkin.</label>
    <Button className="mt-2" size="sm" variant="secondary" disabled={!consent || busy} onClick={run}>{working ? "AI tahlil qilmoqda..." : "Mavzu sahifalarini sinash"}</Button>
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    {result && <div className="mt-3" role="status">
      <p className="font-medium">AI taxmini: {result.exercises.length} ta mashq · {result.provider} / {result.model}</p>
      <p className="text-xs text-amber-700 dark:text-amber-300">Faqat sahifalar: {result.sampled_pages.join(", ")}. AI xato qilishi mumkin — asl PDF bilan tekshiring. Javob kaliti yaratilmaydi.</p>
      {!result.theory.length && <p className="mt-1 text-xs">Nazariya aniqlanmadi.</p>}
      {result.theory.map((t, i) => <p key={i} className="mt-2 text-xs">Nazariya ({t.evidence_pages.join(", ")}): {t.text}</p>)}
      {!result.exercises.length && <p className="mt-1 text-xs">Mashq aniqlanmadi.</p>}
      {storageError && <p role="alert" className="text-red-600">{storageError}</p>}
      {pictureStatus && <p role="status" className="mt-2 text-xs text-indigo-700 dark:text-indigo-300">{pictureStatus}</p>}
      {hasMissingPictures && <div className="mt-3 rounded-xl bg-indigo-50 p-3 text-xs dark:bg-indigo-950/40">
        <p className="font-semibold">Saqlangan mashqlarda rasmlarni avtomatik topish</p>
        <p className="mt-1">Mavjud savol va javoblar saqlanadi. Rasm joylashuvini aniqlash uchun har safar ko'pi bilan {MAX_PICTURE_CALLS} ta mashq yuboriladi; javoblaringiz yuborilmaydi.</p>
        <label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={autoConsent} disabled={busy} onChange={(e) => setAutoConsent(e.target.checked)} />PDF {result.sampled_pages.join(", ")}-sahifalari va mashq matnlarini tashqi AI xizmatiga qayta yuborishga roziman; xizmat haq olishi mumkin.</label>
        <Button type="button" size="sm" variant="secondary" className="mt-2" disabled={!autoConsent || busy} onClick={locateSaved}>Rasmlarni avtomatik topish</Button>
      </div>}
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => {
        if (!window.confirm("Ushbu brauzerdagi mavzu natijasi va javoblarini o'chirasizmi?")) return;
        try { localStorage.removeItem(storageKey); setResult(null); setAnswers([]); setStorageError(""); }
        catch { setStorageError("Brauzerdagi ma'lumotni o'chirib bo'lmadi."); }
      }}>Bu mavzuning mahalliy ma'lumotlarini o'chirish</Button>
      {result.exercises.map((ex, i) => <PreviewExercise key={`${revision}-${i}`} bookId={bookId} ex={ex} pages={result.sampled_pages} answers={answers[i] || []}
        active={active} externalBusy={busy}
        onPicturesChange={(updates) => {
          const current = latest.current;
          if (!current.result || current.storageKey !== storageKey || current.result.exercises[i] !== ex) return;
          const questions = ex.questions.map((q, j) => {
            const update = updates.find((item) => item.index === j);
            if (!update || !pagesContain(current.result!.sampled_pages, update.picture.page)) return q;
            const evidence_pages = Array.from(new Set([...q.evidence_pages, update.picture.page]));
            return validPicture({ ...q, evidence_pages, picture: update.picture }, current.result!.sampled_pages)
              ? { ...q, evidence_pages, picture: update.picture } : q;
          });
          const next = { ...current.result, exercises: current.result.exercises.map((item, j) => j === i ? { ...item, questions } : item) };
          latest.current = { ...current, result: next };
          setResult(next); saveLocally(next, current.answers);
        }}
        onChange={(values) => { const current = latest.current;
          if (!current.result || current.storageKey !== storageKey) return;
          const next = current.result.exercises.map((_, j) => j === i ? values : (current.answers[j] || []));
          latest.current = { ...current, answers: next };
          setAnswers(next); saveLocally(current.result, next); }} />)}
      {result.warnings.map((w, i) => <p key={i} className="mt-1 text-xs">{w}</p>)}
    </div>}
  </div>;
}
