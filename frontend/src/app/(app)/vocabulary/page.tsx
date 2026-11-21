"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { del, get, patch, post } from "@/lib/api";
import type {
  Book, Job, Structure, VocabSession, VocabUnit, VocabUnitEntry, VocabWord,
} from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, EmptyState, Spinner, useToast } from "@/components/ui";
import { VocabPicture } from "@/components/reader/vocab-picture";
import { VisionVocabulary } from "@/components/reader/vision-vocabulary";

/** A word's translation state, in the reader's words: "auto" is usable, not a warning. */
function TranslationBadge({ status, needs }: { status: VocabUnitEntry["translation_status"]; needs: boolean }) {
  if (needs) return <Badge tone="red">Tarjima yo&apos;q</Badge>;
  if (status === "verified") return <Badge tone="green">✓ Tasdiqlangan</Badge>;
  if (status === "edited") return <Badge tone="blue">Tahrirlangan</Badge>;
  if (status === "auto") return <Badge tone="amber">auto</Badge>;
  return null;
}

/**
 * One entry of the Lug'at, editable in place.
 *
 * The old card printed "Tarjima tekshirilmagan — testga kiritilmaydi" over a machine
 * translation that had never been generated: the word existed, was never usable, and there
 * was no way to fix it from the screen. Now a word that has only a machine translation says
 * so with a small "auto" badge and still enters tests; editing, regenerating, verifying and
 * deleting all happen here.
 */
