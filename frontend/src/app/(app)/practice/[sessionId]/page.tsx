"use client";
/** Vocabulary challenge runner: mixed question types, TTS listening, written recall,
 *  failed-word reintroduction with sync refetching, pass-score gate. */
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { post } from "@/lib/api";
import { speak } from "@/lib/tts";
import type { VocabAnswerResult, VocabItem, VocabSession } from "@/lib/types";
import { Button, Card, ErrorBox, Input, Progress, Spinner } from "@/components/ui";

interface DoneState {
  passed: boolean;
  score: number;
  required_score: number;
  message_uz: string;
  gate_opened: boolean;
}

export default function PracticePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const [session, setSession] = useState<VocabSession | null>(null);
  const [index, setIndex] = useState(0);
  const [input, setInput] = useState("");
  const [feedback, setFeedback] = useState<VocabAnswerResult | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState<DoneState | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    (async () => {
      try {
        const { get } = await import("@/lib/api");
        const s = await get<VocabSession>(`/vocabulary/sessions/${sessionId}`);
        setSession(s);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Test topilmadi");
      }
    })();
  }, [sessionId]);

  // auto-play audio for listening/spelling tasks
  useEffect(() => {
    const item = session?.items[index];
    if (item && (item.type === "listening" || item.type === "spelling") && item.audio_text) {
      speak(item.audio_text);
    }
  }, [session, index]);

  if (error) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-4 px-4">
        <ErrorBox message={error} />
        <Link href="/vocabulary"><Button variant="secondary">Lug'atga qaytish</Button></Link>
      </main>
    );
  }
  if (!session) {
    return <main className="flex min-h-screen items-center justify-center"><Spinner className="h-8 w-8 text-brand-500" /></main>;
  }

  const item: VocabItem | undefined = session.items[index];

  const submit = async (response: string) => {
    if (!item || busy || feedback) return;
    setBusy(true);
    try {
      const res = await post<VocabAnswerResult>(`/vocabulary/sessions/${sessionId}/answer`, {
        item_id: item.item_id,
        response,
      });

      // If word failed and was requeued, append it to local session state
      if (res.requeued_item) {
        setSession((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            items: [...prev.items, res.requeued_item!],
            total_items: prev.total_items + 1,
          };
        });
      }

      setFeedback(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xatolik");
    } finally {
      setBusy(false);
    }
  };

  const next = async () => {
    setFeedback(null);
    setInput("");
    if (index + 1 < session.items.length) {
      setIndex(index + 1);
      setTimeout(() => inputRef.current?.focus(), 50);
      return;
    }
    // finish
    setBusy(true);
    try {
      const res = await post<DoneState>(`/vocabulary/sessions/${sessionId}/complete`);
      setDone(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Xatolik");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md text-center">
          <div className="mb-3 text-6xl">{done.passed ? "🎉" : "💪"}</div>
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
            {done.passed ? "Test muvaffaqiyatli o'tildi!" : "Yana bir bor urinib ko'ring"}
          </h1>
          <p className="mt-2 text-4xl font-extrabold text-brand-600">{done.score}%</p>
          <p className="mt-1 text-sm text-slate-500">Talab: {done.required_score}%</p>
          <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{done.message_uz}</p>
          <div className="mt-6 flex flex-col gap-2">
            <Button onClick={() => router.push("/vocabulary")}>Lug'atga qaytish</Button>
            <Button variant="secondary" onClick={() => router.push("/dashboard")}>Boshqaruv paneli</Button>
          </div>
        </Card>
      </main>
    );
  }

  if (!item) return null;
  const isChoice = item.options.length > 0;

  return (
    <main className="flex min-h-screen flex-col items-center px-4 py-8">
      <div className="w-full max-w-xl">
        <div className="mb-4 flex items-center justify-between text-sm text-slate-500">
          <Link href="/vocabulary" className="hover:text-brand-500">← Chiqish</Link>
          <span>{index + 1} / {session.items.length}</span>
        </div>
        <Progress value={((index + 1) / session.items.length) * 100} />

        <Card className="mt-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
              {typeLabel(item.type)}
            </span>
            {item.audio_text && (
              <button onClick={() => speak(item.audio_text)}
                className="rounded-full bg-brand-100 p-2 text-brand-600 transition hover:bg-brand-200 dark:bg-brand-900/40 dark:text-brand-300"
                aria-label="Tinglash">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                </svg>
              </button>
            )}
          </div>

          <p className="mb-4 text-center text-2xl font-bold text-slate-800 dark:text-slate-100">
            {item.type === "listening" ? "🔊 Tinglang..." : item.prompt}
          </p>
          {item.hint && <p className="mb-4 text-center text-sm text-slate-400">{item.hint}</p>}

          {isChoice ? (
            <div className="grid gap-2">
              {item.options.map((o) => {
                const chosen = feedback && feedback.response === o.key;
                const isRight = feedback && o.key === feedback.expected;
                return (
                  <button key={o.key}
                    disabled={!!feedback || busy}
                    onClick={() => submit(o.key)}
                    className={`rounded-xl border px-4 py-3 text-left text-sm font-medium transition ${
                      feedback
                        ? isRight ? "border-emerald-500 bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                          : chosen ? "border-red-500 bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300"
                          : "border-slate-200 text-slate-400 dark:border-slate-700"
                        : "border-slate-200 hover:border-brand-400 hover:bg-brand-50/50 dark:border-slate-700 dark:hover:border-brand-600"}`}>
                    {o.text}
                  </button>
                );
              })}
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); feedback ? next() : submit(input); }}>
              <input
                ref={inputRef}
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Javobingizni yozing..."
                disabled={!!feedback || busy}
                className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 text-center text-lg outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
              <Button type="submit" className="mt-3 w-full" loading={busy} disabled={!input.trim()}>
                Tekshirish
              </Button>
            </form>
          )}

          {feedback && (
            <div className={`mt-4 rounded-xl px-4 py-3 text-sm ${
              feedback.correct ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                : "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300"}`}>
              {feedback.correct ? "✓ To'g'ri!" : `✗ To'g'ri javob: ${feedback.expected}`}
              <div className="mt-0.5 text-xs opacity-80">
                {feedback.term} — {feedback.translation_uz}
              </div>
              <Button size="sm" className="mt-3 w-full" onClick={next}
                disabled={busy}>
                {index + 1 < session.items.length ? "Keyingisi →" : "Yakunlash"}
              </Button>
            </div>
          )}
        </Card>

        <p className="mt-3 text-center text-xs text-slate-400">
          Xato so'zlar seans oxirida qayta beriladi. Birinchi urinish hisobga olinadi.
        </p>
      </div>
    </main>
  );
}

function typeLabel(t: string): string {
  return {
    choice_en_uz: "Inglizcha → O'zbekcha",
    choice_uz_en: "O'zbekcha → Inglizcha",
    written_en_uz: "Yozib ko'rsat (uz)",
    written_uz_en: "Yozib ko'rsat (en)",
    spelling: "Imlo",
    listening: "Tinglash",
    sentence_blank: "Gapni to'ldirish",
  }[t] || t;
}
