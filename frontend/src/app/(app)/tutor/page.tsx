"use client";
/** AI personal tutor chat: context-aware (book/lesson/exercise), voice input, extra exercises. */
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { get, post } from "@/lib/api";
import { listenOnce, sttAvailable } from "@/lib/tts";
import type { Conversation, ExtraExercise, Message, Structure } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, Spinner, useToast } from "@/components/ui";

function TutorInner() {
  const search = useSearchParams();
  const { toast } = useToast();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [aiStatus, setAiStatus] = useState<{ configured: boolean } | null>(null);
  const [extras, setExtras] = useState<ExtraExercise[]>([]);
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const stopListeningRef = useRef<() => void>(() => {});

  useEffect(() => {
    (async () => {
      const st = await get<typeof aiStatus>("/tutor/status");
      setAiStatus(st);
      const convs = await get<Conversation[]>("/tutor/conversations");
      setConversations(convs);
      const bookId = search.get("book");
      const lessonId = search.get("lesson");
      const conv = await post<Conversation>("/tutor/conversations", {
        book_id: bookId || null,
        lesson_id: lessonId || null,
        title: "Yangi suhbat",
      });
      setConversations((c) => [conv, ...c]);
      setActiveId(conv.id);
    })().catch((e) => toast(e instanceof Error ? e.message : "Xatolik", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeId) return;
    get<Message[]>(`/tutor/conversations/${activeId}/messages`)
      .then(setMessages)
      .catch(() => setMessages([]));
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const send = useCallback(async () => {
    const content = input.trim();
    if (!content || !activeId || sending) return;
    setInput("");
    setSending(true);
    setMessages((m) => [
      ...m,
      { id: `tmp-${Date.now()}`, role: "user", content, model: "", created_at: new Date().toISOString() },
    ]);
    try {
      const res = await post<{ message: Message; extra_exercises: ExtraExercise[] }>(
        `/tutor/conversations/${activeId}/messages`, { content });
      setMessages((m) => [...m.filter((x) => !x.id.startsWith("tmp-")), res.message]);
      if (res.extra_exercises?.length) setExtras(res.extra_exercises);
      // refresh conversation titles
      get<Conversation[]>("/tutor/conversations").then(setConversations).catch(() => {});
    } catch (e) {
      toast(e instanceof Error ? e.message : "AI javob bermadi", "error");
      setMessages((m) => m.filter((x) => !x.id.startsWith("tmp-")));
    } finally {
      setSending(false);
    }
  }, [input, activeId, sending, toast]);

  const toggleVoice = () => {
    if (listening) {
      stopListeningRef.current();
      setListening(false);
      return;
    }
    setListening(true);
    stopListeningRef.current = listenOnce((text) => {
      setInput((prev) => (prev ? `${prev} ${text}` : text));
      setListening(false);
    });
    setTimeout(() => setListening(false), 8000);
  };

  const quickPrompts = [
    "Bu darsdagi grammatika qoidasini o'zbek tilida tushuntir",
    "Menga qo'shimcha mashqlar tuz",
    "Present Perfect va Past Simple farqi nima?",
    "Xatolarimni tahlil qilib, nimaga e'tibor berishim kerak?",
  ];

  return (
    <>
      <TopBar title="AI Murabbiy" />
      <main className="mx-auto flex h-[calc(100vh-64px)] max-w-4xl flex-col px-4 py-4 lg:px-8">
        {aiStatus && !aiStatus.configured && (
          <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            ⚠️ AI xizmati serverda sozlanmagan. Murabbiy javob berishi uchun administrator AI
            provayder kalitini kiritishi kerak (AI_PROVIDER, AI_API_KEY, AI_MODEL). Suhbatlar
            saqlanadi, lekin javob hozir kelmaydi.
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          {/* messages */}
          <div className="thin-scroll flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <div className="text-4xl">🤖</div>
                <p className="font-semibold text-slate-700 dark:text-slate-200">
                  Salom! Men sizning murabbiyingizman.
                </p>
                <p className="max-w-md text-sm text-slate-500 dark:text-slate-400">
                  Kitobingiz, darsingiz va xatolaringizni bilaman. Grammatikani so'rang, mashq
                  tuzib berishni so'rang yoki savolingizni yozing.
                </p>
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm ${
                  m.role === "user"
                    ? "rounded-br-md bg-brand-600 text-white"
                    : "rounded-bl-md bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"}`}>
                  {m.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-md bg-slate-100 px-4 py-3 dark:bg-slate-800">
                  <Spinner className="h-4 w-4 text-brand-500" />
                </div>
              </div>
            )}

            {/* AI-generated extra exercises */}
            {extras.length > 0 && (
              <div className="space-y-3">
                {extras.map((ex, i) => (
                  <Card key={i}>
                    <div className="mb-2 flex items-center gap-2">
                      <Badge tone="brand">AI mashq</Badge>
                      {ex.topic && <span className="text-xs text-slate-400">{ex.topic}</span>}
                    </div>
                    <p className="mb-3 text-sm text-slate-600 dark:text-slate-300">{ex.instructions}</p>
                    <div className="space-y-2.5">
                      {ex.questions.map((q) => (
                        <div key={q.number}>
                          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                            {q.number}. {q.prompt}
                          </p>
                          {q.options.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              {q.options.map((o) => (
                                <span key={o.letter} className="rounded-lg bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">
                                  {o.letter}) {o.text}
                                </span>
                              ))}
                            </div>
                          )}
                          <input
                            className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-800"
                            placeholder="Javobingiz..." />
                          {revealed[q.number] ? (
                            <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">
                              Javob: {q.correct_answers.join(", ")}
                            </p>
                          ) : (
                            <button
                              onClick={() => setRevealed((r) => ({ ...r, [q.number]: true }))}
                              className="mt-1 text-xs text-brand-500 hover:underline">
                              Javobni ko'rsatish
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* quick prompts */}
          {messages.length === 0 && (
            <div className="flex flex-wrap gap-2 border-t border-slate-200 px-4 pt-3 dark:border-slate-800">
              {quickPrompts.map((p) => (
                <button key={p}
                  onClick={() => { setInput(p); }}
                  className="rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-600 transition hover:border-brand-400 hover:text-brand-600 dark:border-slate-700 dark:text-slate-300">
                  {p}
                </button>
              ))}
            </div>
          )}

          {/* composer */}
          <div className="flex items-end gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
            {sttAvailable() && (
              <button onClick={toggleVoice}
                className={`rounded-xl p-2.5 transition ${listening ? "bg-red-100 text-red-600 animate-pulse dark:bg-red-900/40" : "text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"}`}
                aria-label="Ovozli kiritish" title="Ovozli kiritish">
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-14 0m7 7v4m-4 0h8M12 3a3 3 0 00-3 3v5a3 3 0 006 0V6a3 3 0 00-3-3z" />
                </svg>
              </button>
            )}
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={1}
              placeholder="Savolingizni yozing... (Enter — yuborish)"
              className="max-h-32 flex-1 resize-none rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-800"
            />
            <Button onClick={send} loading={sending} disabled={!input.trim()}>Yuborish</Button>
          </div>
        </div>
      </main>
    </>
  );
}

export default function TutorPage() {
  return (
    <Suspense fallback={<div className="flex min-h-[70vh] items-center justify-center"><Spinner className="h-8 w-8 text-brand-500" /></div>}>
      <TutorInner />
    </Suspense>
  );
}
