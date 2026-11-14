"use client";
/**
 * Interactive ExerciseCard: renders question controls for all 8 exercise types,
 * debounces autosaves to the backend, restores saved answers, and renders verified/AI
 * grading feedback.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, post, put } from "@/lib/api";
import type { CheckResult, Exercise, Verdict } from "@/lib/types";
import { trustedBlank } from "@/lib/reader-utils";
import { Badge, Button, Card, Spinner, useToast } from "@/components/ui";

export type FbValues = Record<string, Record<string, string>>;

function shuffleRights(pairs: { left: string; right: string }[]) {
  const arr = pairs.map((p, i) => ({ i, text: p.right }));
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor((((i + 1) * 2654435761) % 4294967296) / 4294967296 * (i + 1)) % (i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export function ExerciseCard({
  exercise,
  fbValues,
  onFbChange,
  onChecked,
}: {
  exercise: Exercise;
  fbValues?: FbValues;
  onFbChange?: (qid: string, blankId: string, value: string) => void;
  onChecked?: (verdicts: Verdict[]) => void;
}) {
  const { toast } = useToast();
  const [answers, setAnswers] = useState<Record<string, Record<string, unknown>>>({});
  const [savedStatus, setSavedStatus] = useState<"clean" | "saving" | "saved">("clean");
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [open, setOpen] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const saveVersion = useRef(0);

  // load saved answers from server
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await get<{ question_id: string; content: Record<string, unknown> }[]>(
          `/exercises/${exercise.id}/answers`
        );
        if (cancelled) return;
        const dict: Record<string, Record<string, unknown>> = {};
        for (const r of rows) dict[r.question_id] = r.content || {};
        setAnswers(dict);

        // sync fill_blank answers to reader overlays
        if (onFbChange) {
          for (const q of exercise.questions) {
            const b = dict[q.id]?.blanks as Record<string, string> | undefined;
            if (b) {
              for (const [k, v] of Object.entries(b)) onFbChange(q.id, k, v);
            }
          }
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exercise.id]);

  // Serialize writes so a slower old autosave cannot overwrite a newer answer.
  const enqueueSave = useCallback((newAnswers: Record<string, Record<string, unknown>>, submit: boolean) => {
    const payload = Object.entries(newAnswers).map(([question_id, content]) => ({ question_id, content }));
    const pending = saveQueue.current.catch(() => {}).then(() =>
      put(`/exercises/${exercise.id}/answers`, { answers: payload, submit }));
    saveQueue.current = pending;
    return pending;
  }, [exercise.id]);

  const triggerAutosave = useCallback((newAnswers: Record<string, Record<string, unknown>>) => {
    const version = ++saveVersion.current;
    setSavedStatus("saving");
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(async () => {
      try {
        await enqueueSave(newAnswers, false);
        if (version === saveVersion.current) setSavedStatus("saved");
      } catch {
        if (version === saveVersion.current) {
          setSavedStatus("clean");
          toast("Javob saqlanmadi. Internetni tekshiring va qayta urinib ko'ring.", "error");
        }
      }
    }, 700);
  }, [enqueueSave, toast]);

  // sync fill_blank changes coming from PDF viewer overlays
  useEffect(() => {
    if (!fbValues) return;
    setAnswers((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const q of exercise.questions) {
        if (q.blanks.length > 0 && fbValues[q.id]) {
          const currentBlanks = (next[q.id]?.blanks as Record<string, string>) || {};
          const overlayBlanks = fbValues[q.id];
          let diff = false;
          for (const k in overlayBlanks) {
            if (overlayBlanks[k] !== currentBlanks[k]) {
              diff = true;
              break;
            }
          }
          if (diff) {
            next[q.id] = { ...next[q.id], blanks: { ...currentBlanks, ...overlayBlanks } };
            changed = true;
          }
        }
      }
      if (changed) triggerAutosave(next);
      return changed ? next : prev;
    });
  }, [fbValues, exercise.questions, triggerAutosave]);

  const updateAnswer = (qid: string, content: Record<string, unknown>) => {
    // Clear stale grading result when student edits answer
    if (result) setResult(null);
    setAnswers((prev) => {
      const next = { ...prev, [qid]: content };
      triggerAutosave(next);
      return next;
    });
  };

  const check = async () => {
    setChecking(true);
    try {
      // Flush after older writes and cancel any delayed stale snapshot.
      if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
      ++saveVersion.current;
      await enqueueSave(answers, true);

      const res = await post<CheckResult>(`/exercises/${exercise.id}/check`);
      setResult(res);
      onChecked?.(res.verdicts);
      toast(res.overall_feedback_uz || "Tekshirildi!", res.percent >= 80 ? "success" : "info");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Tekshirib bo'lmadi", "error");
    } finally {
      setChecking(false);
    }
  };

  const answeredCount = Object.values(answers).filter((a) => Object.keys(a).length > 0).length;
  const verdictsByQ = useMemo(() => {
    const map = new Map<string, Verdict>();
    if (result?.verdicts) {
      for (const v of result.verdicts) map.set(v.question_id, v);
    }
    return map;
  }, [result]);

  return (
    <Card className="transition-all">
      {/* header */}
      <div className="flex cursor-pointer items-start justify-between gap-2" onClick={() => setOpen((o) => !o)}>
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-slate-800 dark:text-slate-100">{exercise.ref || exercise.title}</span>
            <Badge tone="slate">{typeLabel(exercise.exercise_type)}</Badge>
            {exercise.topic && <Badge tone="brand">{exercise.topic}</Badge>}
            {result && (result.max_score === 0 ? <Badge tone="slate">Baholanmagan</Badge> : (
              <Badge tone={result.percent >= 80 ? "green" : result.percent >= 50 ? "amber" : "red"}>
                {result.score}/{result.max_score} ({result.percent}%) {result.uncertain ? "· qisman" : ""}
              </Badge>
            ))}
          </div>
          {exercise.instructions && (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{exercise.instructions}</p>
          )}
          {exercise.detection === "ocr" && <p className="mt-1 text-xs text-amber-600">OCR matni xato bo'lishi mumkin. Javob kaliti tasdiqlanmagan; tekshirish AI sozlangan bo'lsa matn va javobni AI xizmatiga yuborishi mumkin.</p>}
          {exercise.detection === "vision" && <p className="mt-1 text-xs text-amber-600">Bu mashq sahifa rasmidan AI yordamida ajratilgan va tekshirilmagan. Javob kaliti yo'q; matnni asl sahifa bilan solishtiring.</p>}
        </div>
        <div className="flex items-center gap-2">
          {savedStatus === "saving" && <span className="text-[11px] text-slate-400">saqlanmoqda…</span>}
          {savedStatus === "saved" && <span className="text-[11px] text-emerald-500">saqlandi ✓</span>}
          <button className="text-slate-400 hover:text-slate-600" aria-label="Toggle">
            {open ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {open && (
        <>
          {/* questions */}
          <div className="mt-4 space-y-4">
            {!loaded ? (
              <div className="flex justify-center py-4">
                <Spinner className="h-5 w-5 text-brand-500" />
              </div>
            ) : (
              exercise.questions.map((q, idx) => (
                <QuestionView
                  key={q.id}
                  q={q}
                  index={idx}
                  exercise={exercise}
                  answer={answers[q.id] || {}}
                  onChange={(c) => updateAnswer(q.id, c)}
                  verdict={verdictsByQ.get(q.id)}
                  fbBlank={fbValues?.[q.id]}
                  fbOnBlank={onFbChange ? (k, v) => onFbChange(q.id, k, v) : undefined}
                />
              ))
            )}
          </div>

          {/* actions */}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3 dark:border-slate-800">
            <span className="text-xs text-slate-400">
              {answeredCount}/{exercise.questions.length} savol javoblandi
            </span>
            <Button onClick={check} loading={checking} disabled={checking || answeredCount === 0} size="sm">
              Tekshirish (Check)
            </Button>
          </div>

          {/* results breakdown */}
          {result && (
            <div className="mt-4 space-y-2 rounded-xl bg-slate-50 p-3 text-xs dark:bg-slate-800/60">
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                Natija: {result.overall_feedback_uz}
              </div>
              {result.verdicts.map((v) => (
                <div key={v.question_id} className="rounded-lg bg-white p-2.5 dark:bg-slate-900">
                  <div className="flex items-center gap-2 font-medium">
                    {v.correct === true ? (
                      <span className="text-emerald-500">✓</span>
                    ) : v.correct === false ? (
                      <span className="text-red-500">✗</span>
                    ) : (
                      <span className="text-slate-400">?</span>
                    )}
                    Savol {v.number}
                    <span className="ml-auto text-xs text-slate-400">
                      {v.source === "key" ? "kitob kaliti" : v.source === "ai" ? "AI baholash" : v.source === "deterministic" ? "qoidalar" : "tekshirilmagan"}
                    </span>
                  </div>
                  {v.correct === false && v.expected && (
                    <p className="mt-1 text-slate-600 dark:text-slate-300">
                      To'g'ri javob: <b className="text-emerald-600 dark:text-emerald-400">{v.expected}</b>
                    </p>
                  )}
                  {v.explanation_uz && (
                    <p className="mt-1 text-slate-500 dark:text-slate-400">{v.explanation_uz}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function QuestionView({
  q,
  index,
  exercise,
  answer,
  onChange,
  verdict,
  fbBlank,
  fbOnBlank,
}: {
  q: Exercise["questions"][number];
  index: number;
  exercise: Exercise;
  answer: Record<string, unknown>;
  onChange: (content: Record<string, unknown>) => void;
  verdict?: Verdict;
  fbBlank?: Record<string, string>;
  fbOnBlank?: (blankId: string, value: string) => void;
}) {
  const state = verdict?.correct === true ? "correct" : verdict?.correct === false ? "wrong" : "neutral";

  // Pre-compute shuffled rights for matching questions safely (always called, never conditional)
  const matchingRights = useMemo(() => {
    if (exercise.exercise_type === "matching" && q.matching_pairs.length > 0) {
      return shuffleRights(q.matching_pairs);
    }
    return [];
  }, [exercise.exercise_type, q.matching_pairs]);

  if (exercise.exercise_type === "fill_blank") {
    const hasBbox = q.blanks.some(trustedBlank);
    const unlocated = q.blanks.some((b) => !trustedBlank(b));
    const blanksDict = (answer.blanks as Record<string, string>) || {};
    return (
      <div className="text-sm">
        <p className="mb-1.5 font-medium text-slate-700 dark:text-slate-200">
          {q.number || index + 1}. {renderPrompt(q.prompt)}
        </p>
        {hasBbox && <p className="mt-1 text-xs text-slate-400">⬆ Aniq joylashgan javoblarni sahifaga yozing.</p>}
        {unlocated && <p className="mt-1 text-xs text-amber-600">Ba'zi joylar aniq topilmadi. Javobni quyida kiriting.</p>}
        <div className="flex flex-wrap gap-2">
          {q.blanks.map((b, bi) => !trustedBlank(b) && (
            <input
              key={b.id || bi}
              value={blanksDict[b.id || `b${bi + 1}`] || ""}
              onChange={(e) => onChange({ blanks: { ...blanksDict, [b.id || `b${bi + 1}`]: e.target.value } })}
              placeholder={`${bi + 1}-bo'sh joy`}
              aria-label={`${q.number || index + 1}-savol, ${bi + 1}-bo'sh joy`}
              className={`w-40 rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-brand-500/30 dark:bg-slate-800 dark:text-white ${
                state === "correct" ? "border-emerald-400" : state === "wrong" ? "border-red-400" : "border-slate-300 dark:border-slate-600"
              }`}
            />
          ))}
        </div>
        {verdict?.correct === false && verdict.expected && (
          <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">To'g'ri javob: {verdict.expected}</p>
        )}
      </div>
    );
  }

  if (exercise.exercise_type === "multiple_choice") {
    const selection = (answer.selection as string) || "";
    return (
      <div>
        <p className="mb-2 font-medium text-slate-700 dark:text-slate-200">
          {q.number || index + 1}. {q.prompt}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {q.options.map((o) => (
            <button
              key={o.id}
              onClick={() => onChange({ selection: o.letter })}
              className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left text-sm transition ${
                selection === o.letter
                  ? "border-brand-500 bg-brand-50 ring-2 ring-brand-500/20 dark:bg-brand-900/30"
                  : "border-slate-200 hover:border-brand-300 dark:border-slate-700 dark:hover:border-brand-700"
              }`}>
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  selection === o.letter ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300"
                }`}>
                {o.letter}
              </span>
              <span className="text-slate-700 dark:text-slate-200">{o.text}</span>
            </button>
          ))}
        </div>
        {verdict && verdict.correct === false && verdict.expected && (
          <p className="mt-1.5 text-xs text-emerald-600 dark:text-emerald-400">To'g'ri javob: {verdict.expected}</p>
        )}
      </div>
    );
  }

  if (exercise.exercise_type === "true_false") {
    const selection = (answer.selection as string) || "";
    return (
      <div>
        <p className="mb-2 font-medium text-slate-700 dark:text-slate-200">
          {q.number || index + 1}. {q.prompt}
        </p>
        <div className="flex gap-2">
          {[["true", "To'g'ri ✓"], ["false", "Noto'g'ri ✗"]].map(([val, label]) => (
            <button
              key={val}
              onClick={() => onChange({ selection: val })}
              className={`rounded-xl border px-4 py-2 text-sm font-medium transition ${
                selection === val
                  ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                  : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (exercise.exercise_type === "matching" && q.matching_pairs.length > 0) {
    const pairs = q.matching_pairs;
    const rights = matchingRights;
    const chosen = (answer.pairs as Record<string, string>) || {};
    return (
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          {pairs.map((p, i) => (
            <div key={i} className="rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
              <span className="mr-2 font-bold text-brand-500">{i + 1}.</span>
              <span className="text-slate-700 dark:text-slate-200">{p.left}</span>
              <select
                value={chosen[String(i)] || ""}
                onChange={(e) => onChange({ pairs: { ...chosen, [String(i)]: e.target.value } })}
                className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-800">
                <option value="">— tanlang —</option>
                {rights.map((r) => (
                  <option key={r.i} value={String(r.i)}>
                    {String.fromCharCode(65 + r.i)}) {r.text}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {rights.map((r) => (
            <div
              key={r.i}
              className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800/50">
              <span className="mr-2 font-bold text-violet-500">{String.fromCharCode(65 + r.i)}.</span>
              <span className="text-slate-700 dark:text-slate-200">{r.text}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // open text types
  const text = (answer.text as string) || "";
  const multiline = exercise.exercise_type === "writing" || exercise.exercise_type === "reading_comprehension";
  return (
    <div>
      <p className="mb-2 font-medium text-slate-700 dark:text-slate-200">
        {q.number || index + 1}. {renderPrompt(q.prompt)}
      </p>
      {multiline ? (
        <textarea
          rows={3}
          value={text}
          onChange={(e) => onChange({ text: e.target.value })}
          placeholder="Javobingizni batafsil yozing..."
          className="w-full rounded-xl border border-slate-300 bg-white p-3 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
        />
      ) : (
        <input
          value={text}
          onChange={(e) => onChange({ text: e.target.value })}
          placeholder="Javobingizni yozing..."
          className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
        />
      )}
      {verdict && (
        <div className="mt-2 text-xs">
          {verdict.correct === true && <span className="font-medium text-emerald-600">✓ To'g'ri</span>}
          {verdict.correct === false && (
            <span className="font-medium text-red-500">
              ✗ Noto'g'ri {verdict.expected ? `(to'g'risi: ${verdict.expected})` : ""}
            </span>
          )}
          {verdict.correct === null && (
            <span className="text-slate-500">ℹ️ {verdict.explanation_uz}</span>
          )}
        </div>
      )}
    </div>
  );
}

function renderPrompt(prompt: string) {
  return prompt;
}

function typeLabel(t: string): string {
  return (
    {
      fill_blank: "Bo'sh joy",
      multiple_choice: "Test (MC)",
      matching: "Moslashtirish",
      translation: "Tarjima",
      sentence_construction: "Gap tuzish",
      sentence_transformation: "Gapni o'zgartirish",
      word_formation: "So'z yasash",
      error_correction: "Xatoni tuzatish",
      short_answer: "Qisqa javob",
      writing: "Yozish",
      reading_comprehension: "Matnni o'qish",
      true_false: "To'g'ri/Xato",
    }[t] || t
  );
}
