"use client";
/**
 * PDF viewer with pdf.js: renders the ORIGINAL page on canvas and positions
 * interactive blank inputs (answer overlays) at their extracted PDF coordinates.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type * as Pdfjs from "pdfjs-dist";
import { getAccessToken } from "@/lib/api";
import { Spinner } from "@/components/ui";

export interface BlankOverlay {
  id: string;
  bbox: [number, number, number, number]; // x0,y0,x1,y1 in PDF points
  value: string;
  onChange: (v: string) => void;
  state?: "neutral" | "correct" | "wrong";
}

export function PdfViewer({
  bookId,
  pageNumber,
  onPageCount,
  onGoTo,
  overlays = [],
  pageWidth,
}: {
  bookId: string;
  pageNumber: number;
  onPageCount?: (n: number) => void;
  onGoTo?: (n: number) => void;
  overlays?: BlankOverlay[];
  pageWidth?: number;
}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pdfRef = useRef<any>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [rendering, setRendering] = useState(true);
  const [error, setError] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pageInfo, setPageInfo] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        const task = pdfjs.getDocument({
          url: `/backend/api/v1/books/${bookId}/file`,
          httpHeaders: { authorization: `Bearer ${getAccessToken()}` },
        });
        const pdf = await task.promise;
        if (cancelled) {
          pdf.destroy();
          return;
        }
        pdfRef.current = pdf;
        onPageCount?.(pdf.numPages);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "PDF yuklanmadi");
      }
    })();
    return () => {
      cancelled = true;
      pdfRef.current?.destroy?.();
      pdfRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  const render = useCallback(async () => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!pdf || !canvas || !container) return;
    setRendering(true);
    try {
      const page = await pdf.getPage(Math.min(Math.max(pageNumber, 1), pdf.numPages));
      setPageInfo(page);
      const containerWidth = container.clientWidth - 4;
      const base = pageWidth || page.getViewport({ scale: 1 }).width;
      const scale = Math.max(0.4, containerWidth / base);
      const viewport = page.getViewport({ scale });
      const dpr = window.devicePixelRatio || 1;
      canvas.width = viewport.width * dpr;
      canvas.height = viewport.height * dpr;
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      await page.render({ canvasContext: ctx, viewport }).promise;
    } catch (e) {
      // cancelled renders are fine
    } finally {
      setRendering(false);
    }
  }, [pageNumber, pageWidth]);

  useEffect(() => {
    if (pdfRef.current) render();
  }, [pdfRef.current, pageNumber, render]);

  useEffect(() => {
    const onResize = () => pdfRef.current && render();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [render]);

  const scale = pageInfo && canvasRef.current
    ? parseFloat(canvasRef.current.style.width) / (pageInfo.getViewport({ scale: 1 }).width)
    : 0;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex items-center justify-between gap-2 rounded-t-2xl border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
        <button
          onClick={() => onGoTo?.(pageNumber - 1)}
          disabled={pageNumber <= 1}
          className="rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800">
          ← Oldingi
        </button>
        <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="number"
            value={pageNumber}
            min={1}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (n >= 1) onGoTo?.(n);
            }}
            className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-center dark:border-slate-700 dark:bg-slate-800"
          />
          <span>/ {pdfRef.current?.numPages ?? "…"}</span>
        </div>
        <button
          onClick={() => onGoTo?.(pageNumber + 1)}
          disabled={!!pdfRef.current && pageNumber >= pdfRef.current.numPages}
          className="rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800">
          Keyingi →
        </button>
      </div>

      {/* page */}
      <div ref={containerRef} className="thin-scroll relative flex-1 overflow-auto rounded-b-2xl bg-slate-200 p-2 dark:bg-slate-800">
        {error && (
          <div className="m-6 rounded-xl bg-red-50 p-4 text-sm text-red-600 dark:bg-red-950/40 dark:text-red-300">
            {error}
          </div>
        )}
        {rendering && !error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center">
            <Spinner className="h-8 w-8 text-brand-500" />
          </div>
        )}
        <div className="relative mx-auto shadow-lg" style={{ width: "fit-content" }}>
          <canvas ref={canvasRef} className="rounded-md bg-white" />
          {/* interactive overlays positioned at PDF coordinates */}
          {overlays.map((o) => {
            if (!o.bbox || scale === 0) return null;
            const [x0, y0, x1, y1] = o.bbox;
            const pad = 2;
            return (
              <input
                key={o.id}
                value={o.value}
                onChange={(e) => o.onChange(e.target.value)}
                placeholder="…"
                autoComplete="off"
                className={`blank-input ${o.state === "correct" ? "!border-emerald-500 !bg-emerald-50 dark:!bg-emerald-900/60" : o.state === "wrong" ? "!border-red-500 !bg-red-50 dark:!bg-red-900/60" : ""}`}
                style={{
                  left: x0 * scale - pad,
                  top: y0 * scale - pad,
                  width: Math.max(48, (x1 - x0) * scale + pad * 2 + 20),
                  height: Math.max(26, (y1 - y0) * scale + pad * 2),
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