function WordCard({ bookId, word, units, onChanged, onDelete, onReload }:
  { bookId: string; word: VocabUnitEntry; units: VocabUnit[];
    onChanged: (w: VocabUnitEntry) => void; onDelete: (id: string) => void;
    onReload: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(word.translation_uz);
  const [busy, setBusy] = useState("");
  const { toast } = useToast();

  async function save() {
    setBusy("save");
    try {
      onChanged(await patch<VocabUnitEntry>(`/books/${bookId}/vocabulary/${word.id}`,
        { translation_uz: draft }));
      setEditing(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Saqlanmadi", "error");
    } finally { setBusy(""); }
  }

  async function regenerate() {
    setBusy("regen");
    try {
      onChanged(await post<VocabUnitEntry>(`/books/${bookId}/vocabulary/${word.id}/translate`));
      toast("Tarjima yangilandi", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Tarjima yaratilmadi", "error");
    } finally { setBusy(""); }
  }

  async function verify() {
    setBusy("verify");
    try {
      onChanged(await post<VocabUnitEntry>(`/books/${bookId}/vocabulary/${word.id}/verify`));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Tasdiqlanmadi", "error");
    } finally { setBusy(""); }
  }

  async function move(unitId: string) {
    setBusy("move");
    try {
      await patch<VocabUnitEntry>(`/books/${bookId}/vocabulary/${word.id}`, { unit_id: unitId });
      toast("Boshqa bo'limga ko'chirildi", "success");
      onReload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Ko'chirilmadi", "error");
    } finally { setBusy(""); }
  }

  return (
    <div className="min-w-0 rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">{word.word}</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {word.part_of_speech && <Badge>{word.part_of_speech}</Badge>}
          <TranslationBadge status={word.translation_status} needs={word.needs_translation} />
        </div>
      </div>
      {editing ? (
        <div className="mt-1 space-y-2">
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
            className="w-full rounded-lg border border-brand-400 px-2 py-1.5 text-base dark:bg-slate-900"
            aria-label={`${word.word} uchun o'zbekcha tarjima`}
          />
          <div className="flex gap-2">
            <Button size="sm" loading={busy === "save"} onClick={save}>Saqlash</Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(word.translation_uz); }}>Bekor</Button>
          </div>
        </div>
      ) : (
        <p className="mt-1 break-words text-base leading-7 text-slate-700 dark:text-slate-200">
          {word.translation_uz || <span className="text-slate-400">tarjima yo&apos;q</span>}
          {!!word.alt_translations?.length && (
            <span className="ml-2 text-sm text-slate-400">({word.alt_translations.join(", ")})</span>
          )}
        </p>
      )}
      {word.picture_page && word.picture_bbox && (
        <VocabPicture bookId={bookId} wordId={word.id} term={word.word} />
      )}
      {word.definition && <p className="mt-2 break-words text-sm leading-6 text-slate-500 dark:text-slate-400">{word.definition}</p>}
      {word.example && <p className="mt-1 break-words text-sm italic leading-6 text-slate-500 dark:text-slate-400">{word.example}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        {!editing && (
          <button type="button" onClick={() => { setEditing(true); setDraft(word.translation_uz); }}
            className="font-medium text-brand-700 hover:underline dark:text-brand-300">Tahrirlash</button>
        )}
        {word.translation_status !== "verified" && !word.needs_translation && (
          <button type="button" onClick={verify} disabled={!!busy}
            className="font-medium text-emerald-700 hover:underline disabled:opacity-50 dark:text-emerald-300">Tasdiqlash</button>
        )}
        {(word.translation_status === "auto" || !word.translation_uz) && (
          <button type="button" onClick={regenerate} disabled={!!busy}
            className="font-medium text-slate-600 hover:underline disabled:opacity-50 dark:text-slate-300">
            {busy === "regen" ? "Yaratilmoqda…" : "Qayta tarjima"}
          </button>
        )}
        {units.length > 1 && (
          <label className="flex items-center gap-1 text-slate-500 dark:text-slate-400">
            <span className="sr-only">Boshqa bo&apos;limga ko&apos;chirish</span>
            <select
              value={word.unit_id ?? ""}
              onChange={(e) => move(e.target.value)}
              disabled={!!busy}
              className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-slate-600 dark:bg-slate-900"
            >
              <option value="">Bo&apos;limga ko&apos;chirish…</option>
              {units.filter((u) => u.id && u.id !== word.unit_id).map((u) => (
                <option key={u.id} value={u.id!}>{u.number != null ? `${u.number}-unit` : u.title}</option>
              ))}
            </select>
          </label>
        )}
        <button type="button" onClick={() => onDelete(word.id)} disabled={!!busy}
          className="font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400">O&apos;chirish</button>
      </div>
    </div>
  );
}

export default function VocabularyPage() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [polling, setPolling] = useState(0);
  const [selected, setSelected] = useState<string>("");
  const [struct, setStruct] = useState<Structure | null>(null);
  const [words, setWords] = useState<VocabWord[]>([]);
  // Units come from the extractor itself: a vocabulary book is organised per unit, and a
  // flat list of 600 words gives no clue whether extraction actually worked.
  const [units, setUnits] = useState<VocabUnit[] | null>(null);
  // Totals come from the same response as the units, so the header cannot disagree with the
  // list below it (a word with no Uzbek translation used to be invisible in both).
  const [vocabTotals, setVocabTotals] = useState<{ total: number; translated: number; untranslated: number } | null>(null);
  const [stats, setStats] = useState<{ learning: number; mastered: number; due: number; total: number } | null>(null);
  const [starting, setStarting] = useState(false);
  const [query, setQuery] = useState("");
  const [expandedLessons, setExpandedLessons] = useState<Record<string, boolean>>({});
  const [translating, setTranslating] = useState(false);
  const [regenerating, setRegenerating] = useState<string>("");
  const [translateError, setTranslateError] = useState("");
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    (async () => {
      const [b, s] = await Promise.all([get<Book[]>("/books"), get<typeof stats>("/vocabulary/stats")]);
      setBooks(b);
      setStats(s);
      const ready = b.find((x) => x.status === "ready");
      if (ready) setSelected(ready.id);
    })().catch(() => toast("Ma'lumot yuklanmadi", "error"));
  }, [toast]);

  useEffect(() => {
    if (!selected) return;
    setStruct(null);
    setWords([]);
    setUnits(null);
    (async () => {
      const st = await get<Structure>(`/books/${selected}/structure`);
      setStruct(st);
      const w = await get<VocabWord[]>(`/books/${selected}/vocabulary`);
      setWords(w);
      try {
        const grouped = await get<{ units: VocabUnit[]; total: number; translated: number; untranslated: number }>(
          `/books/${selected}/vocabulary/units`);
        setUnits(grouped.units);
        setVocabTotals({ total: grouped.total, translated: grouped.translated, untranslated: grouped.untranslated });
      } catch { setUnits([]); }
      // Why a book is empty is usually the last job's answer: a first analysis that ran
      // with an older detector, or a re-analysis that failed. Showing it turns a dead end
      // into something the user can act on.
      try { setJob(await get<Job | null>(`/books/${selected}/status`)); } catch { setJob(null); }
    })().catch(() => toast("Lug'at yuklanmadi", "error"));
  }, [selected, reloadToken, toast]);

  // A book that is still being analysed is not a dead end: keep the screen informative
  // and refresh until it becomes ready instead of showing "no vocabulary".
  const processing = (books || []).filter((b) => b.status === "processing" || b.status === "uploaded");
  useEffect(() => {
    if (!processing.length) return;
    const timer = setInterval(() => setPolling((n) => n + 1), 5000);
    return () => clearInterval(timer);
  }, [processing.length]);
  useEffect(() => {
    if (!polling) return;
    get<Book[]>("/books").then((list) => {
      setBooks(list);
      const ready = list.find((x) => x.status === "ready");
      if (ready) setSelected((current) => current || ready.id);
      // The selected book just finished a re-analysis: its words and lessons are new.
      if (selected && list.some((x) => x.id === selected && x.status === "ready")) {
        setReloadToken((n) => n + 1);
      }
    }).catch(() => {});
  }, [polling, selected]);

  const startReview = async (lessonId?: string) => {
    setStarting(true);
    try {
      const q = lessonId ? `?lesson_id=${lessonId}&kind=lesson_gate` : `?book_id=${selected}&kind=review`;
      const s = await post<VocabSession>(`/vocabulary/sessions${q}`);
      location.href = `/practice/${s.id}`;
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    } finally {
      setStarting(false);
    }
  };

  // A book whose vocabulary stayed empty was analysed by an older detector. Re-analysis
  // keeps answers and SM-2 schedules (matched by content, not ids), so it is safe to
  // offer here instead of leaving the user with an empty screen and no way forward.
  const reanalyzeBook = async () => {
    if (!selected) return;
    setReanalyzing(true);
    try {
      const started = await post<{ warnings?: { message_uz: string }[] }>(`/books/${selected}/reanalyze`);
      toast(started?.warnings?.[0]?.message_uz || "Kitob qayta tahlil qilinmoqda", "success");
      // Keep this screen live: the words appear without a reload once the job finishes.
      setPolling((n) => n + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Qayta tahlil boshlanmadi", "error");
    } finally {
      setReanalyzing(false);
    }
  };
  // The most useful sentence is not "no vocabulary": it is WHY. A scanned book and a book
  // with no word lists both end up empty, and only one of them is fixable by re-analysis.
  // The most useful sentence is not "no vocabulary": it is WHY — and now the backend knows.
  // The pipeline records how many entries the text parser found and what the automatic
  // vision fallback did, so this screen reports a fact instead of guessing from a page count.
  const selectedBook = (books || []).find((b) => b.id === selected) || null;
  const emptyReason = (() => {
    if (selectedBook?.vocabulary_note_uz) return selectedBook.vocabulary_note_uz;
    const cov = struct?.coverage;
    if (!cov) return "";
    if (cov.pages_needing_ocr > 0) {
      return `Kitobning ${cov.pages_needing_ocr} sahifasida matn qatlami yo'q (rasm). Matn ajratgich ularni o'qiy olmaydi; quyidagi AI o'qish tugmasi rasmlardan so'zlarni oladi.`;
    }
    if (job?.status === "failed") {
      return `Oxirgi tahlil tugallanmadi${job.error_code ? ` (${job.error_code})` : ""}${job.error_message ? `: ${job.error_message}` : "."}`;
    }
    if (selectedBook && typeof selectedBook.text_vocabulary_count === "number" && selectedBook.text_vocabulary_count === 0) {
      return "Matn qatlami bor, lekin matn ajratgich undan birorta lug'at yozuvini topa olmadi. AI (vision) yo'li bilan sahifalarni o'qish mumkin.";
    }
    return "Tahlil tugadi, lekin bu kitobdan lug'at so'zlari ajratilmadi — kitobda alohida lug'at ro'yxatlari bo'lmasligi mumkin.";
  })();
  const ocrNeeded = (struct?.coverage.pages_needing_ocr ?? 0) > 0;
  // A scanned book is re-readable only by the vision path: OCR lifts the text, but the
  // rule-based detector still needs a "Word List" layout it can parse. Vision reads it.
  //
  // But a scanned book is not the only case that needs vision, and gating the whole panel
  // on it is why a text book could show "no vocabulary found" with no way forward: the
  // text parser can fail on a layout perfectly well while the pages stay "text" pages.
  // The panel is therefore offered whenever the Lug'at is incomplete, and the "check text
  // pages too" checkbox (already in the panel) decides the worklist.
  const scannedBook = ocrNeeded;
  const visionWanted = ocrNeeded
    || !!selectedBook?.vocabulary_note_uz
    || (typeof selectedBook?.text_vocabulary_count === "number" && selectedBook.text_vocabulary_count === 0);

  const reanalyzeAction = (
    <Button variant="secondary" loading={reanalyzing} onClick={reanalyzeBook}>
      Qayta tahlil qilish
    </Button>
  );

  // "Translate missing" is a bounded server call (it walks batches until a small cap), so a
  // book with hundreds of untranslated words is fixed without the user clicking each one.
  const translateMissing = async () => {
    if (!selected) return;
    setTranslating(true);
    setTranslateError("");
    try {
      const out = await post<{ translated: number; remaining: number; error?: string; error_uz?: string }>(
        `/books/${selected}/vocabulary/translate-missing?limit=150`);
      if (out.translated) {
        toast(`${out.translated} ta so'z tarjima qilindi${out.remaining ? ` · ${out.remaining} ta qoldi` : ""}`, "success");
      } else if (out.error_uz) {
        // The provider's own words ("Gemini xatosi (400): API key not valid…") — a bare error
        // code would make the user guess what to change in Vercel.
        setTranslateError(out.error_uz);
        toast(out.error_uz, "error");
      } else {
        toast("Tarjima kerak bo'lgan so'z yo'q", "error");
      }
      setReloadToken((n) => n + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Tarjima yaratilmadi", "error");
    } finally { setTranslating(false); }
  };

  // Editing a word must not reload the page under the user's cursor: the card updates from
  // the server's own answer, and the group counts are recomputed from the list.
  const replaceWord = (next: VocabUnitEntry) => {
    setUnits((old) => (old || []).map((u) => {
      const has = u.entries.some((w) => w.id === next.id);
      if (!has) return u;
      const entries = u.entries.map((w) => (w.id === next.id ? next : w));
      return {
        ...u,
        entries,
        count: entries.length,
        translated_count: entries.filter((w) => w.translation_uz).length,
        auto_count: entries.filter((w) => w.translation_status === "auto").length,
      };
    }));
  };

  const deleteWord = async (wordId: string) => {
    if (!selected) return;
    try {
      await del(`/books/${selected}/vocabulary/${wordId}`);
      setUnits((old) => (old || []).map((u) => {
        if (!u.entries.some((w) => w.id === wordId)) return u;
        const entries = u.entries.filter((w) => w.id !== wordId);
        return { ...u, entries, count: entries.length };
      }));
      toast("So'z o'chirildi", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "O'chirilmadi", "error");
    }
  };

  const readyBooks = (books || []).filter((b) => b.status === "ready");

  return (
    <>
      <TopBar title="Lug'at" />
      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8">
        {stats && (
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Card><p className="text-sm text-slate-500">Jami so'z</p><p className="text-2xl font-bold">{stats.total}</p></Card>
            <Card><p className="text-sm text-slate-500">O'zlashtirilgan</p><p className="text-2xl font-bold text-emerald-600">{stats.mastered}</p></Card>
            <Card><p className="text-sm text-slate-500">O'rganilmoqda</p><p className="text-2xl font-bold text-brand-600">{stats.learning}</p></Card>
            <Card><p className="text-sm text-slate-500">Takrorlash kerak</p><p className="text-2xl font-bold text-amber-600">{stats.due}</p></Card>
          </div>
        )}

        {!books ? (
          <div className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></div>
        ) : readyBooks.length === 0 ? (
          <EmptyState
            title="Lug'at mavjud emas"
            description="Avval kitob yuklang — AI kitobdan lug'at ro'yxatlarini ajratib oladi va ular bo'yicha test tuzadi."
            action={<Link href="/books"><Button>Kitoblarimga o'tish</Button></Link>}
          />
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              {readyBooks.map((b) => (
                <button key={b.id}
                  onClick={() => setSelected(b.id)}
                  className={`rounded-xl border px-3.5 py-2 text-sm font-medium transition ${
                    selected === b.id ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                      : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}>
                  {b.title}
                </button>
              ))}
            </div>

            {processing.length > 0 && !readyBooks.length && (
              <Card className="text-sm text-slate-600 dark:text-slate-300">
                <p className="font-semibold">Kitob hali tahlil qilinmoqda</p>
                <p className="mt-1">Lug'at sahifalari tayyor bo'lishi bilan shu yerda ko'rinadi. Kuting — bu sahifa o'zi yangilanadi.</p>
              </Card>
            )}

            {readyBooks.length > 0 && !words.length && struct && (
              <Card className="text-sm text-slate-600 dark:text-slate-300">
                <p className="font-semibold">Bu kitobda lug'at yozuvlari topilmadi</p>
                <p className="mt-1">Kitob matnli lug'at sahifalaridan iborat bo'lmasa, so'zlar aniqlanmaydi. Kitobni qayta tahlil qilish eski progressni saqlab qoladi, shuning uchun bemalol boshlash mumkin.</p>
                <p className="mt-3 rounded-lg bg-slate-100 p-2.5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {emptyReason}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {ocrNeeded && (
                    <Link href={`/books/${selected}`}><Button variant="secondary">Skanerlangan sahifalarni o'qish</Button></Link>
                  )}
                  {!scannedBook && reanalyzeAction}
                </div>
                {visionWanted && selected && (
                  <VisionVocabulary bookId={selected} onDone={() => setReloadToken((n) => n + 1)} />
                )}
              </Card>
            )}

            <label className="block">
              <span className="sr-only">Lug'atdan so'z yoki tarjima qidirish</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="So'z yoki tarjimani qidiring…"
                className="w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base text-slate-800 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
            </label>

            <Card className="flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r from-brand-600 to-violet-600 text-white">
              <div>
                <p className="font-semibold">Aqlli takrorlash</p>
                <p className="text-sm opacity-80">SM-2 jadvali bo'yicha bugun takrorlash kerak bo'lgan so'zlar</p>
              </div>
              <Button variant="secondary" className="!bg-white !text-brand-700" loading={starting}
                onClick={() => startReview()} disabled={!words.some((w) => !w.needs_translation)}>
                🔁 Takrorlash seansi
              </Button>
            </Card>

            {vocabTotals && (
              <Card className="text-sm text-slate-600 dark:text-slate-300">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-800 dark:text-slate-100">
                      {vocabTotals.total} ta so&apos;z · {vocabTotals.translated} tasi o&apos;zbekchada
                      {vocabTotals.untranslated ? ` · ${vocabTotals.untranslated} tasi tarjimasiz` : ""}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      Mashinaviy tarjimalar «auto» belgisi bilan turadi va testlarda ishlatiladi.
                      Tasdiqlasangiz yoki tahrirlasangiz — «tasdiqlangan»/«tahrirlangan» bo&apos;ladi.
                    </p>
                  </div>
                  {vocabTotals.untranslated > 0 && (
                    <Button variant="secondary" loading={translating} onClick={translateMissing}>
                      Tarjimasiz so&apos;zlarni tarjima qilish ({vocabTotals.untranslated})
                    </Button>
                  )}
                </div>
                {translateError && (
                  <p role="alert" className="mt-2 rounded-lg bg-red-50 p-2 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-300">
                    {translateError}
                  </p>
                )}
              </Card>
            )}

            {!struct ? (
              <div className="flex justify-center py-10"><Spinner className="h-6 w-6 text-brand-500" /></div>
            ) : (
              <div className="space-y-5">
                {(units ?? []).map((u) => {
                  const normalizedQuery = query.trim().toLocaleLowerCase();
                  const uw = normalizedQuery
                    ? u.entries.filter((w) => `${w.word} ${w.translation_uz} ${w.definition} ${(w.alt_translations || []).join(" ")}`
                        .toLocaleLowerCase().includes(normalizedQuery))
                    : u.entries;
                  if (uw.length === 0) return null;
                  // Group key for expand state and for the lesson gate, which is keyed by lesson.
                  const key = u.lesson_id ?? `unit:${u.number}:${u.page_start}`;
                  const lp = u.lesson_id ? struct.lessons_progress[u.lesson_id] : undefined;
                  // Units start closed: a 30-unit book is a list of 30 headings, not a wall of
                  // 600 cards. A search reopens whatever it matches, so a hit is never hidden.
                  const collapsed = normalizedQuery ? false : expandedLessons[key] !== true;
                  const visibleWords = collapsed ? [] : uw;
                  const heading = u.number != null && u.number > 0
                    ? `${u.number}-unit${u.unit_title ? ` · ${u.unit_title}` : ""}`
                    : (u.title || "Boshqa lug'at yozuvlari");
                  return (
                    <Card key={key}>
                      <button
                        type="button"
                        onClick={() => setExpandedLessons((old) => ({ ...old, [key]: collapsed }))}
                        className="mb-3 flex w-full flex-wrap items-center justify-between gap-3 text-left"
                        aria-expanded={!collapsed}
                      >
                        <div>
                          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
                            {heading}
                          </h3>
                          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                            {uw.length} so&apos;z
                            {u.translated_count ? ` · ${u.translated_count} tarjima qilingan` : ""}
                            {u.page_start ? ` · ${u.page_start}-${u.page_end} bet` : ""}
                            {u.confidence && u.confidence < 0.5 ? " · sarlavha ishonchsiz" : ""}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {u.auto_count > 0 && <Badge tone="amber">{u.auto_count} auto</Badge>}
                          {lp && !lp.vocab_gate_passed && lp.has_vocabulary && <Badge tone="amber">Test o&apos;tilmagan</Badge>}
                          {lp?.vocab_gate_passed && lp.has_vocabulary && <Badge tone="green">✓ Test o&apos;tilgan</Badge>}
                          {u.lesson_id && (
                            <Button size="sm" variant={lp && lp.has_vocabulary && !lp.vocab_gate_passed ? "primary" : "secondary"}
                              loading={starting} disabled={!uw.some((w) => !w.needs_translation)}
                              onClick={(e) => { e.stopPropagation(); startReview(u.lesson_id!); }}>
                              {lp && lp.has_vocabulary && !lp.vocab_gate_passed ? "🔑 Gatetestni topshirish" : "Test"}
                            </Button>
                          )}
                          <span className="text-sm text-slate-400">{collapsed ? "▸ ochish" : "▾ yopish"}</span>
                        </div>
                      </button>
                      <div className="grid gap-3 md:grid-cols-2">
                        {visibleWords.map((w) => (
                          <WordCard key={w.id} bookId={selected} word={w} units={units ?? []}
                            onChanged={replaceWord} onDelete={deleteWord}
                            onReload={() => setReloadToken((n) => n + 1)} />
                        ))}
                      </div>
                    </Card>
                  );
                })}
                {words.length === 0 && (
                  <div className="rounded-2xl border-2 border-dashed border-slate-300 p-4 dark:border-slate-700">
                  <EmptyState
                    title="Bu kitobda lug'at topilmadi"
                    description={emptyReason || "Kitob lug'at ro'yxatlari bo'lmagan holda tahlil qilingan bo'lishi mumkin."}
                    action={<div className="flex flex-wrap justify-center gap-2">
                      {ocrNeeded && <Link href={`/books/${selected}`}><Button variant="secondary">Skanerlangan sahifalarni o'qish</Button></Link>}
                      {!scannedBook && reanalyzeAction}
                    </div>}
                  />
                  {visionWanted && selected && (
                    <VisionVocabulary bookId={selected} onDone={() => setReloadToken((n) => n + 1)} />
                  )}
                  </div>
                )}
                {query.trim() && words.length > 0 && !words.some((w) => `${w.term} ${w.translation_uz} ${w.definition_en}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && (
                  <EmptyState title="So'z topilmadi" description="Boshqa so'z yoki tarjima bilan qidirib ko'ring." />
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </>
  );
}
