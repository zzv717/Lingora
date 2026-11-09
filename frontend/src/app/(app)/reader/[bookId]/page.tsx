"use client";
/**
 * Interactive reader: the ORIGINAL PDF page with live answer overlays positioned at
 * extracted coordinates, plus a lesson sidebar (grammar note, exercises, AI grading,
 * vocabulary gate). Answers autosave; progress resumes after refresh/close.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { get, post } from "@/lib/api";
import type { Exercise, Lesson, Structure, VocabSession, Verdict } from "@/lib/types";
import { Button, Card, Spinner, useToast } from "@/components/ui";
import { PdfViewer, type BlankOverlay } from "@/components/reader/pdf-viewer";
import { ExerciseCard, type FbValues } from "@/components/reader/exercise-card";

function ReaderInner() {
  const { bookId } = useParams<{ bookId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const { toast } = useToast();

  const [struct, setStruct] = useState<Structure | null>(null);
  const [lessonId, setLessonId] = useState<string>("");
  const [exercises, setExercises] = useState<Exercise[] | null>(null);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [page, setPage] = useState(1);
  const [startingGate, setStartingGate] = useState(false);
  const [fbValues, setFbValues] = useState<FbValues>({});
  const [overlayStates, setOverlayStates] = useState<Record<string, "correct" | "wrong">>({});
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    (async () => {
      const s = await get<Structure>(`/books/${bookId}/structure`);
      setStruct(s);
      const requested = search.get("lesson");
      const firstOpen = s.lessons.find((l) => !s.lessons_progress[l.id]?.locked) || s.lessons[0];
      setLessonId(requested && s.lessons.some((l) => l.id === requested) ? requested : firstOpen?.id || "");
    })().catch(() => toast("Kitob yuklanmadi", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  useEffect(() => {
    if (!lessonId || !struct) return;
    setExercises(null);
    setFbValues({});
    setOverlayStates({});
    (async () => {
      const exs = await get<Exercise[]>(`/lessons/${lessonId}/exercises`);
      setExercises(exs);
      const l = struct.lessons.find((x) => x.id === lessonId) || null;
      setLesson(l);
      const lp = struct.lessons_progress[lessonId];
      setPage(l ? (lp?.last_page && lp.last_page >= l.page_start ? lp.last_page : l.page_start) : 1);
    })().catch(() => toast("Mashqlar yuklanmadi", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId]);

  // study-time heartbeat (60s) — feeds streaks & daily activity
  useEffect(() => {
    heartbeatRef.current = setInterval(() => {
      fetch("/backend/api/v1/progress/heartbeat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ seconds: 60, lesson_id: lessonId || undefined, page }),
      }).catch(() => {});
    }, 60_000);
    return () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, [lessonId, page]);

  const onFbChange = useCallback((qid: string, blankId: string, value: string) => {
    setFbValues((prev) => ({ ...prev, [qid]: { ...(prev[qid] || {}), [blankId]: value } }));
  }, []);

  const onChecked = useCallback((verdicts: Verdict[]) => {
    const states: Record<string, "correct" | "wrong"> = {};
    for (const v of verdicts) {
      if (v.correct !== null) states[v.question_id] = v.correct ? "correct" : "wrong";
    }
    setOverlayStates((prev) => ({ ...prev, ...states }));
  }, []);

  const lessonProgress = struct?.lessons_progress[lessonId];
  const gateNeeded = lessonProgress && lessonProgress.has_vocabulary && !lessonProgress.vocab_gate_passed;

  const startGate = async () => {
    setStartingGate(true);
    try {
      const s = await post<VocabSession>(`/vocabulary/sessions?lesson_id=${lessonId}&kind=lesson_gate`);
      router.push(`/practice/${s.id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    } finally {
      setStartingGate(false);
    }
  };

  // live overlay inputs for fill_blank questions on the CURRENT page
  const overlays: BlankOverlay[] = useMemo(() => {
    if (!exercises) return [];
    const out: BlankOverlay[] = [];
    for (const ex of exercises) {
      if (ex.page_number !== page || ex.exercise_type !== "fill_blank") continue;
      for (const q of ex.questions) {
        q.blanks.forEach((b, bi) => {
          if (!b.bbox) return;
          const key = `${q.id}:${b.id || bi}`;
          out.push({
            id: key,
            bbox: b.bbox as [number, number, number, number],
            value: fbValues[q.id]?.[b.id || `b${bi + 1}`] || "",
            onChange: (v) => onFbChange(q.id, b.id || `b${bi + 1}`, v),
            state: overlayStates[q.id],
          });
        });
      }
    }
    return out;
  }, [exercises, page, fbValues, onFbChange, overlayStates]);

  if (!struct) {
    return (
      <main className="flex min-h-[70vh] items-center justify-center">
        <Spinner className="h-8 w-8 text-brand-500" />
      </main>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex min-w-0 items-center gap-2">
          <Link href={`/books/${bookId}`} className="shrink-0 text-sm text-slate-400 hover:text-brand-500">← Kitob</Link>
          <select
            value={lessonId}
            onChange={(e) => setLessonId(e.target.value)}
            className="max-w-[220px] truncate rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800">
            {struct.lessons.map((l) => (
              <option key={l.id} value={l.id} disabled={struct.lessons_progress[l.id]?.locked}>
                {l.title}{struct.lessons_progress[l.id]?.locked ? " 🔒" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {gateNeeded && (
            <Button size="sm" onClick={startGate} loading={startingGate}>
              🔑 Lug'at testi
            </Button>
          )}
          <Link href={`/tutor?book=${bookId}&lesson=${lessonId}`}>
            <Button size="sm" variant="secondary">🤖 Murabbiy</Button>
          </Link>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="thin-scroll min-w-0 flex-1 space-y-4 overflow-y-auto p-3">
          <PdfViewer
            bookId={bookId}
            pageNumber={page}
            onGoTo={setPage}
            overlays={overlays}
          />
          {/* exercises below the PDF on medium screens */}
          <div className="thin-scroll space-y-4 2xl:hidden">
            {exercises === null ? (
              <div className="flex justify-center py-8"><Spinner className="h-6 w-6 text-brand-500" /></div>
            ) : (
              <>
                {lesson && <LessonInfo lesson={lesson} />}
                {gateNeeded && (
                  <Card className="border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30">
                    <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                      Keyingi darsni ochish uchun bu darsning lug'at testini o'tish kerak.
                    </p>
                    <Button size="sm" className="mt-2" onClick={startGate} loading={startingGate}>
                      Testni boshlash
                    </Button>
                  </Card>
                )}
                {exercises.length === 0 && (
                  <Card>
                    <p className="text-sm text-slate-500 dark:text-slate-400">
                      Bu darsda mashq topilmadi — AI murabbiydan qo'shimcha mashq so'rashingiz mumkin.
                    </p>
                  </Card>
                )}
                {exercises.map((ex) => (
                  <ExerciseCard key={ex.id} exercise={ex}
                    fbValues={filterFb(fbValues, ex)} onFbChange={onFbChange} onChecked={onChecked} />
                ))}
              </>
            )}
          </div>
        </div>

        {/* wide-screen exercise sidebar */}
        <aside className="thin-scroll hidden w-[440px] shrink-0 space-y-4 overflow-y-auto border-l border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950 2xl:block">
          {exercises === null ? (
            <div className="flex justify-center py-8"><Spinner className="h-6 w-6 text-brand-500" /></div>
          ) : (
            <>
              {lesson && <LessonInfo lesson={lesson} />}
              {gateNeeded && (
                <Card className="border-amber-300 bg-amber-50 dark:border-amber-700 dark:bg-amber-950/30">
                  <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                    Keyingi darsni ochish uchun bu darsning lug'at testini o'tish kerak.
                  </p>
                  <Button size="sm" className="mt-2" onClick={startGate} loading={startingGate}>
                    Testni boshlash
                  </Button>
                </Card>
              )}
              {exercises.length === 0 && (
                <Card>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Bu darsda mashq topilmadi — AI murabbiydan qo'shimcha mashq so'rashingiz mumkin.
                  </p>
                </Card>
              )}
              {exercises.map((ex) => (
                <ExerciseCard key={ex.id} exercise={ex}
                  fbValues={filterFb(fbValues, ex)} onFbChange={onFbChange} onChecked={onChecked} />
              ))}
            </>
          )}
        </aside>
      </div>
    </div>
  );
}

