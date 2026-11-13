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
  with native text cannot be overwritten by the append endpoint. In the current
  branch, pages without a detected question are also left pending; this includes
  legitimate theory pages. An OCR page with at least one recognized exercise can
  still be marked processed despite missing other exercises. Versioned re-analysis
  and answer/progress reconciliation do not exist. Do not bulk import a real
  textbook until those risks are addressed.
- Extraction classifies pages individually as text, scanned, mixed or blank.
  This classification is not persisted; the page API reports a cautious inference
  from existing data, or unknown after OCR. This avoids requiring a production
  schema migration just to deploy. Mixed indicates text plus an image, not proof
  the image contains text. Mixed-page native text is preserved and a warning is
  emitted; a sparse native layer stays pending and can be previewed, not merged.
- OCR layout handling conservatively recognizes some simple two-column layouts;
  table-like or spanning arrangements retain input order and need human review.
  Synthetic tests do not establish accuracy on real textbooks.
- No secret, production deployment, migration, or production OCR run was performed by the current branch.

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

## Geometry-based review milestone (current branch)

A separate read-only review path proposes regions from OCR numbers, instruction
words and spatial proximity. It retains observed line boxes and marks every region
unverified. Image boxes are reported only as overlapping evidence, and a full-page
scan is never presented as a detected picture. This is not a vision model, table
reconstruction, a universal exercise parser, or a trustworthy exercise count.
Regions can include theoretical text or cross columns; inline cloze blanks and
cross-page continuations are not reconstructed. It does not create or modify any
exercise, answer or progress. Tests of region grouping and a ten-item exercise
use synthetic OCR lines, not Grammarway 3. The local bulk-import guard prevents
marking pages with no recognized question as done, but does not make partially
recognized page imports safe to reconcile. The real PDF remains necessary for
page-by-page acceptance, and the feature has not been tested in a real browser.

## Annotated sample and AI audit

The supplied annotated image shows the Too/Enough explanation on the left and
exercises 8 (paired question/answer), 9 (dialogue completion), and 10 (sentence
rewriting) on the right. They are not the earlier requested pages 7–9 and 16–17.
We did not treat the ink colours as document content or assume all pages have
this layout. A local Tesseract.js run on the 400×509 marked screenshot, upscaled
4× for this experiment, produced 50 lines but no region candidates: the exercise
numbers/instructions were not reliably recognized. This is a real screenshot
OCR failure, not evidence that the original PDF will fail or pass. No page image
was sent to an external model.

The synthetic regression inspired by this layout checks provisional separation
of right-hand numbered instructions, examples and dialogue continuations from
left-hand theory. It deliberately does not establish real OCR accuracy. A
review panel offers temporary answer fields, explicitly unsaved and ungraded;
it is not the production interactive exercise conversion. Tables, pictures,
inline blanks, unmarked task boundaries, mixed OCR lines and cross-page groups
remain unsolved.

Production `/backend/ready` reported `ai_configured: false` during this audit.
The setting only checks provider, model and key presence; it is not a live
provider connectivity test. The browser OCR import does not call an AI document
understanding model even if one is configured. Existing AI enrichment is for
vocabulary/grammar notes, and AI grading works on extracted text rather than
page images. This branch also prevents AI-generated or other unverified answers
from being scored as verified keys; without an available AI evaluation, their
responses remain ungraded. No provider was configured, paid service invoked,
or production database mutated by this investigation.

## Real-book local audit, 2026-11-11 (supersedes earlier source-availability statements)

The permitted Grammarway 3 and Round-Up 1 PDFs were obtained from the user's
Drive and processed locally; sampled pages have no text layer. No page images
were sent to AI. Each listed number is a **one-based PDF index**, matching the
printed page labels for Grammarway. Tesseract.js English OCR was run in Node on
rendered full pages (Grammarway 1846×2400; Round-Up about 1030×1530). Its line
boxes were scaled to PDF points and passed through the actual `_prepare_ocr` and
`visual_candidates` functions. This approximates browser OCR but is not a
browser E2E test; it did not submit or save the production book.

