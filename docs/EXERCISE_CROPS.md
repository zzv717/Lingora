# Exercise crops: normalized regions, vision detection and manual correction

Status: implemented on `backend/app/services/ai/vision_regions.py`,
`backend/app/api/v1/vision_regions.py` and the reader components.
It is **review-only**: crops help a student follow the exercise, they never create
answer keys, grades or progress.

---

## 1. How the old flow worked (what was there before this change)

| Question | Old answer |
| --- | --- |
| Where does the page image come from? | `render_pages()` in `app/services/ai/vision_map.py` renders a PDF page with PyMuPDF at `scale = min(2.0, 1800 / longest_edge)` — 144 DPI for an A4 page, and the shrink factor depends on the page size. |
| Where did coordinates come from? | Three different places: rule/OCR detection (`structure_detector`, `layout_review.visual_candidates`), the blank-level `blanks[].bbox` computed by `pdf_extractor` (PDF points), and the picture locator (`vision_topic.PictureRegion`, 0–1000 of the rendered page). |
| Where did the crop happen? | Only for exercise *pictures*: `frontend/src/components/reader/pdf-picture-crops.ts` rendered the page in the browser with pdf.js (`scale = min(2, 1800/longest)`), multiplied the 0–1000 box by the canvas size and drew it into a second canvas. There was **no crop of the exercise itself**. |
| At what image size? | Unpredictable: `min(2, 1800/max(w,h))` on the backend (≈144 DPI) and in the viewer (also 1800 px long edge), but the browser canvas is device-pixel dependent. |
| Where was the exercise boundary decided? | `layout_review._find_anchor` + "until the next anchor" (`end = anchors[pos+1].index`) over OCR lines, and the vision model's free-form answer for `vision-exercises`. |

## 2. Concrete causes of the wrong crops

1. **Coordinate scale mismatch.** Boxes were stored in the units of whichever renderer
   produced them (PDF points, 0–1000 of an 1800 px render, or OCR pixels). Re-rendering at
   another scale or on a high-DPI screen multiplies the error; a 0–1000 box drawn on a
   different aspect-ratio canvas is shifted and cut.
2. **Boundary = "until the next number".** `layout_review` closes an exercise at the next
   anchor. Inner items `1) 2) 3)` and `a) b)` match the same number patterns, so an exercise
   was cut after its first item or split into several "exercises".
3. **OCR misreads the exercise number.** Circled numbers come back as `Gt`, `@`, `2)`, so the
   anchor is missed entirely and the region start is a neighbouring line.
4. **Two columns mixed.** Anchor search is a single vertical scan; the "left limit" heuristic
   only rejects far-left lines. Matching tables and column layouts were ordered line-by-line,
   producing boxes that span the gutter and merge two exercises.
5. **Cross-page exercises.** `visual_candidates` explicitly reports
   `CROSS_PAGE_GROUPING_NOT_AVAILABLE`; an exercise that continues on the next page was
   truncated at the page bottom with no link to its continuation.
6. **Page furniture included.** Page numbers, headers/footers and running titles were only
   excluded if they failed the number+command pattern, and pictures were never part of the
   box even when the items were arranged around them.
7. **No validation.** Nothing checked `0 <= x1 < x2 <= page`, overlap, implausible size or
   confidence, so one bad model answer produced a silently wrong crop.
8. **No cache and no repairs.** Every retry was a paid call, and a partially wrong answer was
   either accepted as-is or the whole page failed with `AI_BAD_OUTPUT`.

## 3. The new flow

```
PDF page ──render 200 DPI (PyMuPDF)──► PNG + sha256
                                          │
                       cache hit (vision_page_region_cache)?
                        │yes                                  │no
                        ▼                                     ▼
                 cached regions            vision model (JSON schema)
                                                             │
                            clean_regions → validate_regions → sequential check
                                     (one repair retry when numbers gap/duplicate)
                                                             │
                                  confidence < 0.7 → crop is sent back with the
                                  page image for one verification pass
                                                             │
                                   vision_exercise_regions (bbox 0..1, source ai)
                                                             │
   reader / preview / review panel: crop from the ORIGINAL PDF in the browser
   (box * actual canvas size, padding 1.5%)  ── "Tuzatish" → manual box (source manual)
```

Key properties:

* **Normalized boxes.** Every stored box is `[x1, y1, x2, y2]` with `0..1` of the rendered
  page. Pixels are computed only at crop time:
  `backend: bbox_to_pixels()/crop_png()`, `frontend: boxToPixels()/cropFromCanvas()`.
* **Detected once per page image.** The cache key is
  `<page image sha256>:<pdf page>:<page count>`, so re-running detection on unchanged pages
  costs nothing. `force: true` (the "Qayta aniqlash" button) bypasses it.
* **Structured output.** `REGION_SCHEMA` is sent as `response_format: json_schema` (strict)
  to OpenAI-compatible providers; providers that reject it fall back to `json_object` once.
