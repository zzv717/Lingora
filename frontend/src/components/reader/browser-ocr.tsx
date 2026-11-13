"use client";
/** Local, opt-in OCR. Only recognized text is sent to Lingora; images stay in the browser. */
import { useEffect, useRef, useState } from "react";
import { get, getAccessToken, post } from "@/lib/api";
import { Button } from "@/components/ui";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
import type { Worker } from "tesseract.js";

type OCRLine = { text: string; bbox: [number, number, number, number] };

export function BrowserOCR({ bookId, pending, onUpdate }: { bookId: string; pending: number; onUpdate: () => void }) {
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const stopped = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { stopped.current = true; mounted.current = false; }; }, []);

  const start = async () => {
    stopped.current = false; setRunning(true); setError("");
    let worker: Worker | undefined;
    let loading: PDFDocumentLoadingTask | undefined;
    let processed = 0, skipped = 0, exerciseCount = 0, wordCount = 0;
    try {
      const { pages } = await get<{ pages: number[] }>(`/books/${bookId}/ocr/pending`);
      if (!pages.length) { setStatus("OCR talab qiladigan sahifa qolmadi."); return; }
      setStatus("Bepul OCR dasturi yuklanmoqda (birinchi marta bir necha MB)...");
      const [pdfjs, tesseract] = await Promise.all([import("pdfjs-dist"), import("tesseract.js")]);
      if (stopped.current) return;
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
      worker = await tesseract.createWorker("eng", 1, {
        workerPath: "/ocr/worker.min.js", corePath: "/ocr", langPath: "/ocr", workerBlobURL: false,
      });
      if (stopped.current) return;
      loading = pdfjs.getDocument({ url: `/backend/api/v1/books/${bookId}/file`,
        httpHeaders: { authorization: `Bearer ${getAccessToken()}` } });
      const pdf = await loading.promise;
      for (let index = 0; index < pages.length; index++) {
        const number = pages[index];
        if (stopped.current) break;
        setStatus(`${index + 1}/${pages.length}: ${number}-sahifa o'qilmoqda. ${processed} ta saqlandi, ${skipped} ta aniqlanmadi.`);
        const page = await pdf.getPage(number);
        const base = page.getViewport({ scale: 1 });
        const scale = Math.min(2, 2400 / Math.max(base.width, base.height));
        const viewport = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Sahifa tasvirini yaratib bo'lmadi.");
        await page.render({ canvasContext: ctx, viewport }).promise;
        const result = await worker.recognize(canvas, {}, { blocks: true, text: true });
        canvas.width = 1; canvas.height = 1;
        page.cleanup();
        if (stopped.current) break;
        const lines: OCRLine[] = [];
        for (const block of result.data.blocks || []) for (const par of block.paragraphs) for (const line of par.lines) {
          const text = line.text.trim().slice(0, 1000);
          if (!text) continue;
          const b = line.bbox;
          lines.push({ text, bbox: [b.x0 / scale, b.y0 / scale, b.x1 / scale, b.y1 / scale] });
        }
        if (lines.map((l) => l.text).join(" ").length < 24) { skipped++; continue; }
        const saved = await post<{ already_processed: boolean; exercises_added: number; words_added: number }>(
          `/books/${bookId}/ocr/pages/${number}`, { lines: lines.slice(0, 500) });
        if (!saved.already_processed) { processed++; exerciseCount += saved.exercises_added; wordCount += saved.words_added; }
      }
      if (mounted.current) {
        setStatus(`${stopped.current ? "To'xtatildi" : "Yakunlandi"}: ${processed} sahifa saqlandi; ${skipped} sahifa o'qilmadi. ${exerciseCount} mashq va ${wordCount} lug'at nomzodi topildi. OCR natijalari tekshirilishi kerak.`);
        onUpdate();
      }
    } catch (e) {
      if (mounted.current) { setError(e instanceof Error ? e.message : "OCR bajarilmadi."); onUpdate(); }
    } finally {
      if (worker) await worker.terminate().catch(() => {});
      if (loading) await loading.destroy().catch(() => {});
      if (mounted.current) setRunning(false);
    }
  };

  if (!pending && !status && !running) return null;
  return <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-800 dark:bg-amber-950/30">
    <p className="font-semibold text-amber-900 dark:text-amber-200">Skanerlangan sahifalar: {pending} ta</p>
    <p className="mt-1 text-amber-800 dark:text-amber-300">Bepul OCR rasmlarni qurilmangizda o'qiydi, topilgan matnni kitobingizga saqlaydi. Ko'p sahifalar uzoq davom etishi mumkin; tabni ochiq saqlang. To'xtatsangiz, keyin davom ettirishingiz mumkin.</p>
    <p className="mt-1 text-amber-800 dark:text-amber-300">Mashqlar avtomatik aniqlanadi, lekin xatolar bo'lishi mumkin. Tarjima va darajaga mos tanlash hali alohida bosqich.</p>
    {status && <p role="status" className="mt-2 text-slate-700 dark:text-slate-200">{status}</p>}
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    <div className="mt-3">{running ? <Button variant="secondary" size="sm" onClick={() => { stopped.current = true; setStatus("Joriy sahifa tugagach to'xtaydi..."); }}>To'xtatish</Button> :
      <Button size="sm" disabled={!pending} onClick={start}>Bepul OCRni boshlash</Button>}</div>
  </div>;
}
