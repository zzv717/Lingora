"use client";

import { useEffect, useState } from "react";
import { getAccessToken } from "@/lib/api";
import { withTimeout } from "@/lib/timeout";
import type { PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";

export type PictureRegion = { page: number; bbox: [number, number, number, number] };
type Question = { evidence_pages: number[]; picture?: PictureRegion | null };

/** A model-suggested crop is untrusted. Reject invalid and out-of-scope regions. */
export function validPicture(q: Question, pages: number[]): PictureRegion | null {
  const r = q.picture;
  if (!r || !Number.isSafeInteger(r.page) || !pages.includes(r.page) || !q.evidence_pages.includes(r.page) ||
      !Array.isArray(r.bbox) || r.bbox.length !== 4 || !r.bbox.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  const [x0, y0, x1, y1] = r.bbox;
  return x0 >= 0 && y0 >= 0 && x1 <= 1000 && y1 <= 1000 && x0 < x1 && y0 < y1 ? r : null;
}

/** Crops are rendered locally from the authenticated original PDF, never from generated images. */
export function usePdfPictureCrops(bookId: string, questions: Question[], pages: number[], enabled = true) {
  const [pictures, setPictures] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  // Keys track content, not object identity, avoiding PDF reloads on answer edits.
  const regionsKey = JSON.stringify(questions.map((q) => validPicture(q, pages)));
  useEffect(() => {
    const regions = JSON.parse(regionsKey) as (PictureRegion | null)[];
    setPictures({}); setError("");
    if (!enabled || !regions.some(Boolean)) return;
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    let renderTask: RenderTask | undefined;
    (async () => {
      try {
        const pdfjs = await withTimeout(import("pdfjs-dist"), 60_000, "PDF dasturi yuklanmadi.");
        if (cancelled) return;
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        task = pdfjs.getDocument({ url: `/backend/api/v1/books/${bookId}/file`,
          httpHeaders: { authorization: `Bearer ${getAccessToken()}` } });
        const pdf = await withTimeout(task.promise, 120_000, "PDF yuklanmadi.");
        const output: Record<number, string> = {};
        for (const pageNumber of Array.from(new Set(regions.flatMap((r) => r ? [r.page] : [])))) {
          if (cancelled) return;
          if (pageNumber > pdf.numPages) throw new Error("Rasm sahifasi PDFda topilmadi.");
          const page = await withTimeout(pdf.getPage(pageNumber), 60_000, "PDF sahifasi yuklanmadi.");
          const base = page.getViewport({ scale: 1 });
          const scale = Math.min(2, 1800 / Math.max(base.width, base.height));
          const viewport = page.getViewport({ scale });
          const source = document.createElement("canvas");
          source.width = Math.ceil(viewport.width); source.height = Math.ceil(viewport.height);
          const context = source.getContext("2d");
          if (!context) throw new Error("PDF rasmini ko'rsatib bo'lmadi.");
          renderTask = page.render({ canvasContext: context, viewport });
          await withTimeout(renderTask.promise, 60_000, "PDF sahifasini chizib bo'lmadi.");
          renderTask = undefined;
          if (cancelled) return;
          regions.forEach((region, i) => {
            if (!region || region.page !== pageNumber) return;
            const [x0, y0, x1, y1] = region.bbox;
            const sx = source.width * x0 / 1000, sy = source.height * y0 / 1000;
            const sw = source.width * (x1 - x0) / 1000, sh = source.height * (y1 - y0) / 1000;
            const factor = Math.min(1, 600 / Math.max(sw, sh));
            const crop = document.createElement("canvas");
            crop.width = Math.max(1, Math.ceil(sw * factor)); crop.height = Math.max(1, Math.ceil(sh * factor));
            const ctx = crop.getContext("2d");
            if (!ctx) throw new Error("PDF rasmini qirqib bo'lmadi.");
            ctx.drawImage(source, sx, sy, sw, sh, 0, 0, crop.width, crop.height);
            output[i] = crop.toDataURL("image/png");
          });
          source.width = 0; source.height = 0;
        }
        if (!cancelled) setPictures(output);
      } catch {
        renderTask?.cancel();
        if (!cancelled) setError("Rasmlarni ajratib ko'rsatib bo'lmadi. Asl PDF sahifasidan foydalaning.");
      } finally {
        if (task) void task.destroy().catch(() => {});
      }
    })();
    return () => { cancelled = true; renderTask?.cancel(); if (task) void task.destroy().catch(() => {}); };
  }, [bookId, regionsKey, enabled]);
  return { pictures, error };
}