function filterFb(fb: FbValues, ex: Exercise): FbValues {
  const qids = new Set(ex.questions.map((q) => q.id));
  const out: FbValues = {};
  for (const [qid, v] of Object.entries(fb)) if (qids.has(qid)) out[qid] = v;
  return out;
}

function LessonInfo({ lesson }: { lesson: Lesson }) {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <button onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-slate-800 dark:text-slate-100">{lesson.title}</h3>
          <span className="text-xs text-slate-400">{open ? "▾" : "▸"}</span>
        </div>
      </button>
      {lesson.topic && <p className="mt-0.5 text-xs text-slate-400">{lesson.topic}</p>}
      {open && lesson.grammar_explanation_uz && (
        <div className="mt-3 whitespace-pre-wrap rounded-xl bg-brand-50/70 p-3 text-sm text-slate-700 dark:bg-brand-900/20 dark:text-slate-300">
          {lesson.grammar_explanation_uz}
        </div>
      )}
      {open && !lesson.grammar_explanation_uz && (
        <p className="mt-2 text-xs text-slate-400">
          AI tushuntirishi hozircha yo'q — murabbiydan so'rashingiz mumkin.
        </p>
      )}
    </Card>
  );
}

export default function ReaderPage() {
  return (
    <Suspense fallback={<div className="flex min-h-[70vh] items-center justify-center"><Spinner className="h-8 w-8 text-brand-500" /></div>}>
      <ReaderInner />
    </Suspense>
  );
}
