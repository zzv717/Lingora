# Scanned textbook work — incomplete milestone

## Production observation (read-only)

On 2026-11-11 the selected Supabase database recorded Grammarway 3 as 269
pages, 269 pages pending OCR, 0 pages marked OCR-used, 0 extracted exercises and
one fallback lesson. This describes stored analysis state, not a new OCR run;
no production content, answers, or progress were changed. The user's report
that Tesseract read pages 6–10 has not been independently reproduced here.
The private PDF was not available in this workspace. A fresh page-by-page report
requires the rights-confirmed source PDF and an isolated test environment.

## Scope of this branch

- Browser OCR sends line and word text, boxes and confidence to the existing
  authenticated page endpoint. Images stay on the user's device. Boxes are
  converted from PDF.js viewport coordinates to unrotated crop-relative PDF
  coordinates; generated PDF tests exercise crop and 0/90/180/270 rotations.
  Invalid word boxes are rejected. Low-confidence/oversize/empty page output is
  reported and left pending. Exercise box, normalized box, page index and mean
  intersecting line confidence are retained when a candidate has valid geometry.
  None of this proves the extent of an exercise or locates answer blanks.
- Reader offers read-only OCR line/word inspection and explicit loading errors,
  timeout and retry controls. These changes need actual browser testing.
- Numbered instruction candidates such as “Put the verbs…” can be detected
  beside labelled exercises; candidates remain review-required.
- A read-only per-page OCR preview returns text, candidates and the current lesson
  without saving anything, including on previously OCR-processed pages. Mixed pages
  with native text cannot be overwritten by the append endpoint. Bulk import still
  marks successfully recognized pages processed even if no exercises were found;
  versioned re-analysis and answer/progress reconciliation do not exist. Do not
  bulk import a real textbook until those risks are addressed.
- Extraction classifies pages individually as text, scanned, mixed or blank.
  This classification is not persisted; the page API reports a cautious inference
  from existing data, or unknown after OCR. This avoids requiring a production
  schema migration just to deploy. Mixed indicates text plus an image, not proof
  the image contains text. Mixed-page native text is preserved and a warning is
  emitted; a sparse native layer stays pending and can be previewed, not merged.
- OCR layout handling conservatively recognizes some simple two-column layouts;
  table-like or spanning arrangements retain input order and need human review.
  Synthetic tests do not establish accuracy on real textbooks.
- No secret, production deployment, migration, or production OCR run was performed.

## Not yet implemented or established

Mixed pages with an embedded text layer may contain undetected image-only text;
the page-type heuristic is not a substitute for region OCR and safe merging.
Robust column/table/image layout, printed page-number inference, all requested
exercise types, cross-page grouping,
real Unit/Lesson remapping, OCR blank locations, editing and verification UI,
versioned analysis, and complete review workflow remain unfinished. Browser OCR
is English only and heuristic results can be missing or incorrectly classified.
OCR-derived answer keys are not verified and OCR blank overlays are not guessed.
No real textbook, real browser, production file download or real PostgreSQL
integration test is represented by the synthetic tests.

## Required acceptance run

Use a separate test database and storage, with the real permitted PDF kept out of
Git. Test PDF indices 6–10, 16–21, 76, 126, 201 and 226–251 (clarify whether
printed page numbers or one-based PDF indices are intended), plus all 269 pages.
Compare OCR, blocks/words/confidence, reading order, detected exercise type,
normalized geometry and lesson to the actual page; report missing/incorrect
pages and manual ground truth. Test reader load, zoom, rotation and scrolling in
a real browser, and preserve/compare answers and progress before/after any future
re-analysis. Never treat synthetic test counts as textbook exercise counts.

## Latest local test results

- Backend tests use SQLite; PostgreSQL DDL checks use a mock engine.
  No production schema migration is included.
- Frontend build, TypeScript, proxy and reader utility tests passed. PDF.js
  viewport tests use a generated PDF, not a browser.
- Real local Tesseract.js OCR on a synthetic English image produced 3 lines, 18
  words with boxes, and one 2-question exercise candidate with a box. This is not
  Grammarway 3 and does not validate its layout, counts or recognition quality.
- Real Grammarway pages, browser PDF loading and live PostgreSQL/storage remain
  untested. OCR error page numbers and actual textbook counts are unknown.
