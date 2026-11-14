"use client";

import { useEffect, useRef, useState } from "react";
import { getAccessToken } from "@/lib/api";
import { withTimeout } from "@/lib/timeout";
import type { PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";
import type { PictureRegion } from "./pdf-picture-crops";

type Point = { x: number; y: number };
export function selectionBox(a: Point, b: Point): [number, number, number, number] | null {
  const x0 = Math.max(0, Math.min(1000, Math.min(a.x, b.x)));
  const y0 = Math.max(0, Math.min(1000, Math.min(a.y, b.y)));
  const x1 = Math.max(0, Math.min(1000, Math.max(a.x, b.x)));
  const y1 = Math.max(0, Math.min(1000, Math.max(a.y, b.y)));
  return x1 - x0 >= 5 && y1 - y0 >= 5 ? [x0, y0, x1, y1].map(Math.round) as [number, number, number, number] : null;
}

/** Optional local, user-controlled correction; PDF pages never leave the browser for this. */
export function PictureSelector({ bookId, pages, initialPage, onSave, onCancel }: {
  bookId: string; pages: number[]; initialPage: number; onSave: (region: PictureRegion) => void; onCancel: () => void;
}) {
  const [pageNumber, setPageNumber] = useState(pages.includes(initialPage) ? initialPage : pages[0]);
  const [start, setStart] = useState<Point | null>(null);
  const [end, setEnd] = useState<Point | null>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drag = useRef<Point | null>(null);
  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    let renderTask: RenderTask | undefined;
    setReady(false); setError(""); setStart(null); setEnd(null);
    (async () => {
      try {
        const pdfjs = await withTimeout(import("pdfjs-dist"), 60_000, "PDF dasturi yuklanmadi.");
        if (cancelled) return;
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
        task = pdfjs.getDocument({ url: `/backend/api/v1/books/${bookId}/file`, httpHeaders: { authorization: `Bearer ${getAccessToken()}` } });
        const pdf = await withTimeout(task.promise, 120_000, "PDF yuklanmadi.");
        if (cancelled) return;
        const page = await withTimeout(pdf.getPage(pageNumber), 60_000, "Sahifa yuklanmadi.");
        if (cancelled || !canvas.current) return;
        const base = page.getViewport({ scale: 1 });
        const viewport = page.getViewport({ scale: Math.min(2, 1800 / Math.max(base.width, base.height)) });
        const target = canvas.current;
        target.width = Math.ceil(viewport.width); target.height = Math.ceil(viewport.height);
        const context = target.getContext("2d");
        if (!context) throw new Error("Sahifani ko'rsatib bo'lmadi.");
        renderTask = page.render({ canvasContext: context, viewport });
        await withTimeout(renderTask.promise, 60_000, "Sahifani chizib bo'lmadi.");
        renderTask = undefined;
        if (!cancelled) setReady(true);
      } catch {
        renderTask?.cancel();
        if (!cancelled) setError("PDF sahifasi yuklanmadi. Qayta urinib ko'ring.");
      } finally { if (task) void task.destroy().catch(() => {}); }
    })();
    return () => { cancelled = true; renderTask?.cancel(); if (task) void task.destroy().catch(() => {}); };
  }, [bookId, pageNumber]);
  const box = start && end ? selectionBox(start, end) : null;
  const point = (event: React.PointerEvent<HTMLDivElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1000, (event.clientX - rect.left) / rect.width * 1000)), y: Math.max(0, Math.min(1000, (event.clientY - rect.top) / rect.height * 1000)) };
  };
  return <div className="mt-3 rounded-2xl bg-slate-100 p-3 dark:bg-slate-800">
    <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-300">Rasmni belgilang: ustidan torting yoki ikki qarama-qarshi burchagini bosing. PDF tashqi AI xizmatiga yuborilmaydi.</p>
    <label className="mt-2 block text-xs">PDF sahifa <select value={pageNumber} onChange={(e) => setPageNumber(Number(e.target.value))} className="ml-2 rounded bg-white p-1 text-slate-900">{pages.map((n) => <option key={n} value={n}>{n}</option>)}</select></label>
    {!ready && !error && <p className="mt-2 text-xs" role="status">Sahifa yuklanmoqda…</p>}
    {error && <p className="mt-2 text-xs text-red-600" role="alert">{error}</p>}
    <div className="mt-2 max-h-[65vh] overflow-auto rounded-lg bg-slate-300 p-2 dark:bg-slate-700">
      <div className="relative mx-auto w-full max-w-2xl touch-none select-none" onPointerDown={(e) => {
        if (!ready) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = point(e);
      }} onPointerUp={(e) => {
        if (!ready || !drag.current) return;
        const from = drag.current, to = point(e); drag.current = null;
        if (selectionBox(from, to)) { setStart(from); setEnd(to); }
        else if (!start || end) { setStart(to); setEnd(null); }
        else setEnd(to);
      }} onPointerCancel={() => { drag.current = null; }}>
        <canvas ref={canvas} className="block h-auto w-full" aria-label="Rasm tanlash uchun PDF sahifasi" />
        {box && <div aria-hidden="true" className="pointer-events-none absolute border-2 border-indigo-600 bg-indigo-500/15" style={{ left: `${box[0] / 10}%`, top: `${box[1] / 10}%`, width: `${(box[2] - box[0]) / 10}%`, height: `${(box[3] - box[1]) / 10}%` }} />}
      </div>
    </div>
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">Klaviatura bilan: chap, yuqori, o'ng va pastki chegaralarni 0–1000 oralig'ida kiriting.</p>
    <div className="mt-1 flex flex-wrap gap-2">{(['Chap', 'Yuqori', "O'ng", 'Past'] as const).map((label, i) => <label key={label} className="text-xs">{label} <input aria-label={label} type="number" min="0" max="1000" value={i === 0 ? start?.x ?? '' : i === 1 ? start?.y ?? '' : i === 2 ? end?.x ?? '' : end?.y ?? ''} onChange={(e) => {
      const value = Math.max(0, Math.min(1000, Number(e.target.value)));
      if (i < 2) setStart((p) => ({ x: i === 0 ? value : p?.x ?? 0, y: i === 1 ? value : p?.y ?? 0 }));
      else setEnd((p) => ({ x: i === 2 ? value : p?.x ?? 0, y: i === 3 ? value : p?.y ?? 0 }));
    }} className="w-16 rounded border border-slate-300 bg-white px-1 py-1 text-slate-900" /></label>)}</div>
    <div className="mt-3 flex gap-2"><button type="button" disabled={!box || !ready} onClick={() => { if (box) onSave({ page: pageNumber, bbox: box }); }} className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Rasmni qo'shish</button><button type="button" onClick={onCancel} className="rounded-lg px-3 py-2 text-xs text-slate-600 dark:text-slate-300">Bekor qilish</button></div>
  </div>;
}
