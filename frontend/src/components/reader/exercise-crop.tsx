"use client";
/**
 * Exercise crop shown above the questions, with the "Tuzatish" (correct) button.
 *
 * The crop is rendered LOCALLY from the authenticated original PDF in the browser: the
 * page never leaves the device for this feature. The box is normalized, so the same
 * stored value produces an identical crop on any screen and at any zoom.
 */
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui";
import {
  cropFromCanvas, loadPdf, renderPageToCanvas, validBox, type NormalizedBox,
} from "./exercise-crops";
import { ExerciseCropEditor } from "./exercise-crop-editor";
import type { PDFDocumentProxy } from "pdfjs-dist";

export type CropCorrection = { regionId: string; bbox: NormalizedBox };

export function ExerciseCrop({ bookId, page, bbox, regionId, detection, confidence = 0,
  needsReview = false, showDebug = false, onCorrect,
}: {
  bookId: string; page: number; bbox: NormalizedBox | null; regionId?: string | null;
  detection?: string; confidence?: number; needsReview?: boolean; showDebug?: boolean;
  onCorrect?: (correction: CropCorrection) => void;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState("");
  const [zoomOpen, setZoomOpen] = useState(false);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSrc(""); setError("");
    if (!validBox(bbox)) return;
    (async () => {
      try {
        const pdf = pdfRef.current && (pdfRef.current as PDFDocumentProxy & { fingerprint?: string })
          ? pdfRef.current : await loadPdf(bookId);
        pdfRef.current = pdf;
        const canvas = await renderPageToCanvas(pdf, page);
        if (cancelled) return;
        setSrc(cropFromCanvas(canvas, bbox as NormalizedBox));
        canvas.width = 0; canvas.height = 0;
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Qirqimni tayyorlab bo'lmadi.");
      }
    })();
    return () => { cancelled = true; };
  }, [bookId, page, bbox]);

  useEffect(() => () => {
    const pdf = pdfRef.current as (PDFDocumentProxy & { destroy?: () => Promise<void> }) | null;
    if (pdf?.destroy) void pdf.destroy().catch(() => {});
    pdfRef.current = null;
  }, []);

  if (!validBox(bbox)) return null;

  return (
    <figure className="mt-3 w-fit max-w-full rounded-2xl border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800/60">
      <div className="flex flex-wrap items-center gap-2 pb-1.5">
        <figcaption className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Asl sahifadan qirqim · PDF {page}
        </figcaption>
        {detection === "vision" && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
            AI · tekshirilmagan{confidence ? ` (${Math.round(confidence * 100)}%)` : ""}
          </span>
        )}
        {needsReview && (
          <span className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-950/40 dark:text-red-300">
            tekshirish kerak
          </span>
        )}
        {onCorrect && regionId && (
          <Button type="button" size="sm" variant="secondary" className="!px-2 !py-1 !text-[11px]"
            onClick={() => setEditing(true)}>✏️ Tuzatish</Button>
        )}
        {src && (
          <Button type="button" size="sm" variant="ghost" className="!px-2 !py-1 !text-[11px]"
            onClick={() => setZoomOpen((v) => !v)}>{zoomOpen ? "Kichraytirish" : "Kattalashtirish"}</Button>
        )}
      </div>
      {error && <p role="alert" className="max-w-xs text-xs text-red-600 dark:text-red-300">{error}</p>}
      {!src && !error && <p className="max-w-xs text-xs text-slate-500" role="status">Qirqim tayyorlanmoqda…</p>}
      {src && (
        <img src={src} alt={`Mashqning asl PDF ${page}-sahifadan qirqilgan ko'rinishi`}
          className={`rounded-lg bg-white object-contain ${zoomOpen ? "max-h-[70vh] max-w-full" : "max-h-56 max-w-md"}`} />
      )}
      <p className="max-w-md pt-1.5 text-[11px] text-slate-500 dark:text-slate-400">
        Qirqim noto&apos;g&apos;ri bo&apos;lsa, «Tuzatish» bilan chegarani sudrab o&apos;zgartiring.
      </p>
      {editing && (
        <ExerciseCropEditor
          bookId={bookId}
          page={page}
          initial={bbox as NormalizedBox}
          regionId={regionId || null}
          onCancel={() => setEditing(false)}
          onSaved={(correction) => {
            setSaved("Chegara saqlandi. Endi u AI natijasidan ustun.");
            setEditing(false);
            onCorrect?.(correction);
          }}
        />
      )}
      {saved && <p role="status" className="max-w-md pt-1 text-xs text-emerald-700 dark:text-emerald-300">{saved}</p>}
      {showDebug && (
        <a href={`/backend/api/v1/books/${bookId}/exercise-regions/${regionId || ""}/debug.png`}
          target="_blank" rel="noreferrer" className="text-[11px] text-indigo-700 underline dark:text-indigo-300">
          Debug rasmni ochish
        </a>
      )}
    </figure>
  );
}
