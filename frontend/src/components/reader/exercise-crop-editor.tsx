"use client";
/**
 * "Tuzatish" editor: drag / resize the exercise box directly on the page image.
 *
 * Everything happens locally on the rendered PDF; only the final normalized box
 * (four numbers) is sent to the backend, where it replaces the AI box for that exercise
 * and is logged for accuracy analysis. All UI text is Uzbek.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { patch } from "@/lib/api";
import { Button } from "@/components/ui";
import {
  boxStyle, loadPdf, normalizeBox, overlapRatio, renderPageToCanvas,
  type NormalizedBox,
} from "./exercise-crops";
import type { PDFDocumentProxy } from "pdfjs-dist";

type Corner = "nw" | "ne" | "sw" | "se";
const HANDLES: { id: Corner; className: string }[] = [
  { id: "nw", className: "-left-1.5 -top-1.5 cursor-nwse-resize" },
  { id: "ne", className: "-right-1.5 -top-1.5 cursor-nesw-resize" },
  { id: "sw", className: "-left-1.5 -bottom-1.5 cursor-nesw-resize" },
  { id: "se", className: "-right-1.5 -bottom-1.5 cursor-nwse-resize" },
];

export function ExerciseCropEditor({ bookId, page, initial, regionId, onSaved, onCancel }: {
  bookId: string; page: number; initial: NormalizedBox; regionId: string | null;
  onSaved: (result: { regionId: string; bbox: NormalizedBox }) => void; onCancel: () => void;
}) {
  const [box, setBox] = useState<NormalizedBox>(() => normalizeBox(initial) || [0.1, 0.1, 0.9, 0.5]);
  const [image, setImage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [ready, setReady] = useState(false);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);
  const drag = useRef<{ mode: "move" | Corner; startX: number; startY: number; box: NormalizedBox } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdf = await loadPdf(bookId);
        pdfRef.current = pdf;
        const canvas = await renderPageToCanvas(pdf, page, 2);
        if (cancelled) return;
        setImage(canvas.toDataURL("image/png"));
        canvas.width = 0; canvas.height = 0;
        setReady(true);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Sahifa yuklanmadi.");
      }
    })();
    return () => {
      cancelled = true;
      const pdf = pdfRef.current as (PDFDocumentProxy & { destroy?: () => Promise<void> }) | null;
      if (pdf?.destroy) void pdf.destroy().catch(() => {});
      pdfRef.current = null;
    };
  }, [bookId, page]);

  const point = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!ready) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = point(event);
    drag.current = { mode: "move", startX: start.x, startY: start.y, box };
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    const now = point(event);
    const dx = now.x - state.startX;
    const dy = now.y - state.startY;
    const [x1, y1, x2, y2] = state.box;
    let next: NormalizedBox;
    if (state.mode === "move") {
      const width = x2 - x1, height = y2 - y1;
      const left = Math.max(0, Math.min(1 - width, x1 + dx));
      const top = Math.max(0, Math.min(1 - height, y1 + dy));
      next = [left, top, left + width, top + height];
    } else {
      const left = state.mode.includes("w") ? Math.min(x1 + dx, x2 - 0.02) : x1;
      const top = state.mode.includes("n") ? Math.min(y1 + dy, y2 - 0.02) : y1;
      const right = state.mode.includes("e") ? Math.max(x2 + dx, x1 + 0.02) : x2;
      const bottom = state.mode.includes("s") ? Math.max(y2 + dy, y1 + 0.02) : y2;
      next = [Math.max(0, left), Math.max(0, top), Math.min(1, right), Math.min(1, bottom)];
    }
    const normalized = normalizeBox(next);
    if (normalized) setBox(normalized);
  };

  const endDrag = () => { drag.current = null; };

  const startResize = (corner: Corner) => (event: React.PointerEvent<HTMLButtonElement>) => {
    if (!ready) return;
    event.preventDefault();
    event.stopPropagation();
    const host = (event.currentTarget.closest("[data-editor-host]") as HTMLDivElement | null);
    if (!host) return;
    (event.currentTarget.parentElement as HTMLElement | null)?.releasePointerCapture?.(event.pointerId);
    drag.current = { mode: corner, startX: 0, startY: 0, box };
    const rect = host.getBoundingClientRect();
    drag.current.startX = (event.clientX - rect.left) / rect.width;
    drag.current.startY = (event.clientY - rect.top) / rect.height;
    host.setPointerCapture?.(event.pointerId);
    setBox((current) => current);
  };

  const nudge = (key: "left" | "top" | "right" | "bottom", value: number) => {
    if (!Number.isFinite(value)) return;
    const clamped = Math.max(0, Math.min(1, value));
    setBox((current) => {
      const [x1, y1, x2, y2] = current;
      const next: NormalizedBox = key === "left" ? [Math.min(clamped, x2 - 0.01), y1, x2, y2]
        : key === "top" ? [x1, Math.min(clamped, y2 - 0.01), x2, y2]
          : key === "right" ? [x1, y1, Math.max(clamped, x1 + 0.01), y2]
            : [x1, y1, x2, Math.max(clamped, y1 + 0.01)];
      return normalizeBox(next) || current;
    });
  };

  const save = useCallback(async () => {
    const normalized = normalizeBox(box);
    if (!normalized) { setError("Chegara juda kichik. Kattaroq hudud tanlang."); return; }
    if (normalized[2] - normalized[0] < 0.02 || normalized[3] - normalized[1] < 0.02) {
      setError("Chegara juda ingichka: mashqning butun qismini qamrab oling."); return;
    }
    setSaving(true); setError("");
    try {
      if (!regionId) throw new Error("Bu mashq uchun chegara yozuvi topilmadi. Sahifani qayta tahlil qiling.");
      const response = await patch<{ region: { id: string; bbox: number[] }; message_uz?: string }>(
        `/books/${bookId}/exercise-regions/${regionId}`, { bbox: normalized, note: "qo'lda tuzatildi" });
      const saved = normalizeBox(response.region?.bbox) || normalized;
      onSaved({ regionId: response.region?.id || regionId, bbox: saved });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chegarani saqlab bo'lmadi.");
    } finally {
      setSaving(false);
    }
  }, [bookId, box, onSaved, regionId]);

  return (
    <div className="mt-3 rounded-2xl border border-indigo-200 bg-white p-3 shadow-sm dark:border-indigo-800 dark:bg-slate-900">
      <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">Qirqim chegarasini tuzatish</p>
      <p className="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
        Mashqning to&apos;liq qismini qamrab oling: sarlavhadan boshlab oxirgi bandgacha.
        Ichki bandlar (1) 2) a) b) chegara ichida qolishi kerak. Rasmni sudrab ko&apos;chiring
        yoki burchaklaridan tortib o&apos;lchamini o&apos;zgartiring.
      </p>
      {error && <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-300">{error}</p>}
      {!ready && !error && <p role="status" className="mt-2 text-xs text-slate-500">Sahifa yuklanmoqda…</p>}
      <div className="mt-2 max-h-[65vh] overflow-auto rounded-xl bg-slate-200 p-2 dark:bg-slate-800">
        <div data-editor-host className="relative mx-auto w-full max-w-2xl touch-none select-none"
          onPointerDown={onPointerDown} onPointerMove={onPointerMove}
          onPointerUp={endDrag} onPointerCancel={endDrag}>
          {image
            ? <img src={image} alt={`PDF ${page}-sahifa: chegara tanlash uchun`} className="block h-auto w-full rounded-lg" draggable={false} />
            : <div className="aspect-[3/4] w-full rounded-lg bg-slate-300 dark:bg-slate-700" />}
          {ready && (
            <div className="absolute cursor-move border-2 border-indigo-600 bg-indigo-500/15 shadow-[0_0_0_9999px_rgba(15,23,42,0.35)]"
              style={boxStyle(box)}>
              {HANDLES.map((handle) => (
                <button key={handle.id} type="button" aria-label={`${handle.id.toUpperCase()} burchakni tortish`}
                  onPointerDown={startResize(handle.id)}
                  className={`absolute h-3.5 w-3.5 rounded-sm border border-white bg-indigo-600 ${handle.className}`} />
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {(["left", "top", "right", "bottom"] as const).map((key, index) => (
          <label key={key} className="text-xs text-slate-600 dark:text-slate-300">
            {["Chap", "Yuqori", "O'ng", "Past"][index]}{" "}
            <input type="number" min={0} max={100} step={0.1} value={Math.round(box[index] * 1000) / 10}
              aria-label={["Chap chegara", "Yuqori chegara", "O'ng chegara", "Past chegara"][index]}
              onChange={(e) => nudge(key, Number(e.target.value) / 100)}
              className="w-16 rounded border border-slate-300 bg-white px-1 py-1 text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white" />
            %
          </label>
        ))}
        <button type="button" className="text-xs text-indigo-700 underline dark:text-indigo-300"
          onClick={() => setBox(normalizeBox(initial) || box)}>AI chegarasiga qaytarish</button>
      </div>
      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
        Faqat to&apos;rtta raqam (0–100%) serverga yuboriladi; sahifa rasmi yuklanmaydi.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" size="sm" loading={saving} disabled={!ready || saving} onClick={save}>Saqlash</Button>
        <Button type="button" size="sm" variant="ghost" disabled={saving} onClick={onCancel}>Bekor qilish</Button>
      </div>
    </div>
  );
}

/** Overlap check used by callers that add a new box next to existing ones (0.1 = 10%). */
export function conflictsWith(box: NormalizedBox, others: NormalizedBox[]): boolean {
  return others.some((other) => overlapRatio(box, other) > 0.1);
}