* **Validated in code.** Inside the page, `x2 > x1`, `y2 > y1`, overlap ≤ 10% of the smaller
  box (the fragment is dropped, the larger box kept), size flags `< 3%` / `> 90%`, sequential
  printed numbers (gap/duplicate → exactly one repair request for that page).
* **Verification pass.** Boxes with `confidence < 0.7` are rendered as a crop and sent back
  together with the full page: "is this a complete and correct crop?". A returned
  `corrected_bbox` replaces the box (flag `corrected_by_verification`), otherwise the box is
  flagged `verification_rejected` for manual review.
* **Manual correction wins.** `PATCH /exercise-regions/{id}` stores the drawn box with
  `source="manual"`, `confidence=1.0`, never overwritten by a later AI pass, and writes a
  `vision_region_corrections` audit row (previous box, new box, note, who, when).
* **Continuations.** `continues_on_next_page` / `continues_from_previous_page` are stored and
  a box starting at the top of a page is linked (`continued_from_region_id`) to the previous
  page's last box. The UI shows both parts and the link; the parts are not stitched into one
  bitmap on the server.
* **Padding.** 1.5% on every side inside `pad_bbox()`, clamped to the page.
* **Debug mode.** `VISION_REGION_DEBUG=true` (or `--debug`) writes page renders with the AI
  boxes (blue) and manual corrections (green) drawn on them.

## 4. Prompts and reference samples

`system_prompt()` in `vision_regions.py` contains generic layout rules:

* the exercise number is usually bold / in a circle next to the heading;
* inner items `1) 2) a) b)` are **not** exercises and stay inside the box;
* the box covers heading → last item, with no margin;
* on two-column pages each box stays in its own column;
* page numbers, headers/footers and captions are not exercises.

The few-shot block is a **geometry** example (normalized boxes on a typical A4 textbook
page) with a short explanation of why exercise 3 and 4 do not cross the middle — no
Round-Up-specific text is hardcoded, so other books behave the same way. Reference pages
from Round-Up 1 can be added as extra examples without changing any rule.

## 5. API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/books/{id}/exercise-regions?page=` | stored boxes + warnings + correction stats |
| POST | `/books/{id}/exercise-regions/detect` | `{page_numbers, consent_images_to_provider, force}` — detects and stores boxes |
| PATCH | `/books/{id}/exercise-regions/{region_id}` | `{bbox, note}` — manual correction (wins over AI) |
| POST | `/books/{id}/exercise-regions` | add a box the model missed |
| DELETE | `/books/{id}/exercise-regions/{region_id}` | remove a box (logged) |
| PATCH | `/books/{id}/exercise-regions/{region_id}/review` | mark reviewed / needs review |
| GET | `/books/{id}/exercise-regions/{region_id}/crop?as_json=false` | PNG crop of the original page |
| GET | `/books/{id}/exercise-regions/{region_id}/debug.png` | page + boxes drawn |
| POST | `/books/{id}/exercise-regions/debug` | write debug PNGs (requires the env flag) |
| GET | `/books/{id}/exercise-regions/cache/stats` | cache entries / hits |
| POST | `/books/{id}/exercise-regions/cache/prune` | delete expired cache rows |
| POST | `/books/{id}/exercise-regions/attach` | link saved vision exercises to their boxes |

`GET /lessons/{id}/exercises` keeps its previous shape; each exercise may now contain an
optional `region` object (`bbox` normalized 0..1, `source`, `confidence`, `needs_review`,
continuation flags). Old clients that ignore it keep working.

## 6. UI (all text in Uzbek)

* `ExerciseCrop` — the crop above the questions with the `Tuzatish` button, the confidence
  badge and the note "Qirqim noto'g'ri bo'lsa, «Tuzatish» bilan chegarani sudrab
  o'zgartiring."
* `ExerciseCropEditor` — drag the box, resize with four corner handles, or type the four
  edges in percent; `Saqlash` / `Bekor qilish`; "AI chegarasiga qaytarish" restores the model
  box. Only four numbers are sent to the server.
* `RegionReview` — the "Mashq qirqimlari" panel on the book page: page range, one consent
  checkbox, detection progress, per-page crops, warnings and "Tekshirildi deb belgilash".
* The vision exercise preview (`vision-map-preview.tsx`) shows the exercise box when the
  notebook preview includes one and keeps a correction locally as well.

## 7. Configuration

```env
# .env / backend/.env
AI_PROVIDER=openai_compatible
AI_API_KEY=sk-...            # never hardcoded, always from the environment
AI_BASE_URL=https://api.openai.com/v1
AI_VISION_MODEL=gpt-4o-mini  # any model that accepts images

VISION_REGION_DPI=200              # >=150 enforced; long edge capped by the next value
VISION_REGION_MAX_PIXELS=2600
VISION_REGION_WORKERS=4            # parallel pages (1..8)
VISION_REGION_CACHE_ENABLED=true
VISION_REGION_CACHE_TTL_DAYS=30
VISION_REGION_VERIFY_CONFIDENCE=0.7
VISION_REGION_DEBUG=false
VISION_REGION_DEBUG_DIR=./data/vision-debug
```

