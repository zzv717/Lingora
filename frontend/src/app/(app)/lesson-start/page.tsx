"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { get } from "@/lib/api";
import { planUrl, suggestLessons, type PlanOption } from "@/lib/lesson-plan";
import type { Book, LessonProgress } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Button, Card, Spinner } from "@/components/ui";
import { VisionMapPreview } from "@/components/reader/vision-map-preview";

type Option = PlanOption & { title: string; topic: string; page_start: number; page_end: number;
  exercise_count: number; vocabulary_count: number; has_explanation: boolean;
  pending_ocr_pages: number; page_inventory_complete: boolean; progress: LessonProgress };
type Options = { book_id: string; page_count: number; lessons: Option[] };
const statusLabel: Record<string, string> = { not_started: "Boshlanmagan", in_progress: "Davom etmoqda",
  exercises_done: "Mashqlar bajarilgan", completed: "Tugatilgan" };

export default function LessonStartPage() {
  const router = useRouter();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [bookId, setBookId] = useState("");
  const [data, setData] = useState<Options | null>(null);
  const [mode, setMode] = useState<"1" | "2" | "many">("2");
  const [count, setCount] = useState(2);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [booksRetry, setBooksRetry] = useState(0);
  const [optionsRetry, setOptionsRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setBooks(null); setError("");
    get<Book[]>("/books").then((items) => { if (active) { setBooks(items); setBookId(items.find((b) => b.status === "ready")?.id || ""); } })
      .catch((e) => { if (active) { setError(e instanceof Error ? e.message : "Kitoblar yuklanmadi."); setBooks([]); } });
    return () => { active = false; };
  }, [booksRetry]);
  useEffect(() => {
    if (!bookId) { setData(null); return; }
    let active = true;
    setLoading(true); setError(""); setData(null); setSelected([]);
    get<Options>(`/books/${bookId}/lesson-options`).then((result) => {
      if (!active) return;
      setData(result); setMode("2"); setCount(2); setSelected(suggestLessons(result.lessons, 2));
    }).catch((e) => { if (active) setError(e instanceof Error ? e.message : "Darslar yuklanmadi."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [bookId, optionsRetry]);

  const ready = (books || []).filter((book) => book.status === "ready");
  const available = (data?.lessons || []).filter((lesson) => !lesson.progress.locked).length;
  const target = Math.min(count, available);
  const chooseCount = (value: number, nextMode: "1" | "2" | "many") => {
    const next = Math.max(1, Math.min(20, Number.isFinite(value) ? value : 1));
    setMode(nextMode); setCount(next); setSelected(suggestLessons(data?.lessons || [], next));
  };
  const start = () => {
    if (!data || !selected.length || selected.length !== target) return;
    // Book order is the teaching order; the query only carries IDs, not answers.
    const ids = data.lessons.filter((lesson) => selected.includes(lesson.id) && !lesson.progress.locked).map((lesson) => lesson.id);
    if (ids.length !== selected.length) return;
    router.push(planUrl(bookId, ids[0], ids));
  };
  return <>
    <TopBar title="Darsni boshlash" />
    <main className="mx-auto max-w-4xl space-y-5 px-4 py-6 lg:px-8">
      <Link href="/dashboard" className="text-sm text-brand-600 hover:underline">← Boshqaruv paneli</Link>
      <Card>
        <h1 className="text-xl font-bold">Bugungi darsni tanlang</h1>
        <p className="mt-1 text-sm text-slate-500">Avval kitob, keyin o'rganmoqchi bo'lgan mavzularingizni tanlang.</p>
        {error && <div className="mt-3"><p role="alert" className="text-sm text-red-600">{error}</p>
          <Button size="sm" variant="secondary" className="mt-2" onClick={() => bookId ? setOptionsRetry((n) => n + 1) : setBooksRetry((n) => n + 1)}>Qayta urinish</Button></div>}
        {books === null ? <Spinner className="mt-4 h-6 w-6" /> : ready.length === 0 ? <div className="mt-4 text-sm">
          <p>Tayyor kitob yo'q. Kitob yuklang yoki tahlil tugashini kuting.</p>
          <Link href="/books" className="mt-2 inline-block text-brand-600 underline">Kitoblarimga o'tish</Link>
        </div> : <label className="mt-4 block text-sm font-medium">Kitob
          <select value={bookId} onChange={(e) => setBookId(e.target.value)} className="mt-1 block w-full rounded-lg border border-slate-300 bg-white p-2 dark:border-slate-700 dark:bg-slate-800">
            {ready.map((book) => <option key={book.id} value={book.id}>{book.title}</option>)}
          </select>
        </label>}
      </Card>
      {loading && <div className="flex justify-center py-6"><Spinner className="h-6 w-6" /></div>}
      {data && <>
        <Card>
          <h2 className="font-semibold">Nechta mavzu o'rganasiz?</h2>
          <div className="mt-3 flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2"><input type="radio" name="amount" checked={mode === "1"} onChange={() => chooseCount(1, "1")} />1 ta</label>
            <label className="flex items-center gap-2"><input type="radio" name="amount" checked={mode === "2"} onChange={() => chooseCount(2, "2")} />2 ta (standart)</label>
            <label className="flex items-center gap-2"><input type="radio" name="amount" checked={mode === "many"} onChange={() => chooseCount(3, "many")} />Boshqa son</label>
            {mode === "many" && <label>Son: <input aria-label="Mavzular soni" type="number" min={1} max={20} value={count}
              onChange={(e) => chooseCount(Number(e.target.value), "many")} className="w-20 rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-800" /></label>}
          </div>
          <p className="mt-3 text-xs text-slate-500">Dastlab davom etayotgan yoki boshlanmagan darslar tavsiya qilinadi; bu AI tavsiyasi emas. O'zingiz ham tanlovni o'zgartira olasiz. Sonni o'zgartirsangiz tavsiya yangilanadi.</p>
          {count > available && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">Hozir faqat {available} ta ochiq dars mavjud.</p>}
        </Card>
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Mavzular · {selected.length}/{target} tanlandi</h2>
            <Button size="sm" variant="secondary" onClick={() => setSelected(suggestLessons(data.lessons, count))} disabled={!available}>Tavsiyani tiklash</Button></div>
          <p className="mt-1 text-xs text-slate-500">Ro'yxat mavjud dars yozuvlaridan olingan; u kitobning to'liq xaritasi ekanligi tasdiqlanmagan. Ko'rsatilgan sonlar saqlangan materiallar, sahifadagi barcha mashqlar soni emas.</p>
          {!data.lessons.length && <p className="mt-3 text-sm">Darslar aniqlanmadi. Kitob sahifasida xaritalash sinovidan foydalaning.</p>}
          <div className="mt-3 space-y-2">{data.lessons.map((lesson) => {
            const checked = selected.includes(lesson.id);
            return <label key={lesson.id} className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700">
              <input type="checkbox" className="mt-1" checked={checked} disabled={lesson.progress.locked || (!checked && selected.length >= target)} onChange={(e) => setSelected(e.target.checked ? [...selected, lesson.id] : selected.filter((id) => id !== lesson.id))} />
              <span><span className="font-semibold">{lesson.title}</span> {lesson.progress.locked && <span className="text-amber-700">· yopiq (avvalgi lug'at testi kerak)</span>}
                <span className="mt-1 block text-xs text-slate-500">PDF {lesson.page_start}–{lesson.page_end} · {lesson.exercise_count} saqlangan mashq · {lesson.vocabulary_count} saqlangan so'z · {statusLabel[lesson.progress.status] || lesson.progress.status}</span>
                <span className="mt-1 block text-xs text-slate-500">{lesson.has_explanation ? "Tushuntirish mavjud" : "Tushuntirish saqlanmagan"}{lesson.pending_ocr_pages > 0 ? ` · ${lesson.pending_ocr_pages} sahifa OCR kutmoqda` : ""}{!lesson.page_inventory_complete ? " · sahifa holati to'liq emas" : ""}</span>
              </span>
            </label>;
          })}</div>
          {selected.length > 0 && <p className="mt-3 text-xs text-slate-500">Tanlov dars havolasida saqlanadi; mavjud javoblar va o'qish joyi odatdagidek serverda saqlanadi.</p>}
          <Button className="mt-4" onClick={start} disabled={!target || selected.length !== target}>Tanlangan darslarni boshlash →</Button>
        </Card>
        {data.lessons.some((lesson) => lesson.pending_ocr_pages > 0 || !lesson.page_inventory_complete) && <Card>
          <h2 className="font-semibold">Skan sahifalarda mashqlar yetishmasligi mumkin</h2>
          <p className="mt-1 text-sm text-slate-500">Vision sinovi sahifalarni ko'rib chiqadi. Sinov natijasi va javoblar faqat shu brauzerda saqlanadi, dars mashqlariga qo'shilmaydi. Vision xizmati va yuborishga rozilik kerak.</p>
          <details className="mt-3"><summary className="cursor-pointer text-sm text-brand-600">Vision orqali sahifalarni sinash</summary>
            <VisionMapPreview key={bookId} bookId={bookId} pageCount={data.page_count} initialTopicCount={count} />
          </details>
        </Card>}
      </>}
    </main>
  </>;
}