| Book, PDF page | Visually observed activities | Import detector output | Review candidates | Layout |
|---|---|---|---|---|
| Grammarway 7 | 5 (1–5) | 0 | 0 | ambiguous |
| Grammarway 8 | 5 (6–10) | 0 | 0 | ambiguous |
| Grammarway 9 | 1 (11) | 0 | 0 | original |
| Grammarway 16 | 4 (27–30) | 0 | 0 | ambiguous |
| Grammarway 17 | 2 numbered (31–32) plus oral and writing | 0 | 0 | ambiguous |
| Round-Up 7 | not established | 0 | 0 | original |
| Round-Up 8 | not established | 0 | 0 | original |
| Round-Up 16 | at least 3 visually observed | 1 false `Exercise 0`, 11 fill-blank questions | 2 false `0` | original |

The real page 8 exercise 9 contains one ten-blank passage; neither pipeline
recognized it. Grouping, type and checking therefore fail acceptance, rather
than producing ten separate exercises. The full-page OCR often merges columns;
circled exercise numbers are frequently missed or misread. Three-column lists
can also become one OCR line. The visual ground truth counts are not detector
results and Round-Up was sampled, not fully audited.

A separate local experiment OCR'd left and right halves at the same scale. It
produced cleaner instructions on some pages, but the actual detector still
returned no useful grouping: 0 exercises on Grammarway 7–9 and 16; on 17 it
returned two unnumbered fill-blank candidates, one with one question and one
with none. The visual review returned zero candidates on all five. Therefore a
preview-only manual two-column option has been added, with a warning: midpoint
splitting can cut spanning text, tables and illustrations and is not a general
layout solution. It is never used by bulk import. A separate offline color
experiment found most green exercise-number markers on these five pages, but it
is book-style dependent, missed/misclassified some markers, and is not shipped.

The import API now rejects detected ambiguous layouts and `Exercise 0`, leaving
the page pending; this is a conservative guard, **not** proof other imports
are complete. It also defers legitimate pages. No versioned reanalysis or safe
reconciliation exists, so do not bulk-import real books. Neither a complete
interactive conversion nor real-browser, live PostgreSQL, live authenticated
upload or near-50 MiB TUS E2E has been demonstrated.

Production settings were authorized separately: 50 MiB private bucket cap,
public Storage key and direct upload flag; deployment `dpl_HuwHA5vvXXDV92c1HXfa8NWSP9sd`
is READY/PROMOTED with production alias assigned. This branch's UI now requests
server limits instead of advertising a fixed 100 MB, and explains 413 errors;
these code changes are not deployed. Real authenticated direct TUS remains
untested. No book content, answers or progress was altered during this audit.

## Text-only AI OCR review (unmerged branch experiment)

The authenticated page preview now offers an additional opt-in, single-page AI
review. It sends the selected OCR line text, line confidence and PDF point
coordinates to the configured AI provider, but never PDF/page images. It does
not depend on the heuristic finding an exercise first. The model is instructed
to cite line IDs, retain shared passage context, distinguish theory from
activities and avoid invented keys; JSON and references are validated. Valid
references do not guarantee the model's text or grouping is correct. The user
can inspect referenced OCR lines and temporary inputs, compare with the original
PDF, and see uncertainty. No page, exercise, answer or progress is persisted;
an AI usage event is recorded. Bad responses and unavailable providers show errors
instead of silently falling back. It is not bulk OCR, a grading or verified
answer-key pipeline, and it only sees one page.

The AI tests use a mocked provider; the 10-question example is synthetic. They
check text-only messages, consent, ownership, quotas, invalid output/references,
and preservation of book data. The current production `AI_PROVIDER`, `AI_MODEL`
and `AI_API_KEY` are not configured; preview-only variables exist, but their
validity is not established. No real model call or AI detection result on
Grammarway or Round-Up is established. A real provider and an isolated end-to-end
comparison against actual page 8 exercise 9 and the other sampled pages are still
required before claiming effectiveness. Enabling the existing AI settings for
production may also enable other AI features and incur provider charges; do not
copy preview settings without considering that scope.
