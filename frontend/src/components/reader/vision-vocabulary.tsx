"use client";

import { useEffect, useRef, useState } from "react";
import { ApiErr, get, post } from "@/lib/api";
import { Button } from "@/components/ui";

type BatchPage = {
  page: number;
  status: "ok" | "not_a_word_list" | "skipped" | "deferred" | "error";
  unit?: string;
  words_found?: number;
  words_added?: number;
  entries?: string[];
  message?: string;
};
type BatchOut = {
  processed: number;
  words_added: number;
  remaining_pages: number;
  stopped: boolean;
  results: BatchPage[];
};
type Pending = { pages: number[]; batch_size: number; batches: number };

// One click scans at most this many pages: every page is a paid provider call, and a
// 200-page scan started by a single tap would be a surprise bill, not a repair.
const PAGES_PER_RUN = 40;

/**
 * Reads word lists off page images, one bounded batch at a time.
 *
 * The rule-based detector cannot describe a word-list layout it has not seen, and a
 * scanned book has no text layer at all. This path sends the page image to the configured
 * vision model and stores what the book actually prints. It never translates, never
 * replaces an existing word and marks every new word for review.
 *
 * Pages are read in batches because a serverless request cannot run a whole-book scan;
 * the server decides the batch size and reports how much is left after each call.
 */
