"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { post } from "@/lib/api";
import { Button, Spinner } from "@/components/ui";
import { PreviewExercise, type PreviewExerciseData } from "./preview-exercise";

/**
 * One screen, one consent, one action: scan a few pages once, then switch between the
 * detected topics and their exercises without re-scanning or asking for consent again.
 * Everything stays browser-local; no learning data is written by this screen.
 */

type Topic = { title: string; page_start: number | null; page_end: number | null;
  evidence_pages: number[]; content_types: string[]; uncertainty: string };
type MapResult = { sampled_pages: number[]; total_pages: number; partial: boolean; title: string;
  author: string; topics: Topic[]; warnings: string[]; provider: string; model: string };
type TopicResult = { topic: string; sampled_pages: number[]; provider: string; model: string; warnings: string[];
  theory: { text: string; evidence_pages: number[] }[];
  exercises: PreviewExerciseData[] };
type TopicEntry = { result: TopicResult; answers: string[][] };

const CONSENT_HINT = "Mashqlarni yaratish uchun yuqoridagi rozilik katakchasini belgilang.";

function defaultPages(pageCount: number) {
  return Array.from({ length: Math.min(3, pageCount) }, (_, i) => i + 1).join(", ");
}

/** Accepts comma separated pages and small ranges such as "1-5, 10"; at most five pages. */
export function parsePages(text: string, pageCount: number): number[] | null {
  const tokens = text.split(/[,;]+/).map((s) => s.trim()).filter(Boolean);
  const numbers: number[] = [];
  for (const token of tokens) {
    const range = /^(\d+)\s*[-–]\s*(\d+)$/.exec(token);
    if (range) {
      const from = Number(range[1]), to = Number(range[2]);
      if (from > to || to - from > 4) return null;
      for (let n = from; n <= to; n++) numbers.push(n);
      continue;
    }
    if (!/^\d+$/.test(token)) return null;
    numbers.push(Number(token));
  }
  if (!numbers.length || numbers.length > 5) return null;
  if (new Set(numbers).size !== numbers.length) return null;
  if (numbers.some((n) => !Number.isSafeInteger(n) || n < 1 || n > pageCount)) return null;
  return numbers;
}

export function InfoHint({ text }: { text: string }) {
  return <span className="group relative inline-flex align-middle">
    <button type="button" aria-label={`Qo'shimcha ma'lumot: ${text}`}
      className="grid h-5 w-5 place-items-center rounded-full border border-slate-300 text-[11px] font-bold text-slate-500 transition hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800">i</button>
    <span role="tooltip" className="pointer-events-none absolute left-1/2 top-7 z-20 hidden w-64 -translate-x-1/2 rounded-xl border border-slate-200 bg-white p-3 text-xs font-normal leading-relaxed text-slate-600 shadow-xl group-hover:block group-focus-within:block dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">{text}</span>
  </span>;
}

function pageLabel(ex: PreviewExerciseData, fallback: number[]) {
  const pages = ex.evidence_pages.length ? ex.evidence_pages : fallback;
  if (!pages.length) return "Sahifalar: —";
  return `Sahifalar: ${Math.min(...pages)}-${Math.max(...pages)}`;
}

