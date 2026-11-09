"use client";
/**
 * PDF viewer with pdf.js: renders the ORIGINAL page on canvas and positions
 * interactive blank inputs (answer overlays) at their extracted PDF coordinates.
 * Includes robust page loading state, cancellation, and ResizeObserver.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getAccessToken } from "@/lib/api";
import { Button, Spinner } from "@/components/ui";

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
  // pdf.js document instance
  const [pdfDoc, setPdfDoc] = useState<unknown>(null);
  const [numPages, setNumPages] = useState<number>(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [rendering, setRendering] = useState(true);
  const [error, setError] = useState("");
  const [pageInfo, setPageInfo] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Load PDF Document via state
  useEffect(() => {
    let cancelled = false;
    setError("");
    setRendering(true);
    setPdfDoc(null);

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        const task = pdfjs.getDocument({
          url: `/backend/api/v1/books/${bookId}/file`,
          httpHeaders: { authorization: `Bearer ${getAccessToken()}` },
        });
        const doc = await task.promise;
        if (cancelled) {
          doc.destroy();
          return;
        }
        setPdfDoc(doc);
        setNumPages(doc.numPages);
        onPageCount?.(doc.numPages);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "PDF yuklanmadi");
          setRendering(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId, reloadKey]);

  // Render current page onto canvas with cancellation
  const render = useCallback(async () => {
    if (!pdfDoc || !canvasRef.current || !containerRef.current) return;
    setRendering(true);
    let renderTask: { promise: Promise<void> } | null = null;

    try {
      const clampedPage = Math.min(Math.max(pageNumber, 1), (pdfDoc as { numPages: number }).numPages);
      const page = await (pdfDoc as { getPage: (n: number) => Promise<any> }).getPage(clampedPage);
      setPageInfo(page);

      const container = containerRef.current;
      const canvas = canvasRef.current;
      if (!container || !canvas) return;

      const containerWidth = container.clientWidth - 16;
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

      renderTask = page.render({ canvasContext: ctx, viewport });
      if (renderTask) {
        await renderTask.promise;
      }
    } catch (e: unknown) {
      // Ignored if cancelled
      if (e && typeof e === "object" && "name" in e && (e as { name: string }).name === "RenderingCancelledException") {
        return;
      }
    } finally {
      setRendering(false);
    }
  }, [pdfDoc, pageNumber, pageWidth]);

  useEffect(() => {
    if (pdfDoc) {
      render();
    }
  }, [pdfDoc, pageNumber, render]);

  // ResizeObserver for reliable dimension scaling
  useEffect(() => {
    if (!containerRef.current) return;
    let t: ReturnType<typeof setTimeout>;
    const ro = new ResizeObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (pdfDoc) render();
      }, 100);
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [pdfDoc, render]);

  const scale = pageInfo && canvasRef.current
    ? parseFloat(canvasRef.current.style.width) / ((pageInfo as { getViewport: (opt: { scale: number }) => { width: number } }).getViewport({ scale: 1 }).width)
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
            max={numPages || 1}
            onChange={(e) => {
              const n = parseInt(e.target.value);
              if (n >= 1 && n <= (numPages || 1)) onGoTo?.(n);
            }}
            className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-center dark:border-slate-700 dark:bg-slate-800"
          />
          <span>/ {numPages || "…"}</span>
        </div>
        <button
          onClick={() => onGoTo?.(pageNumber + 1)}
          disabled={numPages > 0 && pageNumber >= numPages}
          className="rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-30 dark:text-slate-300 dark:hover:bg-slate-800">
          Keyingi →
        </button>
      </div>

      {/* page canvas container */}
      <div ref={containerRef} className="thin-scroll relative flex-1 overflow-auto rounded-b-2xl bg-slate-200 p-2 dark:bg-slate-800">
        {error && (
          <div className="m-6 flex flex-col items-center justify-center gap-3 rounded-xl bg-red-50 p-6 text-center text-sm text-red-600 dark:bg-red-950/40 dark:text-red-300">
            <p>{error}</p>
            <Button size="sm" variant="secondary" onClick={() => setReloadKey((k) => k + 1)}>
              Qayta urinish
            </Button>
          </div>
        )}
        {rendering && !error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-200/50 dark:bg-slate-800/50">
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