export function VisionVocabulary({ bookId, onDone }: { bookId: string; onDone?: () => void }) {
  const [consent, setConsent] = useState(false);
  // Off by default: a scanned book needs only its scanned pages. A book WITH a text layer
  // that still produced no words is the other case — re-analysis re-reads the same layout
  // and changes nothing, so vision has to look at every page instead.
  const [allPages, setAllPages] = useState(false);
  const [plan, setPlan] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState<number | null>(null);
  const [read, setRead] = useState(0);
  const [results, setResults] = useState<BatchPage[]>([]);
  const [remaining, setRemaining] = useState(0);
  const [error, setError] = useState("");
  const stopRef = useRef(false);

  useEffect(() => {
    let alive = true;
    get<Pending>(`/books/${bookId}/vision-vocabulary/pending?include_text_pages=${allPages}`)
      .then((r) => { if (alive) { setPlan(r); setRemaining(r.pages.length); } })
      .catch(() => { if (alive) setPlan(null); });
    return () => { alive = false; };
  }, [bookId, allPages]);

  // Two independent things gate the run, and they are not the same permission:
  //   * image consent — the page image leaves the server for the model;
  //   * a worklist — there is something left to read.
  // The old code required consent even when the checkbox had been ticked in another
  // component, and enabled the button before the page list had loaded, so a click did
  // nothing. Both are computed here, from state, once.
  const canRun = consent && remaining > 0 && !busy;

  async function run() {
    if (!canRun) return;
    setBusy(true); setError(""); setResults([]); setRead(0); stopRef.current = false;
    let readSoFar = 0;
    try {
      while (!stopRef.current && readSoFar < PAGES_PER_RUN) {
        // Empty page list = "read the next pending pages"; the server owns the batch size
        // and the consent flag is sent on EVERY request that touches a page image.
        const out = await post<BatchOut>(`/books/${bookId}/vision-vocabulary/batch`, {
          consent_images_to_provider: consent,
          include_text_pages: allPages,
          pages: [],
        });
        // Only pages that were actually read count towards this run's page budget; a
        // deferred page is untouched work for the next call.
        const readNow = out.results.filter((r) => r.status !== "deferred").length;
        readSoFar += readNow;
        setRead(readSoFar);
        setRemaining(out.remaining_pages);
        setResults((prev) => [...prev, ...out.results]);
        const last = out.results[out.results.length - 1];
        setCurrent(last ? last.page : null);
        if (out.stopped) {
          const failed = out.results.find((r) => r.status === "error");
          setError(failed?.message ?? "Skanerlash to'xtatildi.");
          break;
        }
        if (!readNow || !out.remaining_pages) break;   // nothing left to read
      }
    } catch (e) {
      const err = e instanceof ApiErr ? e : null;
      setError(err?.message ?? (e instanceof Error ? e.message : "Skanerlash boshlanmadi."));
    } finally {
      setBusy(false); setCurrent(null); onDone?.();
    }
  }

  const added = results.reduce((n, r) => n + (r.words_added ?? 0), 0);
  const failed = results.filter((r) => r.status === "error");
  const deferred = results.filter((r) => r.status === "deferred");
  const skipped = results.filter((r) => r.status === "not_a_word_list");

  function line(r: BatchPage) {
    if (r.status === "error") return r.message ?? "Sahifa o'qilmadi";
    if (r.status === "not_a_word_list") return "lug'at sahifasi emas";
    if (r.status === "skipped") return r.message ?? "o'tkazib yuborildi";
    // The request ran out of time; the page is untouched and the next call picks it up.
    if (r.status === "deferred") return "keyingi so'rovda o'qiladi";
    const unit = r.unit ? `${r.unit}-unit · ` : "";
    return `${unit}${r.words_added ?? 0} ta yangi so'z`;
  }

  return (
    <div className="mt-3 space-y-2">
      {plan && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {remaining
            ? `${remaining} sahifa o'qilishi kerak. Har bir sahifa AI chaqiruvi hisoblanadi; `
              + `bir bosishda ko'pi bilan ${PAGES_PER_RUN} sahifa o'qiladi.`
            : results.length
              ? "Barcha kerakli sahifa o'qildi."
              : "O'qilishi kerak bo'lgan sahifa yo'q — lug'at allaqachon to'plangan."}
        </p>
      )}
      <label className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
        <input type="checkbox" checked={allPages} disabled={busy} onChange={(e) => setAllPages(e.target.checked)} />
        <span>
          Matnli sahifalarni ham tekshirish — kitobda matn bor, lekin lug'at baribir
          topilmagan bo'lsa (qayta tahlil ham o'zgarish bermasa) shu variantni tanlang.
        </span>
      </label>
      <label className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
        <input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
        <span>
          Sahifa rasmlari sozlangan tashqi AI xizmatiga yuborilishiga roziman. So'zlar tarjimasiz
          saqlanadi va «tekshirilishi kerak» deb belgilanadi; mavjud so'zlar va progressingiz o'zgarmaydi.
        </span>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" loading={busy} disabled={!canRun} onClick={run}>
          {busy
            ? `O'qilmoqda: ${current ?? "..."} (${read}/${Math.min(PAGES_PER_RUN, remaining + read)})`
            : !remaining
              ? "Hamma sahifa o'qildi"
              : !consent
                ? "Avval rozilikni belgilang"
                : `Lug'atni o'qish (${Math.min(PAGES_PER_RUN, remaining)} sahifa)`}
        </Button>
        {busy && <Button variant="ghost" onClick={() => { stopRef.current = true; }}>To'xtatish</Button>}
      </div>
      {!consent && remaining > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Tugma ishlashi uchun rozilik katakchasini belgilang — sahifa rasmi AI xizmatiga yuboriladi.
        </p>
      )}
      {error && <p role="alert" className="text-red-700 dark:text-red-300">{error}</p>}
      {!!results.length && (
        <div className="rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-800" role="status">
          <p className="font-medium">
            Jami {added} ta so'z qo'shildi · {results.length} sahifa o'qildi
            {skipped.length ? ` · ${skipped.length} sahifa lug'at emas` : ""}
            {deferred.length ? ` · ${deferred.length} sahifa keyingi so'rovga qoldi` : ""}
            {failed.length ? ` · ${failed.length} ta xato` : ""}
          </p>
          <ul className="mt-2 max-h-40 space-y-1 overflow-auto">
            {results.map((r) => (
              <li key={r.page} className={r.status === "error" ? "text-red-700 dark:text-red-300" : ""}>
                {r.page}-sahifa: {line(r)}
                {r.status === "ok" && r.entries?.length ? ` — ${r.entries.slice(0, 3).join(", ")}` : ""}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-amber-700 dark:text-amber-300">
            AI xato qilishi mumkin. So'zlarni asl sahifa bilan solishtirib tekshiring.
            {remaining > 0 && ` Yana ${remaining} sahifa qoldi — tugmani qayta bosing.`}
          </p>
        </div>
      )}
    </div>
  );
}
