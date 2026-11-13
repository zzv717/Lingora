"use client";
/** Read-only inspection; OCR output is never promoted to a verified answer key. */
import { useEffect, useState } from "react";
import { get } from "@/lib/api";
import { withTimeout } from "@/lib/timeout";
import { Button, Card } from "@/components/ui";

type Word = { text: string; confidence?: number | null };
type Line = { text: string; confidence?: number | null; words?: Word[] };
type Page = { text: string; blocks: Line[]; needs_ocr: boolean; ocr_used: boolean };

export function OcrReview({ bookId, pageNumber }: { bookId: string; pageNumber: number }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPage(null); setError("");
    withTimeout(get<Page>(`/books/${bookId}/pages/${pageNumber}`), 45_000, "OCR ma'lumotlarini olish uzoq davom etdi.")
      .then((result) => { if (!cancelled) setPage(result); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "OCR yuklanmadi"); });
    return () => { cancelled = true; };
  }, [bookId, pageNumber, open, retry]);
  return <Card>
    <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="text-sm font-medium text-brand-600">
      {open ? "OCR tekshiruvini yopish" : "Sahifa matnini tekshirish"}
    </button>
    {open && <div className="mt-3 text-sm">
      {error ? <><p role="alert" className="text-red-600">{error}</p><Button size="sm" onClick={() => setRetry((n) => n + 1)}>Qayta urinish</Button></>
        : !page ? <p role="status">Yuklanmoqda…</p>
        : page.needs_ocr ? <p>Bu sahifa hali OCR qilinmagan.</p>
        : <>
          <p className="mb-2 text-amber-700 dark:text-amber-300">{page.ocr_used ? "OCR matni xato bo'lishi mumkin. Asl PDF bilan solishtiring; bu oynada tahrirlash yoki tasdiqlash hali mavjud emas." : "PDF matn qatlami. Asl sahifa bilan solishtiring."}</p>
          {page.blocks?.length ? <ul className="max-h-64 space-y-2 overflow-auto whitespace-pre-wrap">{page.blocks.map((line, i) => <li key={i}>
            {line.text} {line.confidence != null && <span className="text-xs text-slate-500">({Math.round(line.confidence)}% OCR)</span>}
            {!!line.words?.length && <details className="text-xs text-slate-500"><summary>So'zlar ishonchliligi</summary>{line.words.map((word, j) => <span key={j} className="mr-2">{word.text}{word.confidence != null ? ` (${Math.round(word.confidence)}%)` : ""}</span>)}</details>}
          </li>)}</ul> : <p className="max-h-64 overflow-auto whitespace-pre-wrap">{page.text || "Matn topilmadi."}</p>}
        </>}
    </div>}
  </Card>;
}
