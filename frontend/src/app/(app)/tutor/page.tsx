"use client";
/** AI personal tutor chat: context-aware (book/lesson/exercise), conversation management, voice input, interactive extra exercises. */
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { del, get, post } from "@/lib/api";
import { listenOnce, sttAvailable } from "@/lib/tts";
import type { Conversation, ExtraExercise, Message } from "@/lib/types";
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
  const [aiStatus, setAiStatus] = useState<{ configured: boolean; ai_configured?: boolean; provider: string } | null>(null);
  const [extras, setExtras] = useState<ExtraExercise[]>([]);
  const [extraAnswers, setExtraAnswers] = useState<Record<string, string>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const stopListeningRef = useRef<() => void>(() => {});

  const loadConversations = useCallback(async () => {
    try {
      const convs = await get<Conversation[]>("/tutor/conversations");
      setConversations(convs);
      return convs;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    (async () => {
      const st = await get<typeof aiStatus>("/tutor/status");
      setAiStatus(st);
      const convs = await loadConversations();
      const bookId = search.get("book");
      const lessonId = search.get("lesson");

      if (convs.length > 0 && !bookId && !lessonId) {
        setActiveId(convs[0].id);
      } else {
        const conv = await post<Conversation>("/tutor/conversations", {
          book_id: bookId || null,
          lesson_id: lessonId || null,
          title: "Yangi suhbat",
        });
        setConversations((c) => [conv, ...c]);
        setActiveId(conv.id);
      }
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

  const newChat = async () => {
    try {
      const conv = await post<Conversation>("/tutor/conversations", {
        title: "Yangi suhbat",
      });
      setConversations((c) => [conv, ...c]);
      setActiveId(conv.id);
      setMessages([]);
      setExtras([]);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    }
  };

  const deleteChat = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await del(`/tutor/conversations/${id}`);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        const remaining = conversations.filter((c) => c.id !== id);
        if (remaining.length > 0) {
          setActiveId(remaining[0].id);
        } else {
          newChat();
        }
      }
      toast("Suhbat o'chirildi", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "O'chirishda xatolik", "error");
    }
  };

  const send = useCallback(async (textToSend?: string) => {
    const content = (textToSend || input).trim();
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
      loadConversations();
    } catch (e) {
      toast(e instanceof Error ? e.message : "AI javob bermadi", "error");
      setMessages((m) => m.filter((x) => !x.id.startsWith("tmp-")));
    } finally {
      setSending(false);
    }
  }, [input, activeId, sending, toast, loadConversations]);

  const toggleVoice = () => {
    if (!sttAvailable()) {
      toast("Brauzeringiz ovozli kiritishni (Web Speech API) qo'llab-quvvatlamaydi", "error");
      return;
    }
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
    setTimeout(() => setListening(false), 10000);
  };

  const isConfigured = Boolean(aiStatus?.configured ?? aiStatus?.ai_configured);

  const quickPrompts = [
    "Bu darsdagi grammatika qoidasini o'zbek tilida tushuntir",
    "Menga qo'shimcha mashqlar tuz",
    "Present Perfect va Past Simple farqi nima?",
    "Xatolarimni tahlil qilib, nimaga e'tibor berishim kerak?",
  ];

  return (
    <>
      <TopBar title="AI Murabbiy" />
      <main className="mx-auto flex h-[calc(100vh-64px)] max-w-6xl flex-col px-4 py-4 lg:px-8">
        {!isConfigured && (
          <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            ⚠️ AI xizmati serverda sozlanmagan. Murabbiy javob berishi uchun administrator AI
            provayder kalitini kiritishi kerak (AI_PROVIDER, AI_API_KEY, AI_MODEL). Suhbatlar
            saqlanadi, ammo real AI javobi olinmaydi.
          </div>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-4">
          {/* Conversation history sidebar */}
          <div className="hidden flex-col rounded-2xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900 md:flex">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Suhbatlar</span>
              <Button size="sm" variant="ghost" onClick={newChat}>+ Yangi</Button>
            </div>
            <div className="thin-scroll flex-1 space-y-1 overflow-y-auto">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  onClick={() => setActiveId(c.id)}
                  className={`group flex cursor-pointer items-center justify-between rounded-xl px-3 py-2 text-xs font-medium transition ${
                    activeId === c.id
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-950/50 dark:text-brand-300"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}>
                  <span className="truncate pr-1">{c.title || "Yangi suhbat"}</span>
                  <button
                    onClick={(e) => deleteChat(c.id, e)}
                    className="opacity-0 hover:text-red-500 group-hover:opacity-100"
                    title="O'chirish">
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Main chat window */}
          <div className="flex min-h-0 flex-col rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 md:col-span-3">
            {/* messages */}
            <div className="thin-scroll flex-1 space-y-4 overflow-y-auto p-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center gap-3 py-10 text-center">
                  <div className="text-4xl">🤖</div>
                  <p className="font-semibold text-slate-700 dark:text-slate-200">
                    Salom! Men sizning shaxsiy murabbiyingizman.
                  </p>
                  <p className="max-w-md text-sm text-slate-500">
                    Kitobingiz, darslaringiz yoki yo'l qo'ygan xatolaringiz bo'yicha savol bering.
                  </p>
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    {quickPrompts.map((p) => (
                      <button
                        key={p}
                        onClick={() => send(p)}
                        className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600 hover:border-brand-300 hover:text-brand-600 dark:border-slate-800 dark:bg-slate-800 dark:text-slate-300">
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((m) => {
                const isUser = m.role === "user";
                return (
                  <div key={m.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                        isUser
                          ? "bg-brand-600 text-white"
                          : "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
                      }`}>
                      <p className="whitespace-pre-wrap">{m.content}</p>
                    </div>
                  </div>
                );
              })}

              {/* Extra exercises generated by AI */}
              {extras.map((ex, exIdx) => (
                <div key={`ex-${exIdx}`} className="rounded-xl border border-brand-200 bg-brand-50/50 p-4 dark:border-brand-900/50 dark:bg-brand-950/20">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-bold text-brand-600 dark:text-brand-400">
                      📝 Qo'shimcha mashq: {ex.topic}
                    </span>
                    <Badge tone="brand">{ex.exercise_type}</Badge>
                  </div>
                  <p className="text-xs text-slate-500">{ex.instructions}</p>
                  <div className="mt-3 space-y-3">
                    {ex.questions.map((q, qi) => {
                      const qKey = `${exIdx}-${qi}`;
                      const isRevealed = revealed[qKey];
                      return (
                        <div key={qKey} className="rounded-lg bg-white p-3 text-xs dark:bg-slate-800">
                          <p className="font-medium text-slate-700 dark:text-slate-200">
                            {q.number || qi + 1}. {q.prompt}
                          </p>
                          <div className="mt-2 flex items-center gap-2">
                            <input
                              value={extraAnswers[qKey] || ""}
                              onChange={(e) => setExtraAnswers((p) => ({ ...p, [qKey]: e.target.value }))}
                              placeholder="Javobingiz..."
                              className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
                            />
                            <Button size="sm" variant="ghost" onClick={() => setRevealed((p) => ({ ...p, [qKey]: !p[qKey] }))}>
                              {isRevealed ? "Yashirish" : "Tekshirish"}
                            </Button>
                          </div>
                          {isRevealed && (
                            <p className="mt-2 text-emerald-600 dark:text-emerald-400">
                              To'g'ri javob: <b>{q.correct_answers?.join(", ") || "Topilmadi"}</b>
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}

              {sending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl bg-slate-100 p-3 dark:bg-slate-800">
                    <Spinner className="h-4 w-4 text-brand-500" />
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            {/* input bar */}
            <div className="border-t border-slate-200 p-3 dark:border-slate-800">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send();
                }}
                className="flex items-center gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Murabbiyga savol bering..."
                  className="flex-1 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={toggleVoice}
                  className={listening ? "!bg-red-500 !text-white animate-pulse" : ""}>
                  {listening ? "Tinglamoqda..." : "🎤 Ovoz"}
                </Button>
                <Button type="submit" loading={sending} disabled={!input.trim()}>
                  Yuborish
                </Button>
              </form>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

export default function TutorPage() {
  return (
    <Suspense fallback={<main className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></main>}>
      <TutorInner />
    </Suspense>
  );
}
