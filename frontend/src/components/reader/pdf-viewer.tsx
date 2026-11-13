"use client";
/** PDF page rendering uses a separate canvas per render to avoid overlapping pdf.js tasks. */
import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "@/lib/api";
import { Button, Spinner } from "@/components/ui";
import { fitScale, overlayRect, type PageGeometry } from "@/lib/reader-utils";
import { withTimeout } from "@/lib/timeout";
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";

export interface BlankOverlay {
  id: string;
  bbox: [number, number, number, number];
  value: string;
  onChange: (v: string) => void;
  state?: "neutral" | "correct" | "wrong";
}


export function PdfViewer({ bookId, pageNumber, onPageCount, onGoTo, overlays = [] }: {
  bookId: string; pageNumber: number; onPageCount?: (n: number) => void;
  onGoTo?: (n: number) => void; overlays?: BlankOverlay[];
}) {
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [rotation, setRotation] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [pageInput, setPageInput] = useState(String(pageNumber));
  useEffect(() => setPageInput(String(pageNumber)), [pageNumber]);
  const goToInput = () => {
    const n = Number(pageInput);
    if (Number.isInteger(n) && n >= 1 && n <= numPages) onGoTo?.(n);
    else setPageInput(String(pageNumber));
  };
  const [geometry, setGeometry] = useState<PageGeometry | null>(null);
  const [rendering, setRendering] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    setError(""); setRendering(true); setPdfDoc(null); setGeometry(null);
    (async () => {
      try {
        const pdfjs = await withTimeout(import("pdfjs-dist"), 60_000, "PDF dasturi yuklanmadi. Internetni tekshirib qayta urinib ko'ring.");
        if (cancelled) return;
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        task = pdfjs.getDocument({ url: `/backend/api/v1/books/${bookId}/file`,
          httpHeaders: { authorization: `Bearer ${getAccessToken()}` } });
        const doc = await withTimeout(task.promise, 120_000, "PDF yuklanishi 2 daqiqadan oshdi. Internet yoki faylga kirishni tekshirib qayta urinib ko'ring.");
        if (cancelled) return;
        setPdfDoc(doc); setNumPages(doc.numPages); onPageCount?.(doc.numPages);
      } catch (e) {
        if (task) void task.destroy().catch(() => {});
        if (!cancelled) { setError(e instanceof Error ? e.message : "PDF yuklanmadi"); setRendering(false); }
      }
    })();
    return () => { cancelled = true; if (task) void task.destroy().catch(() => {}); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId, reloadKey]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const update = () => setSize((old) => {
      const next = { width: element.clientWidth, height: element.clientHeight };
      return old.width === next.width && old.height === next.height ? old : next;
    });
    update();
    const ro = new ResizeObserver(update); ro.observe(element);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!pdfDoc || (size.width && size.height)) return;
    const timer = setTimeout(() => {
      setError("PDF ko'rish maydoni tayyor bo'lmadi. Qayta urinib ko'ring.");
      setRendering(false);
    }, 15_000);
    return () => clearTimeout(timer);
  }, [pdfDoc, size.width, size.height]);

  useEffect(() => {
    if (!pdfDoc || !size.width || !size.height) return;
    let cancelled = false;
    let task: RenderTask | null = null;
    setRendering(true); setError(""); setGeometry(null);
    (async () => {
      try {
        const page = await withTimeout(pdfDoc.getPage(Math.min(Math.max(pageNumber, 1), pdfDoc.numPages)),
          60_000, "PDF sahifasini olish uzoq davom etdi. Qayta urinib ko'ring.");
        if (cancelled) return;
        const angle = ((page.rotate + rotation) % 360 + 360) % 360;
        const base = page.getViewport({ scale: 1, rotation: angle });
        const unrotated = page.getViewport({ scale: 1, rotation: 0 });
        const scale = fitScale(size.width, size.height, base.width, base.height, zoom);
        const viewport = page.getViewport({ scale, rotation: angle });
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const buffer = document.createElement("canvas");
        buffer.width = Math.ceil(viewport.width * dpr); buffer.height = Math.ceil(viewport.height * dpr);
        const ctx = buffer.getContext("2d");
        if (!ctx) throw new Error("PDF sahifasini ko'rsatib bo'lmadi");
        task = page.render({ canvasContext: ctx, viewport, transform: [dpr, 0, 0, dpr, 0, 0] });
        await withTimeout(task.promise, 60_000, "PDF sahifasini chizish uzoq davom etdi. Qayta urinib ko'ring.");
        if (cancelled || !canvasRef.current) return;
        const canvas = canvasRef.current;
        canvas.width = buffer.width; canvas.height = buffer.height;
        canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
        const visible = canvas.getContext("2d");
        if (!visible) throw new Error("PDF sahifasini ko'rsatib bo'lmadi");
        visible.drawImage(buffer, 0, 0);
        setGeometry({ scale, width: unrotated.width, height: unrotated.height, rotation: angle });
        setRendering(false);
      } catch (e) {
        task?.cancel();
        if (!cancelled) { setError(e instanceof Error ? e.message : "PDF sahifasi yuklanmadi"); setRendering(false); }
      }
    })();
    return () => { cancelled = true; task?.cancel(); };
  }, [pdfDoc, pageNumber, size.width, size.height, rotation, zoom]);

  return (
    <div className="flex h-full min-h-[350px] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-t-2xl border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
        <button onClick={() => onGoTo?.(pageNumber - 1)} disabled={pageNumber <= 1} className="rounded-lg px-2 py-1 text-sm disabled:opacity-30">← Oldingi</button>
        <div className="flex items-center gap-2 text-sm">
          <input aria-label="Sahifa raqami" type="number" value={pageInput} min={1} max={numPages || 1} onChange={(e) => setPageInput(e.target.value)} onBlur={goToInput} onKeyDown={(e) => { if (e.key === "Enter") { goToInput(); e.currentTarget.blur(); } }} className="w-16 rounded-lg border border-slate-300 bg-white px-2 py-1 text-center dark:border-slate-700 dark:bg-slate-800" />
          <span>/ {numPages || "…"}</span>
        </div>
        <div className="flex items-center gap-1 text-sm">
          <button aria-label="Kichraytirish" title="Kichraytirish" onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))} className="rounded-lg px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">−</button>
          <button title="Sahifani ekranga sig'dirish" onClick={() => setZoom(1)} className="rounded-lg px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">{Math.round(zoom * 100)}%</button>
          <button aria-label="Kattalashtirish" title="Kattalashtirish" onClick={() => setZoom((z) => Math.min(3, Math.round((z + 0.25) * 100) / 100))} className="rounded-lg px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">+</button>
          <button aria-label="Sahifani aylantirish" title="Sahifani 90° aylantirish" onClick={() => setRotation((r) => (r + 90) % 360)} className="rounded-lg px-2 py-1 hover:bg-slate-100 dark:hover:bg-slate-800">↻</button>
        </div>
        <button onClick={() => onGoTo?.(pageNumber + 1)} disabled={numPages > 0 && pageNumber >= numPages} className="rounded-lg px-2 py-1 text-sm disabled:opacity-30">Keyingi →</button>
      </div>
      <div ref={containerRef} className="thin-scroll relative min-h-0 flex-1 overflow-auto rounded-b-2xl bg-slate-200 p-2 dark:bg-slate-800">
        {error && <div role="alert" className="m-6 flex flex-col items-center gap-3 rounded-xl bg-red-50 p-6 text-center text-sm text-red-600 dark:bg-red-950/40 dark:text-red-300"><p>{error}</p><Button size="sm" variant="secondary" onClick={() => setReloadKey((k) => k + 1)}>Qayta urinish</Button></div>}
        {rendering && !error && <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-200/50 dark:bg-slate-800/50"><Spinner className="h-8 w-8 text-brand-500" /></div>}
        <div className="relative mx-auto w-fit shadow-lg">
          <canvas ref={canvasRef} className="block rounded-md bg-white" />
          {geometry && overlays.map((o) => <input key={o.id} aria-label="Mashq javobi" value={o.value} onChange={(e) => o.onChange(e.target.value)} placeholder="…" autoComplete="off" className={`blank-input ${o.state === "correct" ? "!border-emerald-500 !bg-emerald-50 dark:!bg-emerald-900/60" : o.state === "wrong" ? "!border-red-500 !bg-red-50 dark:!bg-red-900/60" : ""}`} style={overlayRect(o.bbox, geometry)} />)}
        </div>
      </div>
    </div>
  );
}