export function LessonVisionWorkflow({ bookId, pageCount, gaps = false }: { bookId: string; pageCount: number; gaps?: boolean }) {
  const { me } = useAuth();
  // Only the id matters, and it must stay stable so the restore effect runs once per book.
  const userId = me?.id || "";
  const mapKey = userId ? `lingora.vision-map.${userId}.${bookId}` : "";
  const [pages, setPages] = useState(() => defaultPages(pageCount));
  // One consent for the scan and for every topic preview opened from the result.
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [storageError, setStorageError] = useState("");
  const [result, setResult] = useState<MapResult | null>(null);
  const [active, setActive] = useState(0);
  const [entries, setEntries] = useState<Record<string, TopicEntry>>({});
  const [loadingKey, setLoadingKey] = useState("");
  const inFlight = useRef<Set<string>>(new Set());
  const [topicError, setTopicError] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const entriesRef = useRef(entries);
  entriesRef.current = entries;
  const resultRef = useRef(result);
  resultRef.current = result;
  const runId = useRef(0);
  const consentRef = useRef(consent);
  consentRef.current = consent;

  const topicKey = useCallback((topic: Topic) => userId
    ? `lingora.vision-topic.${userId}.${bookId}.${encodeURIComponent(JSON.stringify([topic.title, topic.page_start, topic.page_end, topic.evidence_pages]))}`
    : "", [userId, bookId]);

  const storeTopic = useCallback((key: string, value: TopicEntry) => {
    setEntries((prev) => ({ ...prev, [key]: value }));
    if (!key) return;
    try { localStorage.setItem(key, JSON.stringify(value)); setStorageError(""); }
    catch { setStorageError("Natijani brauzerda saqlab bo'lmadi."); }
  }, []);

  // Restore the last scan for this book so the screen opens where the user left it.
  // Cached topic previews are restored too, but nothing is sent to the provider until
  // the user scans again or switches to a topic that has no local copy yet.
  useEffect(() => {
    if (!mapKey) return;
    try {
      const saved = localStorage.getItem(mapKey);
      if (!saved) return;
      const data = JSON.parse(saved) as MapResult;
      if (!Array.isArray(data.topics)) return;
      setResult(data);
      resultRef.current = data;
      const cached: Record<string, TopicEntry> = {};
      for (const topic of data.topics) {
        const key = topicKey(topic);
        if (!key) continue;
        try {
          const raw = localStorage.getItem(key);
          if (!raw) continue;
          const entry = JSON.parse(raw) as TopicEntry;
          if (Array.isArray(entry.result?.exercises) && Array.isArray(entry.answers) &&
            entry.result.sampled_pages?.join(",") === data.sampled_pages.join(",")) cached[key] = entry;
        } catch { /* one damaged entry must not hide the rest */ }
      }
      entriesRef.current = { ...entriesRef.current, ...cached };
      setEntries((prev) => ({ ...prev, ...cached }));
    } catch { setStorageError("Brauzerdagi natijani tiklab bo'lmadi."); }
  }, [mapKey, topicKey]);

  /** Loads the exercise preview for one topic once; later switches reuse it. */
  const ensureTopic = useCallback(async (index: number) => {
    const map = resultRef.current;
    if (!map || !map.topics[index]) return;
    const key = topicKey(map.topics[index]);
    if (!consentRef.current) { setTopicError(CONSENT_HINT); return; }
    const existing = entriesRef.current[key];
    // A saved preview describes one exact page set; a different scan invalidates it.
    const samePages = existing?.result?.sampled_pages.join(",") === map.sampled_pages.join(",");
    if (samePages || inFlight.current.has(key)) return;
    setTopicError("");
    inFlight.current.add(key);
    setLoadingKey(key);
    const currentRun = runId.current;
    try {
      if (key) {
        const saved = localStorage.getItem(key);
        if (saved) {
          const data = JSON.parse(saved) as TopicEntry;
          if (Array.isArray(data.result?.exercises) && Array.isArray(data.answers) &&
            data.result.sampled_pages?.join(",") === map.sampled_pages.join(",")) {
            setEntries((prev) => ({ ...prev, [key]: data }));
            return;
          }
        }
      }
      const data = await post<TopicResult>(`/books/${bookId}/vision-topic/preview`,
        { page_numbers: map.sampled_pages, topic: map.topics[index].title, consent_images_to_provider: true });
      if (runId.current !== currentRun) return;
      const empty = data.exercises.map((ex) => ex.questions.map(() => ""));
      storeTopic(key, { result: data, answers: empty });
    } catch (e) {
      if (runId.current === currentRun) setTopicError(e instanceof Error ? e.message : "Mashqlar tayyorlanmadi.");
    } finally {
      inFlight.current.delete(key);
      setLoadingKey((current) => current === key ? "" : current);
    }
  }, [bookId, storeTopic, topicKey]);

  async function scan() {
    if (busy) return;
    if (!consent) { setError("Rasmlarni AI xizmatiga yuborish uchun rozilik belgilang."); return; }
    const numbers = parsePages(pages, pageCount);
    if (!numbers) { setError(`Ko'pi bilan 5 ta takrorlanmagan sahifa kiriting, masalan «1-3, 5» (1–${pageCount}).`); return; }
    setBusy(true); setError(""); setTopicError(""); setExpanded(null);
    runId.current += 1;
    const currentRun = runId.current;
    try {
      const data = await post<MapResult>(`/books/${bookId}/vision-map/preview`,
        { page_numbers: numbers, consent_images_to_provider: true });
      if (runId.current !== currentRun) return;
      resultRef.current = data; entriesRef.current = {};
      setResult(data); setEntries({}); setActive(0);
      try { if (!mapKey) throw new Error(); localStorage.setItem(mapKey, JSON.stringify(data)); setStorageError(""); }
      catch { setStorageError("Natijani brauzerda saqlab bo'lmadi."); }
      // First topic is highlighted by default; its exercises are prepared right away.
      if (data.topics.length) void ensureTopic(0);
    } catch (e) { if (runId.current === currentRun) setError(e instanceof Error ? e.message : "Tahlil bajarilmadi."); }
    finally { if (runId.current === currentRun) setBusy(false); }
  }

  function selectTopic(index: number) {
    setActive(index); setExpanded(null); setTopicError("");
    void ensureTopic(index);
  }

  function updateEntry(topicIndex: number, next: TopicEntry) {
    const topic = resultRef.current?.topics[topicIndex];
    if (!topic) return;
    storeTopic(topicKey(topic), next);
  }

  const currentTopic = result?.topics[active];
  const currentKey = currentTopic ? topicKey(currentTopic) : "";
  const entry = currentKey ? entries[currentKey] : undefined;
  const exercises = entry?.result.exercises || [];
  const answers = entry?.answers || [];

  return <>
    <section aria-labelledby="vision-scan-title" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <h2 id="vision-scan-title" className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
          Vision AI: Kitob tahlili va Mashqlar
          <InfoHint text={`Kitobning tanlangan 1–5 sahifasi tashqi Vision AI xizmatiga yuboriladi. Natija qisman va taxminiy; oldingi kitob ma'lumotlari o'zgarmaydi.${gaps ? " Ayrim sahifalarda mashq to'liq ajratilmagan bo'lishi mumkin; bu tahlil ularni to'ldirishga yordam beradi." : ""}`} />
        </h2>
      </div>
      <label className="mt-4 block text-sm font-medium text-slate-700 dark:text-slate-300">PDF sahifalari (vergul bilan)
        <input value={pages} disabled={busy} placeholder="Misol: 1-5, 10"
          onChange={(e) => { setPages(e.target.value); setError(""); }}
          className="mt-1.5 block w-full max-w-md rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500" />
      </label>
      <label className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
        <input type="checkbox" className="mt-0.5" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
        <span>Vision AI xizmatiga rasmlar yuborilishiga roziman (barcha mashg'ulotlar uchun qo'llaniladi).</span>
      </label>
      <Button className="mt-4 w-full" onClick={scan} disabled={busy || !consent || !pageCount}>
        {busy ? <span className="inline-flex items-center gap-2"><Spinner className="h-4 w-4" />Tahlil qilinmoqda…</span>
          : "Sahifalarni tahlil qilish va Mashqlarni yaratish"}
      </Button>
      {error && <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {storageError && <p role="alert" className="mt-2 text-xs text-amber-700 dark:text-amber-300">{storageError}</p>}
    </section>

    {result && <section aria-labelledby="vision-result-title" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="vision-result-title" className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-slate-100">
          Aniqlangan mavzular va Mashqlar
          <InfoHint text="Mavzu chegaralari AI taxmini; asl PDF bilan solishtiring. Mashqlar faqat tahlil qilingan sahifalardan olinadi va javob kaliti yaratilmaydi." />
        </h2>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          {result.model} <span className="text-slate-400 dark:text-slate-500">|</span> {result.sampled_pages.length} / {result.total_pages} sahifa
        </span>
      </div>
      {!result.topics.length && <p className="mt-4 text-sm text-slate-600 dark:text-slate-300">Tanlangan sahifalarda mavzu aniqlanmadi; boshqa sahifalarni tahlil qiling.</p>}
      {result.topics.length > 0 && <>
        <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Aniqlangan mavzular">
          {result.topics.map((topic, index) => {
            const selected = index === active;
            return <button key={index} type="button" role="tab" aria-selected={selected}
              title={`PDF ${topic.page_start ?? "?"}–${topic.page_end ?? "?"} · ${topic.content_types.join(", ") || "tur aniqlanmadi"}`}
              onClick={() => selectTopic(index)}
              className={`max-w-[18rem] truncate rounded-full px-3 py-1.5 text-xs font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 ${selected
                ? "bg-brand-600 text-white shadow-sm hover:bg-brand-700 dark:bg-brand-500 dark:hover:bg-brand-600"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"}`}>
              {topic.title}
            </button>;
          })}
        </div>
        <div className="mt-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-800 dark:text-slate-200">
            Ushbu mavzu uchun mashqlar namoyishi
            <InfoHint text="Mashqni bosib, savollar, asl PDF qirqimi va AI tekshiruvi bilan to'liq oching. Natija va javoblar faqat shu brauzerda saqlanadi." />
          </h3>
          {loadingKey === currentKey && <div className="mt-3 space-y-2" role="status" aria-label="Mashqlar tayyorlanmoqda">
            <p className="text-xs text-slate-500 dark:text-slate-400">Mashqlar tayyorlanmoqda…</p>
            {[0, 1, 2].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />)}
          </div>}
          {loadingKey !== currentKey && !entry && <div className="mt-3">
            {topicError
              ? <p role="alert" className={`rounded-xl p-3 text-sm ${topicError === CONSENT_HINT
                ? "bg-amber-50 text-amber-800 dark:bg-amber-950/30 dark:text-amber-300"
                : "bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300"}`}>{topicError}</p>
              : <p className="text-sm text-slate-500 dark:text-slate-400">Bu mavzu uchun mashqlar hali yaratilmagan.</p>}
            <Button size="sm" variant="secondary" className="mt-2" disabled={busy} onClick={() => void ensureTopic(active)}>
              {topicError === CONSENT_HINT ? "Mashqlarni tayyorlash" : "Qayta urinish"}
            </Button>
          </div>}
          {entry && !entry.result.exercises.length && <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">Mashq topilmadi.</p>}
          {entry && entry.result.exercises.length > 0 && <ol className="mt-3 max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {entry.result.exercises.map((ex, index) => {
              const open = expanded === index;
              return <li key={index}>
                <button type="button" aria-expanded={open} onClick={() => setExpanded(open ? null : index)}
                  className={`flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition ${open
                    ? "border-brand-400 bg-brand-50 dark:border-brand-500 dark:bg-brand-950/30"
                    : "border-slate-200 bg-white hover:border-brand-300 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-600"}`}>
                  <span className="mt-0.5 grid h-6 min-w-6 place-items-center rounded-lg bg-slate-100 text-xs font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">{index + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-slate-800 dark:text-slate-100">{ex.instruction || "Mashq"}</span>
                    <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">{ex.questions.length} savol</span>
                  </span>
                  <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">{pageLabel(ex, entry.result.sampled_pages)}</span>
                </button>
                {open && <div className="mt-2">
                  <PreviewExercise bookId={bookId} ex={ex} pages={entry.result.sampled_pages} answers={answers[index] || []}
                    active externalBusy={busy || !!loadingKey}
                    onChange={(values) => {
                      const nextAnswers = entry.result.exercises.map((_, i) => i === index ? values : (answers[i] || []));
                      updateEntry(active, { result: entry.result, answers: nextAnswers });
                    }}
                    onRegionChange={(correction) => {
                      // The backend already stored the corrected box; mirror it locally.
                      const exs = entry.result.exercises.map((item, i) => i === index
                        ? { ...item, region: { ...(item.region || { id: correction.regionId, confidence: 1 }), id: correction.regionId, bbox: correction.bbox, needs_review: false } }
                        : item);
                      updateEntry(active, { result: { ...entry.result, exercises: exs }, answers });
                    }}
                    onPicturesChange={(updates) => {
                      const questions = ex.questions.map((q, j) => {
                        const update = updates.find((item) => item.index === j);
                        if (!update || !entry.result.sampled_pages.includes(update.picture.page)) return q;
                        return { ...q, picture: update.picture };
                      });
                      const exs = entry.result.exercises.map((item, i) => i === index ? { ...item, questions } : item);
                      updateEntry(active, { result: { ...entry.result, exercises: exs }, answers });
                    }} />
                </div>}
              </li>;
            })}
          </ol>}
          {entry?.result.warnings.map((warning, i) => <p key={i} className="mt-2 text-xs text-amber-700 dark:text-amber-300">{warning}</p>)}
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">Natijalar faqat shu brauzerda saqlanadi; AI xato qilishi mumkin.</p>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => {
            if (!window.confirm("Ushbu kitob uchun brauzerdagi Vision natijalarini o'chirasizmi?")) return;
            try {
              localStorage.removeItem(mapKey);
              result?.topics.forEach((topic) => { const key = topicKey(topic); if (key) localStorage.removeItem(key); });
              setResult(null); setEntries({}); setActive(0); setExpanded(null); setStorageError("");
            } catch { setStorageError("Brauzerdagi ma'lumotni o'chirib bo'lmadi."); }
          }}>Mahalliy ma'lumotlarni o'chirish</Button>
        </div>
      </>}
    </section>}
  </>;
}
