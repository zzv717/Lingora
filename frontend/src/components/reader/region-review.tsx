"use client";
/**
 * Exercise crop review panel for scanned books ("Mashq qirqimlari").
 *
 * 1. The user picks pages and consents once; the backend renders each page at >=150 DPI
 *    and sends it to the vision provider for normalized boxes (cached by page hash).
 * 2. Every box is shown as a crop of the ORIGINAL PDF, with a "Tuzatish" editor.
 * 3. "Saqlash" in the editor stores the manual box (it always wins over the AI box) and
 *    the backend logs the change for later accuracy analysis.
 * All UI text is Uzbek; nothing is graded or answered here.
 */
import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { Badge, Button, Card, Spinner, useToast } from "@/components/ui";
import { ExerciseCrop, type CropCorrection } from "./exercise-crop";
import { validBox, type NormalizedBox } from "./exercise-crops";

type Region = {
  id: string; page: number; number: string; title: string; bbox: NormalizedBox;
  source: string; confidence: number; needs_review: boolean; flags: string[];
  continues_from_previous_page: boolean; continues_on_next_page: boolean;
  continued_from_region_id: string | null;
};
type Library = {
  regions: Region[]; warnings: string[]; coordinate_space: string; dpi: number;
  stats: { regions: number; manual: number; low_confidence: number; corrections: number };
};
type DetectResponse = {
  pages: { page: number; cached: boolean; warnings: string[]; regions: Region[]; error?: string; error_code?: string }[];
  detected: number; failed_pages: { page: number; error: string }[]; message_uz: string;
};

