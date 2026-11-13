"use client";
/** Local, opt-in OCR. Only recognized text is sent to Lingora; images stay in the browser. */
import { useEffect, useRef, useState } from "react";
import { ApiErr, get, getAccessToken, post } from "@/lib/api";
import { Button } from "@/components/ui";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
import type { Worker } from "tesseract.js";
import { ocrBoxToPdf } from "@/lib/ocr-geometry";

type OCRWord = { text: string; bbox: [number, number, number, number]; confidence: number };
type OCRLine = { text: string; bbox: [number, number, number, number]; confidence: number; words: OCRWord[] };
type Preview = { page_number: number; text: string; already_processed: boolean;
  lesson: { title: string } | null; warnings: { code: string; message_uz: string }[];
  exercises: { title: string; type: string; instructions: string; geometry: unknown;
    questions: { number: string; prompt: string }[] }[];
  layout_review: { candidates: { number: string; instruction: string; bbox: number[];
    lines: { text: string; confidence: number | null }[];
    numbered_item_candidates: { number: string; text: string; continuation_lines: string[] }[];
    image_candidates: { bbox: number[] }[] }[]; warnings: string[] } };

export function BrowserOCR({ bookId, pageCount, pending, onUpdate }: { bookId: string; pageCount: number; pending: number; onUpdate: () => void }) {
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [pageInput, setPageInput] = useState("1");
  const [preview, setPreview] = useState<Preview | null>(null);
  const stopped = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { stopped.current = true; mounted.current = false; }; }, []);

  const start = async (previewOnly: boolean) => {
    const selected = Number(pageInput);
    if (previewOnly && (!Number.isInteger(selected) || selected < 1 || selected > pageCount)) {
      setError(`Sahifa raqami 1–${pageCount} oralig'ida bo'lishi kerak.`); return;
    }
    stopped.current = false; setRunning(true); setError(""); setPreview(null);
    let worker: Worker | undefined;
    let loading: PDFDocumentLoadingTask | undefined;
    let processed = 0, skipped = 0, exerciseCount = 0, wordCount = 0;
    const skippedPages: number[] = [];
    try {
      const pages = previewOnly ? [selected] : (await get<{ pages: number[] }>(`/books/${bookId}/ocr/pending`)).pages;
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
        let exceedsLimit = false;
        for (const block of result.data.blocks || []) for (const par of block.paragraphs) for (const line of par.lines) {
          const text = line.text.trim();
          if (!text) continue;
          const detectedWords = line.words.filter((word) => word.text.trim() && Number.isFinite(word.confidence));
          if (text.length > 1000 || detectedWords.length > 200 || detectedWords.some((word) => word.text.trim().length > 200)) {
            exceedsLimit = true; break;
          }
          const words = detectedWords.map((word) => ({ text: word.text.trim(),
            bbox: ocrBoxToPdf(word.bbox, viewport, page.view),
            confidence: Math.max(0, Math.min(100, word.confidence)) }));
          lines.push({ text, bbox: ocrBoxToPdf(line.bbox, viewport, page.view),
            confidence: Math.max(0, Math.min(100, line.confidence)), words });
        }
        const confidence = lines.reduce((sum, line) => sum + line.confidence, 0) / Math.max(lines.length, 1);
        if (exceedsLimit || lines.length > 500 || lines.map((l) => l.text).join(" ").length < 24 || confidence < 40) {
          skipped++; skippedPages.push(number); continue;
        }
        if (previewOnly) {
          const result = await post<Preview>(`/books/${bookId}/ocr/pages/${number}/preview`, { lines });
          if (mounted.current) setPreview(result);
        } else {
          try {
            const saved = await post<{ already_processed: boolean; exercises_added: number; words_added: number }>(
              `/books/${bookId}/ocr/pages/${number}`, { lines });
            if (!saved.already_processed) { processed++; exerciseCount += saved.exercises_added; wordCount += saved.words_added; }
          } catch (e) {
            if (e instanceof ApiErr && ["MIXED_PAGE_REVIEW_REQUIRED", "OCR_NO_EXERCISE_REVIEW"].includes(e.code)) {
              skipped++; skippedPages.push(number); continue;
            }
            throw e;
          }
        }
      }
      if (mounted.current) {
        setStatus(previewOnly
          ? (stopped.current ? "Sinov to'xtatildi. Hech narsa saqlanmadi." : skipped ? `${skippedPages.join(", ")}-sahifa o'qilmadi yoki ishonchliligi past. Hech narsa saqlanmadi.` : "Sinov tugadi. Hech narsa saqlanmadi; natijani PDF bilan solishtiring.")
            : `${stopped.current ? "To'xtatildi" : "Yakunlandi"}: ${processed} sahifa saqlandi; ${skipped} sahifa OCR yoki mashq aniqlashda tekshiruvga qoldi${skippedPages.length ? ` (${skippedPages.join(", ")})` : ""}. ${exerciseCount} mashq va ${wordCount} lug'at nomzodi topildi. Tekshirilmagan sahifalar navbatda qoladi. OCR natijalari tekshirilishi kerak.`);
        if (!previewOnly) onUpdate();
      }
    } catch (e) {
      if (mounted.current) { setError(e instanceof Error ? e.message : "OCR bajarilmadi."); onUpdate(); }
    } finally {
      if (worker) await worker.terminate().catch(() => {});
      if (loading) await loading.destroy().catch(() => {});
      if (mounted.current) setRunning(false);
    }
  };

  return <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-800 dark:bg-amber-950/30">
    <p className="font-semibold text-amber-900 dark:text-amber-200">Skanerlangan sahifalar: {pending} ta</p>
    <p className="mt-1 text-amber-800 dark:text-amber-300">Bepul OCR rasmlarni qurilmangizda o'qiydi, topilgan matnni kitobingizga saqlaydi. Ko'p sahifalar uzoq davom etishi mumkin; tabni ochiq saqlang. To'xtatsangiz, keyin davom ettirishingiz mumkin.</p>
    <p className="mt-1 text-amber-800 dark:text-amber-300">Tajriba funksiyasi: mashqlar tushib qolishi mumkin. Saqlangan sahifani xavfsiz qayta tahlil qilish hali yo'q; avval kichik sinov qiling. Natijalar tasdiqlangan javob emas.</p>
    {status && <p role="status" className="mt-2 text-slate-700 dark:text-slate-200">{status}</p>}
    {error && <p role="alert" className="mt-2 text-red-700 dark:text-red-300">{error}</p>}
    {preview && <div className="mt-3 rounded-lg bg-white p-3 dark:bg-slate-900">
      <p className="font-medium">{preview.page_number}-PDF sahifa: {preview.exercises.length} ta mashq nomzodi. Dars: {preview.lesson?.title || "biriktirilmagan"}.</p>
      <p className="text-xs">{preview.already_processed ? "Sahifa oldin ishlangan; bu faqat yangi ko'rib chiqish." : "Sinov natijasi saqlanmagan."}</p>
      {preview.exercises.map((ex, i) => <div key={i} className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-700">
        <p>{ex.title} · {ex.type} · {ex.questions.length} savol · {ex.geometry ? "koordinata bor" : "koordinata yo'q"}</p>
        <p>{ex.instructions}</p><ul className="ml-4 list-disc">{ex.questions.map((q, j) => <li key={j}>{q.number}. {q.prompt}</li>)}</ul>
      </div>)}
      <details className="mt-2"><summary>Geometrik ko'rib chiqish: {preview.layout_review.candidates.length} ta tekshirilmagan hudud</summary>
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">Hudud va savol chegaralari taxminiy: nazariy matn aralashishi yoki mashq keyingi sahifada davom etishi mumkin. Asl sahifa bilan solishtiring. Bu natija saqlanmaydi.</p>
        {preview.layout_review.candidates.map((candidate, i) => <div key={i} className="mt-2 border-t border-slate-200 pt-2 text-xs dark:border-slate-700">
          <p>Raqam: {candidate.number} · OCR chiziqlari: {candidate.lines.length} · raqamlangan satr nomzodlari: {candidate.numbered_item_candidates.length}</p>
          <p>{candidate.instruction}</p><p>PDF hududi: {candidate.bbox.map((n) => n.toFixed(1)).join(", ")} · ustma-ust rasm hududlari: {candidate.image_candidates.length}</p>
          <details><summary>Hudud matni</summary><ul>{candidate.lines.map((line, j) => <li key={j}>{line.text}</li>)}</ul></details>
          {candidate.numbered_item_candidates.length > 0 && <details className="mt-2"><summary>Vaqtinchalik interaktiv ko'rinishni sinash</summary>
            <p className="my-1 text-amber-700 dark:text-amber-300">Bu faqat ko'rinish sinovi: javoblar saqlanmaydi va tekshirilmaydi. Savol matni va chegaralari OCR taxmini.</p>
            {candidate.numbered_item_candidates.map((item, j) => <div key={j} className="my-2 rounded border border-slate-200 p-2 dark:border-slate-700">
              <p>{item.text}</p>{item.continuation_lines.map((text, k) => <p key={k}>{text}</p>)}
              <label className="mt-1 block">{item.number}-savol javobi <textarea rows={2} className="mt-1 block w-full rounded border border-slate-300 bg-white p-1 dark:border-slate-600 dark:bg-slate-800" /></label>
            </div>)}
          </details>}
        </div>)}
      </details>
      <details className="mt-2"><summary>OCR matni</summary><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{preview.text}</pre></details>
      {!!preview.warnings.length && <details className="mt-2"><summary>Ogohlantirishlar</summary><ul>{preview.warnings.map((w, i) => <li key={i}>{w.message_uz}</li>)}</ul></details>}
    </div>}
    <div className="mt-3 flex flex-wrap items-center gap-2">{running ? <Button variant="secondary" size="sm" onClick={() => { stopped.current = true; setStatus("Joriy sahifa tugagach to'xtaydi..."); }}>To'xtatish</Button> : <>
      <label>Sahifa <input aria-label="OCR sinov sahifasi" type="number" min={1} max={pageCount} value={pageInput} onChange={(e) => setPageInput(e.target.value)} className="w-20 rounded border border-slate-300 bg-white px-2 py-1 dark:bg-slate-800" /></label>
      <Button variant="secondary" size="sm" disabled={!pageCount} onClick={() => start(true)}>Sahifani saqlamasdan sinash</Button>
      <Button size="sm" disabled={!pending} onClick={() => start(false)}>Bepul OCRni saqlash</Button></>}</div>
  </div>;
}
