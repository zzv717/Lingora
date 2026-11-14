"use client";

import { useRef, useState } from "react";
import { ApiErr, get, post } from "@/lib/api";
import { Button } from "@/components/ui";

type PageResult = { page: number; status: "ok" | "skipped" | "error"; added: number; message: string };
type Saved = { exercises_added: number; exercises_found: number; warnings: string[] };

// Errors where retrying the next page cannot succeed: stop the whole run.
const STOP_CODES = new Set([
  "AI_NOT_CONFIGURED", "AI_VISION_NOT_CONFIGURED", "AI_FEATURE_QUOTA_EXCEEDED", "AI_QUOTA_EXCEEDED",
  "AI_TOKEN_QUOTA_EXCEEDED", "AI_PROVIDER_REJECTED", "UNAUTHORIZED", "TOKEN_EXPIRED",
]);
// Page-level problems: record and continue with the next page.
const SKIP_CODES = new Set(["EXERCISES_ALREADY_EXIST", "VISION_PAGE_ALREADY_DONE"]);

export function VisionExercises({ bookId, pageCount, onUpdate }: { bookId: string; pageCount: number; onUpdate?: () => void }) {
  const [consent, setConsent] = useState(false);
  const [includeText, setIncludeText] = useState(false);
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState(String(pageCount));
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [results, setResults] = useState<PageResult[]>([]);
  const [error, setError] = useState("");
  const stopRef = useRef(false);

  async function run() {
    if (!consent || busy) return;
    const a = Number(from), b = Number(to);
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 1 || b > pageCount || a > b) {
      setError(`Sahifa oralig'ini to'g'ri kiriting (1–${pageCount}).`);
      return;
    }
    setBusy(true); setError(""); setResults([]); stopRef.current = false;
    try {
      const { pages } = await get<{ pages: number[] }>(
        `/books/${bookId}/vision-exercises/pending?include_text_pages=${includeText}`);
      const todo = pages.filter((p) => p >= a && p <= b);
      setTotal(todo.length);
      if (!todo.length) { setError("Bu oraliqda tahlil qilinadigan sahifa qolmagan."); return; }
      for (const page of todo) {
        if (stopRef.current) break;
        setCurrent(page);
        try {
          const r = await post<Saved>(`/books/${bookId}/vision-exercises/pages/${page}`,
            { consent_images_to_provider: true, replace: false });
          setResults((prev) => [...prev, { page, status: "ok", added: r.exercises_added,
            message: r.exercises_added ? `${r.exercises_added} ta mashq` : "mashq topilmadi" }]);
        } catch (e) {
          const err = e instanceof ApiErr ? e : null;
          const message = err?.message ?? (e instanceof Error ? e.message : "Noma'lum xato");
          const status = err && SKIP_CODES.has(err.code) ? "skipped" : "error";
          setResults((prev) => [...prev, { page, status, added: 0, message }]);
          if (err && STOP_CODES.has(err.code)) { setError(message); break; }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tahlil boshlanmadi.");
    } finally {
      setBusy(false); setCurrent(null); onUpdate?.();
    }
  }

  const added = results.reduce((n, r) => n + r.added, 0);
  const failed = results.filter((r) => r.status === "error");

  return <section className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm dark:border-emerald-900 dark:bg-emerald-950/30">
    <h3 className="font-semibold">Vision AI: skaner sahifalaridan mashqlarni topish</h3>
    <p className="mt-1 text-slate-600 dark:text-slate-300">
      Har bir sahifa rasmi AI ga yuboriladi; u raqamli doirachalar va ko'rsatmalarni ko'rib mashqlarni ajratadi.
      Natijalar «tekshirilishi kerak» deb belgilanadi, javob kalitlari yaratilmaydi, mavjud mashqlar o'zgarmaydi.
    </p>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <label>Sahifadan <input className="mx-1 w-16 rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" value={from} disabled={busy} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>gacha <input className="mx-1 w-16 rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" value={to} disabled={busy} onChange={(e) => setTo(e.target.value)} /></label>
    </div>
    <label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={includeText} disabled={busy} onChange={(e) => setIncludeText(e.target.checked)} />
      <span>Matnli (skaner bo'lmagan) sahifalarni ham tekshirish, agar ularda mashq topilmagan bo'lsa</span></label>
    <label className="mt-2 flex items-start gap-2 text-xs"><input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
      <span>Sahifa rasmlari sozlangan tashqi AI xizmatiga yuborilishiga roziman. Provayder ma'lumotni qayta ishlashi va haq olishi mumkin; yuborishga huquqim bo'lmagan kitoblarni tanlamayman.</span></label>
    <div className="mt-3 flex gap-2">
      <Button variant="secondary" size="sm" disabled={!consent || busy || !pageCount} onClick={run}>
        {busy ? `Tahlil qilinmoqda: ${current ?? "..."} (${results.length}/${total})` : "Tahlilni boshlash"}</Button>
      {busy && <Button variant="ghost" size="sm" onClick={() => { stopRef.current = true; }}>To'xtatish</Button>}
    </div>
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    {!!results.length && <div className="mt-3 rounded-lg bg-white p-3 dark:bg-slate-900" role="status">
      <p className="font-medium">Jami {added} ta mashq qo'shildi · {results.length} sahifa ko'rib chiqildi{failed.length ? ` · ${failed.length} ta xato` : ""}</p>
      <ul className="mt-2 max-h-48 space-y-1 overflow-auto text-xs">
        {results.map((r) => <li key={r.page} className={r.status === "error" ? "text-red-700 dark:text-red-300" : ""}>
          {r.page}-sahifa: {r.message}</li>)}
      </ul>
      <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">AI xato qilishi mumkin. Mashqlarni asl sahifa bilan solishtirib tekshiring.</p>
    </div>}
  </section>;
}
