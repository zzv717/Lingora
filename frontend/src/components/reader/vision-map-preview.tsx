"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";

type Topic = { title: string; page_start: number | null; page_end: number | null;
  evidence_pages: number[]; content_types: string[]; uncertainty: string };
type Result = { sampled_pages: number[]; total_pages: number; partial: boolean; title: string;
  author: string; topics: Topic[]; warnings: string[]; provider: string; model: string };
type TopicResult = { topic: string; sampled_pages: number[]; provider: string; model: string; warnings: string[];
  theory: { text: string; evidence_pages: number[] }[];
  exercises: { number: string; instruction: string; exercise_type: string; context: string; uncertainty: string;
    evidence_pages: number[]; questions: { number: string; prompt: string; options: string[]; evidence_pages: number[] }[] }[] };

function parsePages(text: string, pageCount: number): number[] | null {
  const tokens = text.split(",").map((s) => s.trim());
  const numbers = tokens.map(Number);
  if (tokens.some((s) => !/^\d+$/.test(s)) || numbers.length > 5 || new Set(numbers).size !== numbers.length ||
      numbers.some((n) => !Number.isSafeInteger(n) || n < 1 || n > pageCount)) return null;
  return numbers;
}

export function VisionMapPreview({ bookId, pageCount, initialTopicCount = 2 }: { bookId: string; pageCount: number; initialTopicCount?: number }) {
  const [pages, setPages] = useState(Array.from({ length: Math.min(5, pageCount) }, (_, i) => i + 1).join(", "));
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [topicBusy, setTopicBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [selected, setSelected] = useState<number[]>([]);

  async function run() {
    if (!consent) return;
    const numbers = parsePages(pages, pageCount);
    if (!numbers) { setError(`1–5 ta takrorlanmagan sahifa kiriting (1–${pageCount}).`); return; }
    if (result && !window.confirm("Yangi xarita avvalgi vaqtinchalik sinov natijalari va javoblarni o'chiradi. Davom etasizmi?")) return;
    setBusy(true); setError(""); setResult(null); setSelected([]);
    try {
      const data = await post<Result>(`/books/${bookId}/vision-map/preview`,
        { page_numbers: numbers, consent_images_to_provider: true });
      setResult(data);
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
      <p className="text-xs">Yuborilgan PDF sahifalari: {result.sampled_pages.join(", ")} / {result.total_pages}. Natija saqlanmaydi.</p>
      <p className="mt-2">Nomi: {result.title || "aniqlanmadi"} · Muallif: {result.author || "aniqlanmadi"}</p>
      <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">Dastlabki tanlov faqat qulaylik uchun; bu shaxsiy AI tavsiyasi emas. Tanlov va javoblar saqlanmaydi. Har bir mavzu uchun sahifalarni alohida tasdiqlang va sinang.</p>
      {!result.topics.length && <p className="mt-2">Tanlangan sahifalarda mavzu aniqlanmadi; boshqa sahifalarni sinang.</p>}
      {result.topics.map((topic, i) => <label key={i} className="mt-2 flex items-start gap-2 border-t border-slate-200 pt-2 dark:border-slate-700">
        <input type="checkbox" checked={selected.includes(i)} disabled={topicBusy || busy} onChange={(e) => setSelected(e.target.checked ? [...selected, i] : selected.filter((v) => v !== i))} />
        <span><strong>{topic.title}</strong><br />PDF chegaralari: {topic.page_start ?? "noma'lum"}–{topic.page_end ?? "noma'lum"} · Manba sahifalari: {topic.evidence_pages.join(", ")}<br />
          Turlari: {topic.content_types.join(", ") || "aniqlanmadi"} · {topic.uncertainty || "AI qo'shimcha noaniqlik bildirmadi; tekshiring."}</span>
      </label>)}
      {result.warnings.map((w, i) => <p key={i} className="mt-1 text-xs text-amber-700 dark:text-amber-300">{w}</p>)}
      {result.topics.map((topic, i) => <div key={i} hidden={!selected.includes(i)}>
        <TopicSample bookId={bookId} pageCount={pageCount} topic={topic} busy={busy || topicBusy} setBusy={setTopicBusy} />
      </div>)}
    </div>}
  </section>;
}

function TopicSample({ bookId, pageCount, topic, busy, setBusy }: { bookId: string; pageCount: number; topic: Topic; busy: boolean; setBusy: (value: boolean) => void }) {
  const [pages, setPages] = useState("");
  const [consent, setConsent] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<TopicResult | null>(null);

  async function run() {
    if (!consent || busy) return;
    const numbers = parsePages(pages, pageCount);
    if (!numbers) { setError(`1–5 ta takrorlanmagan sahifa kiriting (1–${pageCount}).`); return; }
    if (result && !window.confirm("Qayta sinash ushbu mavzudagi vaqtinchalik natija va javoblarni o'chiradi. Davom etasizmi?")) return;
    setWorking(true); setBusy(true); setError(""); setResult(null);
    try {
      setResult(await post<TopicResult>(`/books/${bookId}/vision-topic/preview`,
        { page_numbers: numbers, topic: topic.title, consent_images_to_provider: true }));
    } catch (e) { setError(e instanceof Error ? e.message : "Mavzu sinovi bajarilmadi."); }
    finally { setWorking(false); setBusy(false); }
  }
  return <div className="mt-4 border-t border-slate-300 pt-3 dark:border-slate-700">
    <h4 className="font-semibold">«{topic.title}»: sahifalarni sinash</h4>
    <p className="mt-1 text-xs">1–5 ta sahifani belgilang. Bu butun mavzuning yakuniy tahlili emas; davom etuvchi mashq uchun qo'shni sahifalarni ham tanlang. Natija va javoblar saqlanmaydi, tekshirilmaydi.</p>
    <label className="mt-2 block">Mavzu PDF sahifalari (vergul bilan)
      <input value={pages} disabled={busy} onChange={(e) => { setPages(e.target.value); setConsent(false); }} className="mt-1 block w-full max-w-sm rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" />
    </label>
    <label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />Bu sahifalar rasmlarini tashqi Vision AI xizmatiga yuborishga roziman; provayder haq olishi mumkin.</label>
    <Button className="mt-2" size="sm" variant="secondary" disabled={!consent || busy} onClick={run}>{working ? "AI tahlil qilmoqda..." : "Mavzu sahifalarini sinash"}</Button>
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    {result && <div className="mt-3" role="status">
      <p className="font-medium">AI taxmini: {result.exercises.length} ta mashq · {result.provider} / {result.model}</p>
      <p className="text-xs text-amber-700 dark:text-amber-300">Faqat sahifalar: {result.sampled_pages.join(", ")}. AI xato qilishi mumkin — asl PDF bilan tekshiring. Javob kaliti yaratilmaydi.</p>
      {!result.theory.length && <p className="mt-1 text-xs">Nazariya aniqlanmadi.</p>}
      {result.theory.map((t, i) => <p key={i} className="mt-2 text-xs">Nazariya ({t.evidence_pages.join(", ")}): {t.text}</p>)}
      {!result.exercises.length && <p className="mt-1 text-xs">Mashq aniqlanmadi.</p>}
      {result.exercises.map((ex, i) => <div key={i} className="mt-3 border-t border-slate-200 pt-2 dark:border-slate-700">
        <p className="font-medium">Mashq {ex.number || "raqami noma'lum"} · {ex.exercise_type} · {ex.questions.length} savol · sahifa {ex.evidence_pages.join(", ")}</p>
        <p>{ex.instruction}</p>{ex.context && <p className="mt-1 whitespace-pre-wrap">{ex.context}</p>}
        {ex.uncertainty && <p className="text-xs text-amber-700 dark:text-amber-300">Noaniqlik: {ex.uncertainty}</p>}
        {ex.questions.map((q, j) => <label key={j} className="my-2 block rounded border border-slate-200 p-2 text-xs dark:border-slate-700">
          <span>{q.number ? `${q.number}. ` : ""}{q.prompt}</span>{q.options.map((opt, k) => <span key={k} className="block">{opt}</span>)}
          <span className="block text-slate-500">Vaqtinchalik javob (saqlanmaydi, tekshirilmaydi)</span><textarea rows={2} className="mt-1 block w-full rounded border border-slate-300 bg-white p-1 dark:border-slate-600 dark:bg-slate-800" />
        </label>)}
      </div>)}
      {result.warnings.map((w, i) => <p key={i} className="mt-1 text-xs">{w}</p>)}
    </div>}
  </div>;
}
