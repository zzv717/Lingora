"use client";

import { useEffect, useRef, useState } from "react";
import { ApiErr, get, post } from "@/lib/api";
import { Button } from "@/components/ui";

type PageResult = { page: number; status: "ok" | "skipped" | "error"; added: number; message: string };
type Saved = { words_added: number; words_found: number; heading?: string; warnings: string[] };

// Errors where scanning the next page cannot succeed either: stop the whole run.
const STOP_CODES = new Set([
  "AI_NOT_CONFIGURED", "AI_VISION_NOT_CONFIGURED", "AI_FEATURE_QUOTA_EXCEEDED", "AI_QUOTA_EXCEEDED",
  "AI_TOKEN_QUOTA_EXCEEDED", "AI_PROVIDER_REJECTED", "UNAUTHORIZED", "TOKEN_EXPIRED",
]);
// Page-level problems: the page is not a word list or has no readable words. Keep going.
const SKIP_CODES = new Set(["NOT_A_WORD_LIST", "NO_WORDS_FOUND"]);

/**
 * Reads word lists off SCANNED pages, one page image at a time.
 *
 * A photocopied book has no text layer, so the rule-based detector finds no vocabulary and
 * the Lug'at screen stays empty however often the book is re-analysed. This is the path that
 * actually produces words for such a book; it never translates, never replaces a word and
 * marks everything as reviewable.
 */
export function VisionVocabulary({ bookId, onDone }: { bookId: string; onDone?: () => void }) {
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState<number[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const [results, setResults] = useState<PageResult[]>([]);
  const [error, setError] = useState("");
  const stopRef = useRef(false);

  useEffect(() => {
    let alive = true;
    get<{ pages: number[] }>(`/books/${bookId}/vision-vocabulary/pending`)
      .then((r) => { if (alive) setPending(r.pages); })
      .catch(() => { if (alive) setPending(null); });
    return () => { alive = false; };
  }, [bookId]);

  async function run() {
    if (!consent || busy) return;
    setBusy(true); setError(""); setResults([]); stopRef.current = false;
    try {
      const { pages } = await get<{ pages: number[] }>(`/books/${bookId}/vision-vocabulary/pending`);
      setPending(pages);
      if (!pages.length) {
        setError("Skanerlangan sahifa qolmagan — lug'atni boshqa yo'l bilan to'ldirish kerak.");
        return;
      }
      for (const page of pages) {
        if (stopRef.current) break;
        setCurrent(page);
        try {
          const r = await post<Saved>(`/books/${bookId}/vision-vocabulary/pages/${page}`,
            { consent_images_to_provider: true });
          setResults((prev) => [...prev, {
            page, status: "ok", added: r.words_added,
            message: r.words_added ? `${r.words_added} ta yangi so'z` : "yangi so'z qo'shilmadi",
          }]);
        } catch (e) {
          const err = e instanceof ApiErr ? e : null;
          const message = err?.message ?? (e instanceof Error ? e.message : "Noma'lum xato");
          const status = err && SKIP_CODES.has(err.code) ? "skipped" : "error";
          setResults((prev) => [...prev, { page, status, added: 0, message }]);
          if (err && STOP_CODES.has(err.code)) { setError(message); break; }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Skanerlash boshlanmadi.");
    } finally {
      setBusy(false); setCurrent(null); onDone?.();
    }
  }

  const added = results.reduce((n, r) => n + r.added, 0);
  const failed = results.filter((r) => r.status === "error");

  return (
    <div className="mt-3 space-y-2">
      {pending && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {pending.length
            ? `${pending.length} sahifa skanerlangan (matn qatlamisiz). Vision AI ularni birma-bir o'qib, lug'at ro'yxatlarini ajratadi.`
            : "Skanerlangan sahifa yo'q — kitob matnli, lug'at tahlildan kelishi kerak."}
        </p>
      )}
      <label className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
        <input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
        <span>
          Sahifa rasmlari sozlangan tashqi AI xizmatiga yuborilishiga roziman. So'zlar tarjimasiz
          saqlanadi va «tekshirilishi kerak» deb belgilanadi; mavjud so'zlar va progressingiz o'zgarmaydi.
        </span>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" loading={busy} disabled={!consent || !pending?.length} onClick={run}>
          {busy ? `O'qilmoqda: ${current ?? "..."} (${results.length}/${pending?.length ?? 0})` : "Lug'atni Vision bilan o'qish"}
        </Button>
        {busy && <Button variant="ghost" onClick={() => { stopRef.current = true; }}>To'xtatish</Button>}
      </div>
      {error && <p role="alert" className="text-red-700 dark:text-red-300">{error}</p>}
      {!!results.length && (
        <div className="rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-800" role="status">
          <p className="font-medium">
            Jami {added} ta so'z qo'shildi · {results.length} sahifa o'qildi
            {failed.length ? ` · ${failed.length} ta xato` : ""}
          </p>
          <ul className="mt-2 max-h-40 space-y-1 overflow-auto">
            {results.map((r) => (
              <li key={r.page} className={r.status === "error" ? "text-red-700 dark:text-red-300" : ""}>
                {r.page}-sahifa: {r.message}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-amber-700 dark:text-amber-300">
            AI xato qilishi mumkin. So'zlarni asl sahifa bilan solishtirib tekshiring.
          </p>
        </div>
      )}
    </div>
  );
}
