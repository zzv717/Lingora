"use client";
/** Interactive exercise card: renders each exercise type with inputs, autosave and AI-checked results.
 *  fill_blank answers with extracted bboxes are ALSO rendered over the PDF (controlled by the reader);
 *  the card keeps the authoritative merged state and autosaves everything. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get, post, put } from "@/lib/api";
import type { CheckResult, Exercise, Verdict } from "@/lib/types";
import { Badge, Button, Card, Progress, Spinner } from "@/components/ui";

type Answers = Record<string, Record<string, unknown>>; // question_id -> content
export type FbValues = Record<string, Record<string, string>>; // qid -> blankId -> value

const TYPE_BADGE: Record<string, { label: string; tone: "brand" | "blue" | "amber" | "green" | "slate" }> = {
  fill_blank: { label: "Bo'sh joy", tone: "brand" },
  multiple_choice: { label: "Test", tone: "blue" },
  matching: { label: "Moslashtirish", tone: "amber" },
  translation: { label: "Tarjima", tone: "green" },
  sentence_construction: { label: "Gap tuzish", tone: "slate" },
  writing: { label: "Yozish", tone: "slate" },
  reading_comprehension: { label: "O'qish", tone: "blue" },
  true_false: { label: "To'g'ri/Xato", tone: "amber" },
};

export function ExerciseCard({ exercise, onJumpToPage, fbValues = {}, fbOnChange, onChecked }: {
  exercise: Exercise;
  onJumpToPage?: (n: number) => void;
  /** live fill-blank blank values owned by the reader (PDF overlay inputs) */
  fbValues?: FbValues;
  fbOnChange?: (qid: string, blankId: string, value: string) => void;
  /** notify parent after grading so PDF overlays can be colored */
  onChecked?: (verdicts: Verdict[]) => void;
}) {
  const [answers, setAnswers] = useState<Answers>({});
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<Answers>({});
  const badge = TYPE_BADGE[exercise.exercise_type] || { label: exercise.exercise_type, tone: "slate" as const };

  // merge PDF-overlay fill-blank values into the authoritative answer map
  const merged: Answers = useMemo(() => {
    const out: Answers = { ...answers };
    for (const [qid, blanks] of Object.entries(fbValues)) {
      if (Object.keys(blanks).length === 0) continue;
      out[qid] = { ...(out[qid] || {}), blanks: { ...blanks, ...((out[qid]?.blanks as object) || {}) } };
    }
    return out;
  }, [answers, fbValues]);
  latest.current = merged;

  // load saved answers (resume support)
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setResult(null);
    (async () => {
      try {
        const saved = await get<{ question_id: string; content: Record<string, unknown> }[]>(
          `/exercises/${exercise.id}/answers`);
        if (cancelled) return;
        const map: Answers = {};
        for (const s of saved) map[s.question_id] = s.content;
        setAnswers(map);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [exercise.id]);

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      try {
        const all = latest.current;
        await put(`/exercises/${exercise.id}/answers`, {
          answers: Object.entries(all).map(([question_id, content]) => ({ question_id, content })),
        });
        setSavedFlash(true);
        setTimeout(() => setSavedFlash(false), 1200);
      } catch { /* retried on next change */ }
    }, 800);
  }, [exercise.id]);

  // autosave also when overlay values change
  useEffect(() => {
    if (loading) return;
    if (Object.keys(fbValues).length > 0) scheduleSave();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fbValues]);

  const update = (qid: string, content: Record<string, unknown>) => {
    setAnswers((prev) => ({ ...prev, [qid]: content }));
    scheduleSave();
  };

  const check = async () => {
    setChecking(true);
    try {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      await put(`/exercises/${exercise.id}/answers`, {
        answers: Object.entries(merged).map(([question_id, content]) => ({ question_id, content })),
      });
      const res = await post<CheckResult>(`/exercises/${exercise.id}/check`);
      setResult(res);
      onChecked?.(res.verdicts);
    } finally {
      setChecking(false);
    }
  };

  const verdictFor = (qid: string): Verdict | undefined =>
    result?.verdicts.find((v) => v.question_id === qid);

  const answeredCount = exercise.questions.filter((q) => {
    const a = merged[q.id];
    if (!a) return false;
    return Object.values(a).some((v) =>
      typeof v === "string" ? v.trim() : v && Object.keys(v as object).length > 0);
  }).length;

  return (
    <Card className="scroll-mt-20">
      <div id={`exercise-${exercise.id}`} />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <button
            onClick={() => onJumpToPage?.(exercise.page_number)}
            className="text-xs text-brand-600 hover:underline dark:text-brand-400">
            {exercise.ref} · {exercise.page_number}-bet ↗
          </button>
          {savedFlash && <span className="text-xs text-emerald-500">✓ saqlandi</span>}
        </div>
        {exercise.topic && <span className="text-xs text-slate-400">{exercise.topic}</span>}
      </div>
      {exercise.instructions && (
        <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">{exercise.instructions}</p>
      )}

      {loading ? (
        <div className="flex justify-center py-4"><Spinner className="h-5 w-5 text-brand-500" /></div>
      ) : (
        <>
          <div className="space-y-4">
            {exercise.questions.map((q, qi) => (
              <QuestionView
                key={q.id}
                q={q}
                index={qi}
                exercise={exercise}
                answer={merged[q.id] || {}}
                fbBlank={fbValues[q.id]}
                fbOnBlank={(blankId, value) => fbOnChange?.(q.id, blankId, value)}
                onChange={(content) => update(q.id, content)}
                verdict={verdictFor(q.id)}
              />
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button onClick={check} loading={checking} disabled={answeredCount === 0}>
              Javoblarni tekshirish
            </Button>
            <span className="text-xs text-slate-400">
              {answeredCount}/{exercise.questions.length} javob berildi · avtosaqlash yoqilgan
            </span>
          </div>

          {result && (
            <div className="mt-4 space-y-3">
              <div className={`rounded-xl px-4 py-3 text-sm font-medium ${
                result.percent >= 80 ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                : result.percent >= 50 ? "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                : "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300"}`}>
                {result.overall_feedback_uz}
                {result.max_score > 0 && (
                  <span className="float-right font-bold">{result.score}/{result.max_score} · {result.percent}%</span>
                )}
                {result.uncertain && (
                  <div className="mt-1 text-xs font-normal opacity-80">
                    ⚠️ Ba'zi javoblar noaniq baholandi — pastdagi izohlarga e'tibor bering.
                  </div>
                )}
              </div>
              <Progress value={result.percent} tone={result.percent >= 80 ? "green" : result.percent >= 50 ? "amber" : "brand"} />
              {result.verdicts.filter((v) => !v.correct || v.explanation_uz).map((v) => (
                <div key={v.question_id}
                  className={`rounded-xl border px-3.5 py-2.5 text-sm ${
                    v.correct === true ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/30"
                    : v.correct === false ? "border-red-200 bg-red-50/60 dark:border-red-900 dark:bg-red-950/30"
                    : "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/60"}`}>
                  <div className="flex items-center gap-2 font-medium text-slate-700 dark:text-slate-200">
                    {v.correct === true ? <span className="text-emerald-500">✓</span>
                      : v.correct === false ? <span className="text-red-500">✗</span>
                      : <span className="text-slate-400">?</span>}
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

function QuestionView({ q, index, exercise, answer, onChange, verdict, fbBlank, fbOnBlank }: {
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

  if (exercise.exercise_type === "fill_blank") {
    const hasBbox = q.blanks.some((b) => b.bbox);
    const blanksDict = (answer.blanks as Record<string, string>) || {};
    if (hasBbox) {
      // inputs live on the PDF overlay; here we only show feedback
      return (
        <div className="text-sm">
          <p className="font-medium text-slate-700 dark:text-slate-200">
            {q.number || index + 1}. {renderPrompt(q.prompt)}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            ⬆ Javoblarni sahifadagi bo'sh joylarga yozing.
          </p>
          {verdict && !verdict.correct && verdict.expected && (
            <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">To'g'ri javob: {verdict.expected}</p>
          )}
          {Object.keys(blanksDict).length === 0 && (
            <p className="mt-1 text-xs text-amber-500">Hali to'ldirilmagan</p>
          )}
        </div>
      );
    }
    return (
      <div className="text-sm">
        <p className="mb-1.5 font-medium text-slate-700 dark:text-slate-200">
          {q.number || index + 1}. {renderPrompt(q.prompt)}
        </p>
        <div className="flex flex-wrap gap-2">
          {q.blanks.map((b, bi) => (
            <input key={b.id || bi}
              value={blanksDict[b.id || `b${bi + 1}`] || ""}
              onChange={(e) => onChange({ blanks: { ...blanksDict, [b.id || `b${bi + 1}`]: e.target.value } })}
              placeholder={`${bi + 1}-bo'sh joy`}
              className={`w-40 rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-brand-500/30 dark:bg-slate-800 dark:text-white ${
                state === "correct" ? "border-emerald-400" : state === "wrong" ? "border-red-400" : "border-slate-300 dark:border-slate-600"}`} />
          ))}
        </div>
        {verdict && !verdict.correct && verdict.expected && (
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
            <button key={o.id}
              onClick={() => onChange({ selection: o.letter })}
              className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 text-left text-sm transition ${
                selection === o.letter ? "border-brand-500 bg-brand-50 ring-2 ring-brand-500/20 dark:bg-brand-900/30"
                  : "border-slate-200 hover:border-brand-300 dark:border-slate-700 dark:hover:border-brand-700"}`}>
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                selection === o.letter ? "bg-brand-600 text-white" : "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300"}`}>
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
            <button key={val}
              onClick={() => onChange({ selection: val })}
              className={`rounded-xl border px-4 py-2 text-sm font-medium transition ${
                selection === val ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                  : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (exercise.exercise_type === "matching" && q.matching_pairs.length > 0) {
    const pairs = q.matching_pairs;
    const rights = useMemo(() => {
      const arr = pairs.map((p, i) => ({ i, text: p.right }));
      // deterministic shuffle so the challenge is not trivially aligned
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor((((i + 1) * 2654435761) % 4294967296) / 4294967296 * (i + 1)) % (i + 1);
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }
      return arr;
    }, [pairs]);
    const chosen = (answer.pairs as Record<string, string>) || {};
    return (
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          {pairs.map((p, i) => (
            <div key={i} className="rounded-xl border border-slate-200 px-3 py-2 text-sm dark:border-slate-700">
              <span className="mr-2 font-bold text-brand-500">{i + 1}.</span>
              <span className="text-slate-700 dark:text-slate-200">{p.left}</span>
              <select value={chosen[String(i)] || ""}
                onChange={(e) => onChange({ pairs: { ...chosen, [String(i)]: e.target.value } })}
                className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-800">
                <option value="">— tanlang —</option>
                {rights.map((r) => (
                  <option key={r.i} value={String(r.i)}>{String.fromCharCode(65 + r.i)}) {r.text}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          {rights.map((r) => (
            <div key={r.i} className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm dark:border-slate-600 dark:bg-slate-800/50">
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
      {q.passage && (
        <div className="mb-2 rounded-xl bg-slate-50 p-3 text-sm italic text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
          {q.passage}
        </div>
      )}
      {multiline ? (
        <textarea
          value={text}
          onChange={(e) => onChange({ text: e.target.value })}
          rows={5}
          placeholder="Javobingizni yozing..."
          className={`w-full rounded-xl border px-3.5 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-brand-500/30 dark:bg-slate-800 dark:text-white ${
            state === "correct" ? "border-emerald-400" : state === "wrong" ? "border-red-400" : "border-slate-300 dark:border-slate-600"}`} />
      ) : (
        <input
          value={text}
          onChange={(e) => onChange({ text: e.target.value })}
          placeholder="Javobingiz..."
          className={`w-full rounded-xl border px-3.5 py-2.5 text-sm outline-none transition focus:ring-2 focus:ring-brand-500/30 dark:bg-slate-800 dark:text-white ${
            state === "correct" ? "border-emerald-400" : state === "wrong" ? "border-red-400" : "border-slate-300 dark:border-slate-600"}`} />
      )}
      {verdict?.correct === false && verdict.expected && (
        <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">To'g'ri javob: {verdict.expected}</p>
      )}
    </div>
  );
}

function renderPrompt(prompt: string): React.ReactNode {
  const parts = prompt.split(/(\{b\d+\})/g);
  return parts.map((p, i) =>
    /^\{b\d+\}$/.test(p) ? (
      <span key={i} className="mx-1 inline-block w-16 border-b-2 border-brand-400 align-bottom">&nbsp;</span>
    ) : (
      <span key={i}>{p}</span>
    ));
}
