# Lingora — Development Status

**Status: incomplete / not production-ready as a full interactive workbook.**

The current branch adds a dashboard lesson-start flow for existing lessons. It
shows stored exercise/word counts, respects lesson locks, recommends up to two
by existing progress (not AI), supports custom selection and navigation, and
links to the existing reader. The plan is in the URL, not a persisted session.
Scanned pages may have no detected exercises; the separate, consent-gated Vision
preview remains temporary and does not create interactive lessons. See
`docs/SCANNED_TEXTBOOK_STATUS.md` and `docs/AI_TUTOR_VISION_AUDIT.md`.
Real Grammarway 3 and Round-Up samples were locally audited; Grammarway detection
failed on all five requested pages. Browser end-to-end acceptance remains unverified.

This file replaces earlier broad completion claims that were not supported by an
end-to-end browser test. The current work is a safety and geometry milestone, not
the requested full engine rebuild. See `docs/SCANNED_TEXTBOOK_STATUS.md` for the
current scanned textbook work and its verification limits.

## Verified in this checkout

- Existing analyzed content is protected from destructive re-analysis: the API
  and pipeline reject replacement until versioned staging and migration exist.
  New first-pass content is saved in one transaction; a simulated write failure
  rolls it back. This is a safety block, **not** versioned re-analysis.
- New native-text PDF blanks are located from PyMuPDF character boxes in
  unrotated, crop-relative points. Missing geometry is shown in a card instead of
  being guessed. Legacy proportional boxes are not displayed as PDF overlays.
- A limited instruction-without-heading pattern is recognized and flagged for
  review. Explicit exercise references are used to associate answer keys when
  unambiguous; ambiguous repeated numbers remain unverified. Parsed keys have
  not been human-verified. Old persisted answer-key associations are not audited.
- Local Tesseract extraction, when installed, records word and line geometry and
  confidence. Short or low-confidence OCR remains pending; OCR answer keys and
  OCR blank positions are not treated as verified. Browser OCR remains opt-in.
- Detected matching pairs are not automatically graded as correct just because
  of their inferred layout. Overlay edits are queued for autosave in the UI;
  this UI path still needs browser verification.
- Automated backend suite: **133 tests passed locally** (SQLite, mock PostgreSQL
  DDL test; no real PostgreSQL integration test). This includes generated-text PDF
  upload, lesson counts, exercise access and saved-answer API flow, not a browser
  E2E or real textbook. Frontend production build, proxy, reader and lesson-plan
  unit tests passed locally. JSDOM smoke tests with mocked API responses exercised
  selection and two temporary Vision previews; these are not a real browser or
  provider integration test.

## Experimental text-only AI OCR preview

A consent-based, page-local AI review is implemented on this branch, but live AI
provider configuration and real-book AI acceptance remain untested. No page images
are sent. See `docs/SCANNED_TEXTBOOK_STATUS.md` for limitations.

## Vision AI tutor milestone

See `docs/AI_TUTOR_VISION_AUDIT.md`. A bounded consent-based Vision mapping and
topic preview has been added, not a full mapping-first pipeline or tutor. Real
AI/provider acceptance and durable, persistent topic analysis are not complete.

## Important remaining work

- Browser and real-device E2E for overlay position, edits, focus, zoom, rotation,
  scroll and resume; scanned/mixed and real textbook workflows remain unverified.
- Versioned analysis staging, stable question mapping, manual corrections and
  migration of unmappable student work; existing books cannot be re-analyzed.
- General multi-column, tables, diagrams, vector-drawn blanks, multiple-page
  exercises, headingless numbered content, reading and matching reconstruction.
- Browser OCR word boxes/rotation have synthetic viewport tests but need actual
  browser and real-page verification. OCR blank detection, Uzbek OCR data, scan
  quality evaluation, and complete page-by-page reporting remain unfinished.
- Review interface, human verification of answer keys, partial scoring, and
  auditing previously parsed answer keys. Some historical `key` associations
  can be incorrect and need review before being trusted.
- Placement assessment and level-adapted vocabulary are not implemented.
- Vision page understanding is only an opt-in, temporary preview, not a complete
  mapping/analysis pipeline; no real provider or scanned-book acceptance has been
  demonstrated. External image processing requires consent and cost/privacy review.
- Durable job processing, monitoring and recovery, production storage verification,
  real PostgreSQL integration, deployment environment isolation and security
  dependency upgrades. `npm ci` reported 15 vulnerabilities (2 critical).

## Deployment

This branch does not require a schema migration; page-type inference and lesson
plans are not persisted. Authorized production direct-upload configuration was
deployed with a 50 MiB limit, but authenticated uploads and near-limit TUS remain
untested. This dashboard update has not yet been deployed. See `docs/WORKBOOK_AUDIT.md`,
`docs/SCANNED_TEXTBOOK_STATUS.md` and `docs/DEPLOYMENT.md` before deployment.

## Annotated sample and AI check

See `docs/SCANNED_TEXTBOOK_STATUS.md`: the marked screenshot OCR returned zero
review regions in a local test, while the inspired layout regression is synthetic.
Production reported AI unconfigured; the OCR import is not AI document
understanding. The temporary review inputs are not saved or graded. AI guesses
are not promoted to deterministic grading keys on this branch.
