"use client";
/**
 * Exercise crop geometry shared by the reader, the preview and the "Tuzatish" editor.
 *
 * Boxes always travel as NORMALIZED coordinates: [x1, y1, x2, y2] where 0 is the left/top
 * edge and 1 the right/bottom edge of the page. Pixel rectangles are computed here from the
 * actual canvas size, so a different zoom, DPI or screen can never shift a crop.
 */
import { getAccessToken } from "@/lib/api";
import { withTimeout } from "@/lib/timeout";
import type { PDFDocumentProxy, PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";

export type NormalizedBox = [number, number, number, number];

/** Highest render scale used for crops (>=150 DPI equivalent) with a bounded long edge. */
export const CROP_RENDER_SCALE = 2.4;
export const CROP_MAX_EDGE = 2400;
export const CROP_PADDING = 0.015;

/** True when the box is a usable rectangle inside the page (0..1). */
export function validBox(box: unknown): box is NormalizedBox {
  if (!Array.isArray(box) || box.length !== 4) return false;
  if (!box.every((n) => typeof n === "number" && Number.isFinite(n))) return false;
  const [x1, y1, x2, y2] = box as number[];
  return x1 >= 0 && y1 >= 0 && x2 <= 1 && y2 <= 1 && x2 - x1 > 0.002 && y2 - y1 > 0.002;
}

/** Order corners and clamp into the page; returns null when nothing usable remains. */
export function normalizeBox(box: unknown): NormalizedBox | null {
  if (!Array.isArray(box) || box.length !== 4) return null;
  if (!box.every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  let [x1, y1, x2, y2] = box as number[];
  if (x1 > x2) [x1, x2] = [x2, x1];
  if (y1 > y2) [y1, y2] = [y2, y1];
  const clamp = (n: number) => Math.max(0, Math.min(1, n));
  const result: NormalizedBox = [clamp(x1), clamp(y1), clamp(x2), clamp(y2)];
  return result[2] - result[0] > 0.002 && result[3] - result[1] > 0.002 ? result : null;
}

/** Add 1.5% padding on every side without leaving the page. */
export function padBox(box: NormalizedBox, ratio = CROP_PADDING): NormalizedBox {
  const [x1, y1, x2, y2] = box;
  const padX = (x2 - x1) * ratio;
  const padY = (y2 - y1) * ratio;
  return [Math.max(0, x1 - padX), Math.max(0, y1 - padY), Math.min(1, x2 + padX), Math.min(1, y2 + padY)];
}

/** Normalized box -> pixel rectangle for a concrete canvas width/height. */
export function boxToPixels(box: NormalizedBox, width: number, height: number) {
  const [x1, y1, x2, y2] = padBox(normalizeBox(box) || box);
  const left = Math.max(0, Math.min(width - 1, Math.round(x1 * width)));
  const top = Math.max(0, Math.min(height - 1, Math.round(y1 * height)));
  const right = Math.max(left + 1, Math.min(width, Math.round(x2 * width)));
  const bottom = Math.max(top + 1, Math.min(height, Math.round(y2 * height)));
  return { left, top, width: right - left, height: bottom - top };
}

/** CSS percentage style for drawing a box over a page image (no pixels needed). */
export function boxStyle(box: NormalizedBox) {
  const [x1, y1, x2, y2] = normalizeBox(box) || box;
  return { left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` };
}

/** Intersection over the smaller box; > 0.1 means the boxes overlap too much. */
export function overlapRatio(a: NormalizedBox, b: NormalizedBox): number {
  const width = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
  const height = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
  if (width <= 0 || height <= 0) return 0;
  const area = (x: NormalizedBox) => Math.max(0, x[2] - x[0]) * Math.max(0, x[3] - x[1]);
  const smaller = Math.min(area(a), area(b));
  return smaller > 0 ? (width * height) / smaller : 0;
}

/** Shared authenticated PDF document loader (one load per book/page set). */
export async function loadPdf(bookId: string): Promise<PDFDocumentProxy> {
  const pdfjs = await withTimeout(import("pdfjs-dist"), 60_000, "PDF dasturi yuklanmadi.");
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.js";
  const task: PDFDocumentLoadingTask = pdfjs.getDocument({
    url: `/backend/api/v1/books/${bookId}/file`,
    httpHeaders: { authorization: `Bearer ${getAccessToken()}` },
  });
  try {
    return await withTimeout(task.promise, 120_000, "PDF yuklanmadi.");
  } catch (error) {
    void task.destroy().catch(() => {});
    throw error;
  }
}

/** Render one page to a canvas at a scale that yields at least ~150-200 DPI. */
export async function renderPageToCanvas(pdf: PDFDocumentProxy, pageNumber: number,
  scale = CROP_RENDER_SCALE): Promise<HTMLCanvasElement> {
  const page = await withTimeout(pdf.getPage(pageNumber), 60_000, "PDF sahifasi yuklanmadi.");
  const base = page.getViewport({ scale: 1 });
  const bounded = Math.min(scale, CROP_MAX_EDGE / Math.max(base.width, base.height));
  const viewport = page.getViewport({ scale: bounded });
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("PDF rasmini ko'rsatib bo'lmadi.");
  const task: RenderTask = page.render({ canvasContext: context, viewport });
  await withTimeout(task.promise, 60_000, "PDF sahifasini chizib bo'lmadi.");
  return canvas;
}

/** Crop a normalized box out of a rendered page canvas (PNG data URL). */
export function cropFromCanvas(source: HTMLCanvasElement, box: NormalizedBox,
  maxEdge = 700): string {
  const rect = boxToPixels(box, source.width, source.height);
  const factor = Math.min(1, maxEdge / Math.max(rect.width, rect.height));
  const crop = document.createElement("canvas");
  crop.width = Math.max(1, Math.ceil(rect.width * factor));
  crop.height = Math.max(1, Math.ceil(rect.height * factor));
  const context = crop.getContext("2d");
  if (!context) throw new Error("PDF rasmini qirqib bo'lmadi.");
  context.drawImage(source, rect.left, rect.top, rect.width, rect.height, 0, 0, crop.width, crop.height);
  return crop.toDataURL("image/png");
}
