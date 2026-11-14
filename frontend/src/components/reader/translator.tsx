"use client";

import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { Button } from "@/components/ui";

export type TranslationSeed = { text: string; id: number };

/** The text box is intentionally explicit: neither PDF images nor student answers are sent automatically. */
export function Translator({ seed }: { seed?: TranslationSeed }) {
  const [open, setOpen] = useState(false);
  const [direction, setDirection] = useState<"en-uz" | "uz-en">("en-uz");
  const [text, setText] = useState("");
  const [consent, setConsent] = useState(false);
  const [translation, setTranslation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!seed) return;
    requestVersion.current++;
    setOpen(true); setText(seed.text.slice(0, 1000)); setDirection("en-uz"); setTranslation(""); setError("");
    const timer = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [seed]);

  async function translate() {
    if (!text.trim() || !consent || busy) return;
    setBusy(true); setError(""); setTranslation("");
    const version = ++requestVersion.current;
    try {
      const result = await post<{ translation: string }>("/tutor/translate", { text, direction, consent_text_to_provider: true });
      if (version === requestVersion.current) setTranslation(result.translation);
    } catch (e) { if (version === requestVersion.current) setError(e instanceof Error ? e.message : "Tarjima amalga oshmadi."); }
    finally { setBusy(false); }
  }
  function swap() { setDirection((v) => v === "en-uz" ? "uz-en" : "en-uz"); setTranslation(""); setError(""); }

  return <section className="rounded-2xl border border-indigo-100 bg-indigo-50/70 dark:border-indigo-900 dark:bg-indigo-950/30">
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 rounded-2xl p-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 sm:p-4">
      <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-indigo-600 text-sm font-bold text-white">A<span className="sr-only"> </span>文</span>
      <span className="min-w-0 flex-1"><span className="block text-sm font-bold text-indigo-950 dark:text-indigo-100">Mini tarjimon</span><span className="block text-xs text-indigo-700 dark:text-indigo-300">So'z yoki jumlani tarjima qiling</span></span>
      <span aria-hidden="true" className="text-indigo-500">{open ? "−" : "+"}</span>
    </button>
    {open && <div className="space-y-3 border-t border-indigo-100 p-3 dark:border-indigo-900 sm:p-4">
      <div className="flex items-center gap-2 text-xs font-semibold text-indigo-900 dark:text-indigo-100">
        <span>{direction === "en-uz" ? "English" : "O'zbekcha"}</span>
        <button type="button" aria-label="Tarjima yo'nalishini almashtirish" disabled={busy} onClick={swap} className="rounded-lg border border-indigo-200 bg-white px-2 py-1 text-base hover:bg-indigo-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 dark:border-indigo-800 dark:bg-slate-900">⇄</button>
        <span>{direction === "en-uz" ? "O'zbekcha" : "English"}</span>
      </div>
      <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">Tarjima uchun matn
        <textarea ref={inputRef} value={text} disabled={busy} maxLength={1000} rows={2} onChange={(e) => { setText(e.target.value); setTranslation(""); setError(""); }} placeholder="So'z yoki jumla yozing…" className="mt-1 block w-full resize-y rounded-xl border border-indigo-200 bg-white p-3 text-sm font-normal text-slate-900 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 dark:border-indigo-900 dark:bg-slate-900 dark:text-slate-100" />
      </label>
      {seed && seed.text.length > 1000 && <p className="text-xs text-amber-700 dark:text-amber-300">Matnning faqat birinchi 1000 belgisi olindi.</p>}
      <div className="text-right text-[11px] text-slate-500">{text.length}/1000</div>
      <label className="flex items-start gap-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300"><input className="mt-0.5" type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
        <span>Faqat yuqoridagi matn tashqi AI xizmatiga yuborilishiga roziman. Provayder undan foydalanishi yoki haq olishi mumkin.</span></label>
      <Button type="button" size="sm" disabled={!consent || busy || !text.trim()} onClick={translate}>{busy ? "Tarjima qilinmoqda…" : "Tarjima qilish"}</Button>
      {error && <p role="alert" className="text-xs text-red-700 dark:text-red-300">{error}</p>}
      {translation && <div role="status" className="rounded-xl border border-emerald-200 bg-white p-3 dark:border-emerald-900 dark:bg-slate-900"><p className="text-[11px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">AI tarjimasi · tekshirib ko'ring</p><p className="mt-1 whitespace-pre-wrap text-sm text-slate-800 dark:text-slate-100">{translation}</p></div>}
    </div>}
  </section>;
}
