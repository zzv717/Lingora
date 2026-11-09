"use client";
/**
 * Revision runner: student practices weak topics and due vocabulary generated
 * by smart revision. Server grades answers deterministically.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { get, post } from "@/lib/api";
import { TopBar } from "@/components/nav";
import { Button, Card, ErrorBox, Progress, Spinner } from "@/components/ui";

interface RevisionItemData {
  item_id: string;
  item_type: "vocab" | "question";
  payload: {
    prompt: string;
    expected?: string;
    type?: string;
    topic?: string;
    options?: { letter: string; text: string }[];
  };
}

interface RevisionSessionData {
  session_id: string;
  focus: string;
  reason: string;
  status: string;
  score: number;
  items: RevisionItemData[];
}

export default function RevisionSessionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [session, setSession] = useState<RevisionSessionData | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [doneScore, setDoneScore] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    get<RevisionSessionData>(`/revision/sessions/${id}`)
      .then(setSession)
      .catch((e) => setError(e instanceof Error ? e.message : "Yuklanmadi"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Spinner className="h-8 w-8 text-brand-500" />
      </main>
    );
  }

  if (error || !session) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-4 px-4">
        <ErrorBox message={error || "Seans topilmadi"} />
        <Link href="/progress"><Button variant="secondary">Natijalarga qaytish</Button></Link>
      </main>
    );
  }

  if (doneScore !== null) {
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Card className="w-full max-w-md text-center">
          <div className="mb-3 text-6xl">🎯</div>
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-100">
            Takrorlash yakunlandi!
          </h1>
          <p className="mt-2 text-4xl font-extrabold text-brand-600">{doneScore}%</p>
          <p className="mt-2 text-sm text-slate-500">{session.focus}</p>
          <div className="mt-6 flex flex-col gap-2">
            <Button onClick={() => router.push("/progress")}>Natijalarga qaytish</Button>
            <Button variant="secondary" onClick={() => router.push("/dashboard")}>Boshqaruv paneli</Button>
          </div>
        </Card>
      </main>
    );
  }

  const currentItem = session.items[index];
  const total = session.items.length;
  const currentVal = answers[currentItem.item_id] || "";

  const submitAll = async () => {
    setSubmitting(true);
    try {
      const payload = {
        answers: session.items.map((it) => ({
          item_id: it.item_id,
          answer: answers[it.item_id] || "",
        })),
      };
      const res = await post<{ ok: boolean; score: number }>(`/revision/sessions/${id}/complete`, payload);
      setDoneScore(res.score);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Yakunlashda xatolik");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <TopBar title="Aqlli takrorlash" />
      <main className="mx-auto flex min-h-[calc(100vh-64px)] max-w-xl flex-col px-4 py-8">
        <div className="mb-4 flex items-center justify-between text-sm text-slate-500">
          <Link href="/progress" className="hover:text-brand-500">← Chiqish</Link>
          <span>{index + 1} / {total}</span>
        </div>
        <Progress value={((index + 1) / total) * 100} />

        <Card className="mt-6 flex-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400">
            {currentItem.item_type === "vocab" ? "Lug'at takrorlash" : `Mavzu: ${currentItem.payload.topic || "Grammatika"}`}
          </span>
          <p className="mt-4 text-center text-xl font-bold text-slate-800 dark:text-slate-100">
            {currentItem.payload.prompt}
          </p>

          {currentItem.payload.options && currentItem.payload.options.length > 0 ? (
            <div className="mt-6 grid gap-2">
              {currentItem.payload.options.map((opt) => {
                const selected = currentVal === opt.letter;
                return (
                  <button
                    key={opt.letter}
                    onClick={() => setAnswers((prev) => ({ ...prev, [currentItem.item_id]: opt.letter }))}
                    className={`rounded-xl border p-3.5 text-left text-sm font-medium transition ${
                      selected
                        ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300"
                        : "border-slate-200 hover:border-slate-300 dark:border-slate-800"
                    }`}>
                    <b>{opt.letter})</b> {opt.text}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="mt-6">
              <input
                autoFocus
                value={currentVal}
                onChange={(e) => setAnswers((prev) => ({ ...prev, [currentItem.item_id]: e.target.value }))}
                placeholder="Javobingizni yozing..."
                className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 text-center text-lg outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </div>
          )}

          <div className="mt-8 flex justify-between gap-3">
            <Button
              variant="secondary"
              disabled={index <= 0}
              onClick={() => setIndex((i) => i - 1)}>
              ← Oldingi
            </Button>
            {index + 1 < total ? (
              <Button onClick={() => setIndex((i) => i + 1)}>
                Keyingi →
              </Button>
            ) : (
              <Button onClick={submitAll} loading={submitting} disabled={submitting}>
                Yakunlash va tekshirish
              </Button>
            )}
          </div>
        </Card>
      </main>
    </>
  );
}
