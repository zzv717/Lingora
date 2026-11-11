"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { get } from "@/lib/api";
import type { Structure, VocabWord, Job } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, Spinner } from "@/components/ui";

const TYPE_LABELS: Record<string, string> = {
  fill_blank: "Bo'sh joy",
  multiple_choice: "Test (MC)",
  matching: "Moslashtirish",
  translation: "Tarjima",
  sentence_construction: "Gap tuzish",
  writing: "Yozish",
  reading_comprehension: "Matnni o'qish",
  true_false: "To'g'ri/Xato",
};

export default function BookDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [struct, setStruct] = useState<Structure | null>(null);
  const [error, setError] = useState("");
  const [aiWarning, setAiWarning] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setStruct(await get<Structure>(`/books/${id}/structure`));
        try {
          const job = await get<Job | null>(`/books/${id}/status`);
          setAiWarning(job?.warnings?.find((w) => w.code === "AI_ENRICHMENT_FAILED")?.message_uz || "");
        } catch { /* Structure remains usable if status is unavailable. */ }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Yuklanmadi");
      }
    })();
  }, [id]);

  if (error) {
    return (
      <>
        <TopBar title="Kitob" />
        <main className="mx-auto max-w-3xl px-4 py-10">
          <Card><p className="text-sm text-red-500">{error}</p></Card>
        </main>
      </>
    );
  }
  if (!struct) {
    return (
      <>
        <TopBar title="Kitob" />
        <main className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></main>
      </>
    );
  }

  const cov = struct.coverage;
  const grouped = struct.chapters.map((ch) => ({
    chapter: ch,
    lessons: struct.lessons.filter((l) => l.chapter_id === ch.id),
  }));

  return (
    <>
      <TopBar title={struct.book.title} />
      <main className="mx-auto max-w-5xl px-4 py-6 lg:px-8">
        {aiWarning && <p role="alert" className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">{aiWarning}</p>}
        {/* header card */}
        <Card className="mb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{struct.book.title}</h2>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {struct.book.page_count} sahifa · yuklangan:{" "}
                {new Date(struct.book.created_at).toLocaleDateString("uz-UZ")}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone="brand">{cov.exercises} mashq</Badge>
                <Badge tone="blue">{cov.questions} savol</Badge>
                <Badge tone="green">
                  {cov.questions_with_key}/{cov.questions} savol kaliti bor
                </Badge>
                <Badge tone="amber">{cov.vocabulary} lug'at so'zi</Badge>
                {cov.pages_ocr_used > 0 && <Badge tone="slate">{cov.pages_ocr_used} sahifa OCR</Badge>}
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => router.push(`/reader/${id}`)} size="lg">
                O'qishni boshlash →
              </Button>
            </div>
          </div>
          {!cov.ocr_available && (
            <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              ℹ️ Skanerlangan kitoblar uchun OCR serverda sozlanmagan. Matnli PDF'lar to'liq ishlaydi.
            </p>
          )}
        </Card>

        {/* chapters & lessons */}
        <h3 className="mb-3 font-semibold text-slate-700 dark:text-slate-200">Tuzilma</h3>
        <div className="space-y-4">
          {grouped.map(({ chapter, lessons }) => (
            <Card key={chapter.id}>
              <div className="mb-3 flex items-center justify-between">
                <h4 className="font-semibold text-slate-800 dark:text-slate-100">{chapter.title}</h4>
                <Badge>{chapter.page_start}-{chapter.page_end} bet</Badge>
              </div>
              <div className="space-y-2">
                {lessons.map((l) => {
                  const lp = struct.lessons_progress[l.id];
                  return (
                    <LessonRow key={l.id} lesson={l} progress={lp} bookId={id} />
                  );
                })}
              </div>
            </Card>
          ))}
          {struct.chapters.length === 0 && (
            <Card><p className="text-sm text-slate-400">Tuzilma aniqlanmadi.</p></Card>
          )}
        </div>
      </main>
    </>
  );
}

function LessonRow({ lesson, progress, bookId }: {
  lesson: Structure["lessons"][number];
  progress?: Structure["lessons_progress"][string];
  bookId: string;
}) {
  const [words, setWords] = useState<VocabWord[] | null>(null);
  useEffect(() => {
    if (words !== null) return;
    get<VocabWord[]>(`/books/${bookId}/vocabulary?lesson_id=${lesson.id}`)
      .then(setWords)
      .catch(() => setWords([]));
  }, [bookId, lesson.id, words]);

  const locked = progress?.locked;
  const done = progress?.status === "exercises_done" || progress?.status === "completed";
  const gateOk = progress?.vocab_gate_passed ?? true;

  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3.5 py-3 ${
      locked ? "border-slate-200 bg-slate-50 opacity-60 dark:border-slate-800 dark:bg-slate-800/40"
             : "border-slate-200 hover:border-brand-300 dark:border-slate-700 dark:hover:border-brand-700"}`}>
      <div className="min-w-0">
        <Link href={`/reader/${bookId}?lesson=${lesson.id}`}
          className={`font-medium ${locked ? "text-slate-400" : "text-slate-700 hover:text-brand-600 dark:text-slate-200"}`}>
          {lesson.title}
        </Link>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span>{lesson.page_start}-{lesson.page_end} bet</span>
          {lesson.topic && <span>· {lesson.topic}</span>}
          {words && words.length > 0 && <span>· {words.length} so'z</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {!gateOk && <Badge tone="amber">Lug'at testi kerak</Badge>}
        {done && <Badge tone="green">✓ Mashqlar bajarildi</Badge>}
        {locked && (
          <span title="Oldingi dars lug'at testi o'tilishi kerak">
            <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </span>
        )}
        {!locked && (
          <Link href={`/reader/${bookId}?lesson=${lesson.id}`}>
            <Button size="sm" variant="secondary">Ochish</Button>
          </Link>
        )}
      </div>
    </div>
  );
}
