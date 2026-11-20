"use client";
/**
 * Sharp illustration for a vocabulary word.
 *
 * The picture is a crop of the ORIGINAL PDF page, rendered on the server at >= 200 DPI
 * from the stored normalized box — not a screenshot of a scaled page — so it stays
 * crisp on retina screens. The <img> asks for ~2x the rendered width, and a click opens
 * a full-size view. Nothing is generated: if the book has no illustration, none is shown.
 */
import { useEffect, useState } from "react";
import { getAccessToken } from "@/lib/api";

const BASE = "/backend/api/v1";
const MAX_EDGE = 1400;

export function VocabPicture({ bookId, wordId, term, className = "" }: {
  bookId: string; wordId: string; term: string; className?: string;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(false);

  useEffect(() => {
    let active = true;
    let url = "";
    setSrc(""); setError("");
    (async () => {
      try {
        const token = getAccessToken();
        const response = await fetch(`${BASE}/books/${bookId}/vocabulary/${wordId}/picture.png?max_edge=${MAX_EDGE}`, {
          headers: token ? { authorization: `Bearer ${token}` } : {},
        });
        if (!response.ok) throw new Error(String(response.status));
        const blob = await response.blob();
        url = URL.createObjectURL(blob);
        if (active) setSrc(url);
      } catch {
        if (active) setError("Rasmni yuklab bo'lmadi.");
      }
    })();
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [bookId, wordId]);

  useEffect(() => {
    if (!zoom) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setZoom(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [zoom]);

  if (error) return <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{error}</p>;
  if (!src) return <div aria-hidden="true" className={`mt-2 h-28 w-40 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800 ${className}`} />;

  return <>
    <button type="button" onClick={() => setZoom(true)}
      className={`group mt-2 block w-fit max-w-full overflow-hidden rounded-xl border border-slate-200 bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 dark:border-slate-700 dark:bg-slate-800 ${className}`}
      aria-label={`${term} so'zining rasmini kattalashtirish`}>
      {/* eslint-disable-next-line @next/next/no-img-element -- a private, authenticated crop has no optimizer URL */}
      <img src={src} alt={`${term} so'zining kitobdagi rasmi`} width={MAX_EDGE} height={MAX_EDGE}
        className="max-h-40 w-auto max-w-full object-contain transition group-hover:opacity-90" />
    </button>
    {zoom && <div role="dialog" aria-modal="true" aria-label={`${term} so'zining rasmi`}
      onClick={() => setZoom(false)}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
      {/* eslint-disable-next-line @next/next/no-img-element -- see above */}
      <img src={src} alt={`${term} so'zining kitobdagi rasmi, katta ko'rinishda`}
        className="max-h-[90vh] max-w-[92vw] rounded-2xl bg-white object-contain shadow-2xl" />
      <button type="button" onClick={() => setZoom(false)}
        className="absolute right-4 top-4 rounded-xl bg-white/90 px-3 py-2 text-sm font-semibold text-slate-800">Yopish</button>
    </div>}
  </>;
}
