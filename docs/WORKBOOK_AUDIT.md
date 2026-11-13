# Interactive workbook audit and safety milestone

## Scope and root causes

Lingora uses Next.js with a same-origin backend proxy, FastAPI, SQLAlchemy,
PyMuPDF, local/Supabase storage and optional AI providers. Upload creates a job;
PDF analysis extracts page lines, detects structure, persists book content and
optionally enriches it. The PDF.js reader loads lesson exercises and sends
answers to the API for grading and progress tracking. Vercel Services currently
includes both Next.js and a serverless Python backend; `render.yaml` is an
alternative backend blueprint, not evidence of an active Render deployment.

The previous extractor approximated blank coordinates from string length,
server OCR represented each recognized line as the whole page, and answer-key
matching relied on a global sequential counter. Matching pairs could be treated
as an answer key based on inferred column order. Existing re-analysis removed
pages, lessons, exercises and vocabulary, cascading into user work, and commits
inside the pipeline made the swap non-atomic. Startup recovery could incorrectly
mark jobs owned by another worker as failed. Existing `/ready` checks Supabase
configuration presence rather than proving object storage connectivity.

## Changes in this milestone

- `content_integrity.py`, `books.py`, `pipeline.py`: conservative re-analysis
  guard, write-boundary check, rollback on errors and atomic first-pass content
  persistence. No existing records are replaced. This does not implement staged
  versions or safe reconciliation.
- `pdf_extractor.py`, `structure_detector.py`: native raw character boxes;
  local OCR word/line geometry with confidence and pending state; no guessed
  overlay coordinates; narrowly supported instruction-only headings. Coordinate
  convention for native glyphs: unrotated crop-relative PDF points, top-left
  origin. Browser OCR remains line-only and its blank locations remain unknown.
- `structure_detector.py`, `grading.py`: answer-key mapping by unambiguous
  explicit references or unique unlabelled numbers; ambiguity is reported.
  Inferred matching pairs are not a deterministic key. Correct incomplete
  multi-blank and invalid true/false grading; do not treat parsed key records as
  manually verified.
- `reader-utils.ts`, `pdf-viewer.tsx`, reader and exercise card: refuse legacy
  estimated boxes; show unlocated inputs in the card; preserve geometric width
  and height; queue overlay autosaves and serialize writes. Browser E2E is not
  yet established, so these must be verified before production.
- `main.py`: disable global startup recovery in production / Celery to avoid
  marking another process's live job failed. Stale-job recovery remains unsolved.
- `test_workbook_integrity.py`, `pdf_factory.py`, reader tests: targeted
  regressions for actual glyph boxes, crop/rotation, ambiguous keys, re-analysis
  protection, rollback, OCR pending and grading. The test key fixture now uses
  explicit exercise groupings rather than relying on the unsafe global counter.

## Limits and risks

There is no full layout engine, vector-line detection, reliable column or table
reconstruction, cross-page question model, manual review/editor, verified-key
workflow, genuine scored partial answers, optional vision layer or new learner
assessment. A positioned field does not prove that the question was parsed
correctly. Old stored answer keys may already be wrongly associated; this change
does not silently rewrite or delete them. OCR produces uncertain text; word boxes
are not enough to locate blank characters. Imported OCR can miss many exercises.
No real textbook, browser interaction, real Postgres, Celery/Redis worker,
production TUS upload or selected Supabase dataset was modified or tested.

## Local verification and owner manual test

1. In an **isolated** database/storage environment, install backend requirements,
   run `python -m pytest -q` and start FastAPI with a strong local SECRET_KEY.
2. In `frontend`, run `npm ci`, `npm run build`, `npm run test:proxy` and
   `npm run test:reader`. Start Next with server-side `BACKEND_URL` set to the
   test API; run `python scripts/e2e_smoke.py` through the Next proxy. The smoke
   uses a generated PDF and calls APIs, not a browser.
3. In a separate isolated preview (not the production database), upload a
   permitted small English textbook. Compare detected exercises and answers with
   the source and check every key. Check page fit, all rotations and zoom levels,
   scroll/resize, input focus, autosave after refresh and mobile touch. Do not
   trust legacy boxes or grade scanned answers without review.
4. Try a text PDF, an image scan and a mixed PDF. Record pages with missing text,
   errors, unexpected exercise counts or wrong positions. Browser OCR is opt-in;
   it sends recognized text to Lingora, not page images to a third-party model.
5. Do not attempt production promotion until actual browser, PostgreSQL, object
   storage, background worker and real textbook tests pass and the open risks
   are addressed. Preview/production may share Supabase resources; isolate them.

## Environment and deployment checks

Required values depend on deployment: `ENV`, strong `SECRET_KEY`, `DATABASE_URL`
(persistent PostgreSQL), `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, private
`SUPABASE_SERVICE_KEY`, bucket name, `FRONTEND_URL`, `CORS_ORIGINS`; direct
browser upload additionally needs `SUPABASE_PUBLISHABLE_KEY` and its feature
flag. Frontend needs a server-side `BACKEND_URL` or Vercel Services binding.
For a persistent worker, provision Redis and set `TASK_BACKEND=celery`,
`REDIS_URL`, and run the separate Celery process with identical DB/storage
configuration. Long-lived worker reliability and retry/recovery still require
verification. Optional AI needs provider, model and server-only key; OCR needs
local Tesseract and language data. Never place secrets in frontend bundles.
Actual Production variable values and a Render deployment were not inspected.
