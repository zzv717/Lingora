"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get, post } from "@/lib/api";
import type { Book, Job, Structure, VocabSession, VocabWord } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, EmptyState, Spinner, useToast } from "@/components/ui";
import { VocabPicture } from "@/components/reader/vocab-picture";

export default function VocabularyPage() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [polling, setPolling] = useState(0);
  const [selected, setSelected] = useState<string>("");
  const [struct, setStruct] = useState<Structure | null>(null);
  const [words, setWords] = useState<VocabWord[]>([]);
  const [stats, setStats] = useState<{ learning: number; mastered: number; due: number; total: number } | null>(null);
  const [starting, setStarting] = useState(false);
  const [query, setQuery] = useState("");
  const [expandedLessons, setExpandedLessons] = useState<Record<string, boolean>>({});
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
    (async () => {
      const st = await get<Structure>(`/books/${selected}/structure`);
      setStruct(st);
      const w = await get<VocabWord[]>(`/books/${selected}/vocabulary`);
      setWords(w);
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
  const emptyReason = (() => {
    const cov = struct?.coverage;
    if (!cov) return "";
    if (cov.pages_needing_ocr > 0) {
      return `Kitobning ${cov.pages_needing_ocr} sahifasi skanerlangan (matn emas, rasm) — o'qish uchun OCR kerak. Kitob sahifasidagi «Skanerlangan sahifalar» bo'limidan ularni birma-bir o'qib chiqing.`;
    }
    if (job?.status === "failed") {
      return `Oxirgi tahlil tugallanmadi${job.error_code ? ` (${job.error_code})` : ""}${job.error_message ? `: ${job.error_message}` : "."}`;
    }
    return "Tahlil tugadi, lekin bu kitobdan lug'at so'zlari ajratilmadi — kitobda alohida lug'at ro'yxatlari bo'lmasligi mumkin.";
  })();
  const ocrNeeded = (struct?.coverage.pages_needing_ocr ?? 0) > 0;

  const reanalyzeAction = (
    <Button variant="secondary" loading={reanalyzing} onClick={reanalyzeBook}>
      Qayta tahlil qilish
    </Button>
  );

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
                  {reanalyzeAction}
                </div>
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

            {!struct ? (
              <div className="flex justify-center py-10"><Spinner className="h-6 w-6 text-brand-500" /></div>
            ) : (
              <div className="space-y-5">
                {struct.lessons.map((l) => {
                  const lessonWords = words.filter((w) => w.lesson_id === l.id);
                  const normalizedQuery = query.trim().toLocaleLowerCase();
                  const lw = normalizedQuery
                    ? lessonWords.filter((w) => `${w.term} ${w.translation_uz} ${w.definition_en}`.toLocaleLowerCase().includes(normalizedQuery))
                    : lessonWords;
                  if (lw.length === 0) return null;
                  const lp = struct.lessons_progress[l.id];
                  const expanded = !!expandedLessons[l.id] || !!normalizedQuery;
                  const visibleWords = expanded ? lw : lw.slice(0, 12);
                  return (
                    <Card key={l.id}>
                      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100">{l.title}</h3>
                          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{lw.length} so'z · {l.page_start}-{l.page_end} bet</p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          {lp && !lp.vocab_gate_passed && lp.has_vocabulary && <Badge tone="amber">Test o'tilmagan</Badge>}
                          {lp?.vocab_gate_passed && lp.has_vocabulary && <Badge tone="green">✓ Test o'tilgan</Badge>}
                          <Button size="sm" variant={lp && lp.has_vocabulary && !lp.vocab_gate_passed ? "primary" : "secondary"}
                            loading={starting} disabled={!lessonWords.some((w) => !w.needs_translation)} onClick={() => startReview(l.id)}>
                            {lp && lp.has_vocabulary && !lp.vocab_gate_passed ? "🔑 Gatetestni topshirish" : "Test"}
                          </Button>
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        {visibleWords.map((w) => (
                          <div key={w.id} className="min-w-0 rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-700">
                            <div className="flex flex-wrap items-start justify-between gap-2">
                              <span className="break-words text-lg font-semibold leading-7 text-slate-900 dark:text-slate-100">{w.term}</span>
                              {w.part_of_speech && <Badge>{w.part_of_speech}</Badge>}
                            </div>
                            <p className="mt-1 break-words text-base leading-7 text-slate-600 dark:text-slate-300">
                              {w.needs_translation ? "Tarjima tekshirilmagan — testga kiritilmaydi" : w.translation_uz}
                            </p>
                            {/* The illustration is cropped from the original PDF, so it stays sharp. */}
                            {w.picture_page && w.picture_bbox && (
                              <VocabPicture bookId={selected} wordId={w.id} term={w.term} />
                            )}
                            {w.definition_en && <p className="mt-2 break-words text-sm leading-6 text-slate-500 dark:text-slate-400">{w.definition_en}</p>}
                            {w.example_sentence && <p className="mt-1 break-words text-sm italic leading-6 text-slate-500 dark:text-slate-400">{w.example_sentence}</p>}
                          </div>
                        ))}
                      </div>
                      {lw.length > 12 && !normalizedQuery && (
                        <button
                          type="button"
                          onClick={() => setExpandedLessons((old) => ({ ...old, [l.id]: !expanded }))}
                          className="mt-4 rounded-lg px-3 py-2 text-base font-medium text-brand-700 hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:text-brand-300 dark:hover:bg-brand-900/30"
                        >
                          {expanded ? "Kamroq ko'rsatish" : `Barcha ${lw.length} ta so'zni ko'rish`}
                        </button>
                      )}
                    </Card>
                  );
                })}
                {words.length === 0 && (
                  <EmptyState
                    title="Bu kitobda lug'at topilmadi"
                    description={emptyReason || "Kitob lug'at ro'yxatlari bo'lmagan holda tahlil qilingan bo'lishi mumkin."}
                    action={<div className="flex flex-wrap justify-center gap-2">
                      {ocrNeeded && <Link href={`/books/${selected}`}><Button variant="secondary">Skanerlangan sahifalarni o'qish</Button></Link>}
                      {reanalyzeAction}
                    </div>}
                  />
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