export function RegionReview({ bookId, pageCount, onUpdate }: {
  bookId: string; pageCount: number; onUpdate?: () => void;
}) {
  const { toast } = useToast();
  const [library, setLibrary] = useState<Library | null>(null);
  const [loading, setLoading] = useState(true);
  const [consent, setConsent] = useState(false);
  const [pages, setPages] = useState(`1-${Math.min(10, pageCount)}`);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pageWarnings, setPageWarnings] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      setLibrary(await get<Library>(`/books/${bookId}/exercise-regions`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Qirqimlarni yuklab bo'lmadi.");
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  useEffect(() => { void load(); }, [load]);

  function parseRange(text: string): number[] | null {
    const found: number[] = [];
    for (const part of text.split(",")) {
      const chunk = part.trim();
      if (!chunk) continue;
      const range = chunk.match(/^(\d+)\s*-\s*(\d+)$/);
      if (range) {
        const a = Number(range[1]), b = Number(range[2]);
        if (a < 1 || b > pageCount || a > b) return null;
        for (let n = a; n <= b && found.length < 40; n++) if (!found.includes(n)) found.push(n);
      } else if (/^\d+$/.test(chunk)) {
        const n = Number(chunk);
        if (n < 1 || n > pageCount) return null;
        if (!found.includes(n)) found.push(n);
      } else return null;
    }
    return found.length && found.length <= 40 ? found : null;
  }

  async function detect(force = false) {
    const numbers = parseRange(pages);
    if (!numbers) { setError(`Sahifa oralig'ini to'g'ri kiriting (1–${pageCount}, ko'pi bilan 40 sahifa).`); return; }
    if (!consent) { setError("Sahifa rasmlarini AI xizmatiga yuborish uchun rozilik belgilang."); return; }
    setBusy(true); setError(""); setMessage(""); setPageWarnings([]);
    try {
      const response = await post<DetectResponse>(`/books/${bookId}/exercise-regions/detect`, {
        page_numbers: numbers, consent_images_to_provider: true, force,
      });
      setMessage(`${response.message_uz}${response.pages.some((p) => p.cached) ? " (ba'zi sahifalar keshdan olindi)" : ""}`);
      setPageWarnings(response.pages.flatMap((p) => p.warnings.map((w) => `${p.page}-sahifa: ${w}`)));
      if (response.failed_pages.length) {
        toast(`${response.failed_pages.length} sahifa tahlil qilinmadi.`, "error");
      }
      await load();
      onUpdate?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tahlil amalga oshmadi. Qayta urinib ko'ring.");
    } finally {
      setBusy(false);
    }
  }

  function applyCorrection(correction: CropCorrection) {
    setLibrary((current) => current ? {
      ...current,
      regions: current.regions.map((region) => region.id === correction.regionId
        ? { ...region, bbox: correction.bbox, source: "manual", needs_review: false, confidence: 1 }
        : region),
    } : current);
    setMessage("Chegara saqlandi. Endi bu mashq uchun AI natijasi emas, sizning chegara ishlatiladi.");
    onUpdate?.();
  }

  async function markReviewed(region: Region) {
    try {
      await post(`/books/${bookId}/exercise-regions/${region.id}/review`, { needs_review: false });
      setLibrary((current) => current ? {
        ...current,
        regions: current.regions.map((item) => item.id === region.id
          ? { ...item, needs_review: false, flags: [...item.flags, "reviewed_by_user"] } : item),
      } : current);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Belgilab bo'lmadi.", "error");
    }
  }

  const regions = library?.regions || [];
  const grouped = Array.from(new Set(regions.map((r) => r.page)));
  const stats = library?.stats;

  return (
    <Card className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-800 dark:text-slate-100">Mashq qirqimlari (AI + qo&apos;lda tuzatish)</h3>
        {stats && (
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge tone="brand">{stats.regions} chegara</Badge>
            <Badge tone="green">{stats.manual} qo&apos;lda</Badge>
            {stats.low_confidence > 0 && <Badge tone="amber">{stats.low_confidence} ishonchsiz</Badge>}
          </div>
        )}
      </div>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
        Har bir mashq sahifadagi o&apos;z joyidan qirqib olinadi. Chegara normallashtirilgan (0–100%),
        shuning uchun DPI yoki ekran o&apos;lchami o&apos;zgarsa ham qirqim siljimaydi. AI xato qilishi mumkin —
        «Tuzatish» tugmasi bilan chegarani qo&apos;lda to&apos;g&apos;rilang.
      </p>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="text-sm">Sahifalar
          <input value={pages} disabled={busy} onChange={(e) => { setPages(e.target.value); setConsent(false); }}
            placeholder="masalan: 1-5, 9"
            className="ml-2 w-40 rounded-lg border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800" />
        </label>
        <label className="flex max-w-xl items-start gap-2 text-xs">
          <input type="checkbox" checked={consent} disabled={busy} onChange={(e) => setConsent(e.target.checked)} />
          <span>Tanlangan sahifa rasmlari tashqi Vision AI xizmatiga yuborilishiga roziman. Provayder haq olishi mumkin; javoblar va o&apos;quv natijalari yuborilmaydi.</span>
        </label>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" disabled={busy || !consent} loading={busy} onClick={() => detect(false)}>
          {busy ? "Sahifalar tahlil qilinmoqda…" : "Qirqimlarni aniqlash"}
        </Button>
        {regions.length > 0 && (
          <Button size="sm" variant="secondary" disabled={busy || !consent} onClick={() => detect(true)}>
            Qayta aniqlash (keshni chetlab o&apos;tish)
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>Yangilash</Button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-300">{error}</p>}
      {message && <p role="status" className="mt-2 text-xs text-indigo-700 dark:text-indigo-300">{message}</p>}
      {pageWarnings.length > 0 && (
        <ul className="mt-2 max-h-32 space-y-1 overflow-auto text-xs text-amber-700 dark:text-amber-300">
          {pageWarnings.map((warning, index) => <li key={index}>• {warning}</li>)}
        </ul>
      )}
      {library?.warnings.map((warning, index) => (
        <p key={`lib-${index}`} className="mt-1 text-xs text-amber-700 dark:text-amber-300">⚠️ {warning}</p>
      ))}

      {loading ? <div className="mt-4 flex justify-center"><Spinner className="h-6 w-6 text-brand-500" /></div>
        : regions.length === 0 ? (
          <p className="mt-3 rounded-xl bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            Hozircha saqlangan qirqim yo&apos;q. Sahifalarni tanlab «Qirqimlarni aniqlash» tugmasini bosing.
          </p>
        ) : (
          <div className="mt-4 space-y-4">
            {grouped.map((page) => (
              <section key={page}>
                <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200">PDF {page}-sahifa</h4>
                <div className="mt-2 grid gap-3 lg:grid-cols-2">
                  {regions.filter((region) => region.page === page).map((region) => (
                    <div key={region.id} className="rounded-2xl border border-slate-200 p-2 dark:border-slate-700">
                      <div className="flex flex-wrap items-center gap-2 px-1 pb-1">
                        <span className="text-sm font-semibold">Mashq {region.number || "raqamsiz"}</span>
                        <Badge tone={region.source === "manual" ? "green" : "slate"}>
                          {region.source === "manual" ? "qo'lda" : `AI ${Math.round(region.confidence * 100)}%`}
                        </Badge>
                        {region.continues_from_previous_page && <Badge tone="amber">oldingi sahifadan davom</Badge>}
                        {region.continues_on_next_page && <Badge tone="amber">keyingi sahifada davom etadi</Badge>}
                        {region.needs_review && (
                          <button type="button" onClick={() => void markReviewed(region)}
                            className="ml-auto text-[11px] text-emerald-700 underline dark:text-emerald-300">
                            Tekshirildi deb belgilash
                          </button>
                        )}
                      </div>
                      {region.title && <p className="px-1 pb-1 text-xs text-slate-500 dark:text-slate-400">{region.title}</p>}
                      {validBox(region.bbox) ? (
                        <ExerciseCrop bookId={bookId} page={region.page} bbox={region.bbox}
                          regionId={region.id} detection="vision" confidence={region.confidence}
                          needsReview={region.needs_review} onCorrect={applyCorrection} />
                      ) : (
                        <p className="px-1 text-xs text-red-600">Chegara yaroqsiz — «Tuzatish» bilan qayta belgilang.</p>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
        Sahifalar keshda saqlanadi: o&apos;zgarmagan sahifa ikkinchi marta AI ga yuborilmaydi.
        Qirqimlar asl PDFdan brauzerda chiziladi; bu panel javob kaliti yaratmaydi.
      </p>
    </Card>
  );
}