## 8. Verification (step 8)

```bash
cd backend
alembic upgrade head                  # adds the three region tables
python -m scripts.verify_exercise_regions --book <book_id> --pages 1-10 --debug
```

The script prints one row per exercise (`page · number · bbox · confidence · source ·
flags`), a second table of failed/suspicious cases with the reason, writes
`regions-report.json`, and with `--debug` writes `page-XXXX.png` with the boxes drawn.
`--mock` runs the same pipeline with a deterministic offline provider — useful for a smoke
test on a machine without an API key, but it is **not** an accuracy measurement.

## 9. Changed files (what and why)

| File | Change |
| --- | --- |
| `backend/app/services/ai/vision_regions.py` | New: schemas, prompts + few-shot geometry, `clean_regions`, `validate_regions`, `sequence_issues`, page render at ≥150 DPI, hash cache, repair retry, low-confidence verification, parallel book detection, crop and debug rendering. |
| `backend/app/services/ai/vision_region_store.py` | New: persistence of regions, manual corrections (priority + audit log), continuation linking, warnings and accuracy stats. |
| `backend/app/models/vision_region.py` | New models `VisionExerciseRegion`, `VisionPageRegionCache`, `VisionRegionCorrection` (boxes are JSON arrays in 0..1). |
| `backend/app/api/v1/vision_regions.py` | New router with ownership, consent, rate limits and Uzbek errors. |
| `backend/alembic/versions/b7c1d2e4f9a3_exercise_regions.py` | Migration for the three tables and indexes. |
| `database/supabase_schema.sql` | Same three tables with RLS policies (27 → 30 tables). |
| `backend/app/services/ai/provider.py` | `json_schema` support for OpenAI-compatible providers with a safe fallback to `json_object`. |
| `backend/app/services/ai/vision_exercises.py` | Asks for and validates a normalized `bbox` per exercise, stores it as a region after saving, exposes it in the preview payload. |
| `backend/app/schemas.py`, `backend/app/api/v1/exercises.py` | Optional `region` on exercise responses (old fields unchanged). |
| `backend/app/core/config.py` | The `VISION_REGION_*` settings. |
| `backend/scripts/verify_exercise_regions.py` | The step-8 verification CLI. |
| `frontend/src/components/reader/exercise-crops.ts` | Normalized-box math, page rendering and cropping from the original PDF. |
| `frontend/src/components/reader/exercise-crop.tsx` | Crop display + `Tuzatish`. |
| `frontend/src/components/reader/exercise-crop-editor.tsx` | Drag/resize editor with `Saqlash` / `Bekor qilish`. |
| `frontend/src/components/reader/region-review.tsx` | Book-page panel for detection, review and correction. |
| `frontend/src/components/reader/preview-exercise.tsx`, `vision-map-preview.tsx` | Show the exercise crop and keep corrections in the saved preview. |
| `frontend/src/app/(app)/reader/[bookId]/page.tsx` | Crop above each saved exercise; correction updates the local state. |
| `frontend/src/lib/types.ts` | `ExerciseRegion` type and `Exercise.region`. |
| `backend/tests/test_vision_regions.py`, `frontend/tests/exercise-crops.test.mjs` | New tests (geometry, validation, cache, repair, verification, corrections, ownership). |
| `backend/tests/test_postgres_and_rls.py` | Table count 27 → 30 with the new RLS policies. |
| `frontend/tests/vision-preview.test.cjs`, `frontend/package.json` | Mock the new modules; run the new geometry test. |

## 10. Known limitations

1. **No live provider run in this environment.** The provider was not configured here, so
   accuracy figures on real Round-Up 1 pages have not been measured; the pipeline was
   verified with a deterministic mock and unit tests. Run the CLI with a real key for the
   table.
2. **No stitched bitmap for cross-page exercises.** The two parts are linked and shown
   separately (`continued_from_region_id`), not merged into one image.
3. **PDF embedded text boxes are untouched.** `blanks[].bbox` for native-text blanks still
   uses PDF points (`geometry: "native_chars"`); only exercise regions are normalized.
4. **Detection is per page.** A page's repair/verification calls are bounded, but a very large
   book (300 pages) is a real cost; the cache only helps after the first run.
5. **The preview path (`vision-topic`) is browser-local.** Its `region` is optional and not
   stored as an exercise; corrections there update the backend box only when the preview
   carries a region id.
6. **Cache scope is the book.** Two users with identical books do not share cache rows
   (keys include the page hash, rows are still owner-scoped for privacy).
7. **The editor needs the exercise's region id.** Exercises saved before this migration have
   no region; run detection (or `attach`) for those pages first.
