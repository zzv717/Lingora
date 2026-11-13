# Lingora — Development Status

**Status: incomplete / not production-ready as a full interactive workbook.**

This file replaces earlier broad completion claims that were not supported by an
end-to-end browser test. The current work is a safety and geometry milestone, not
the requested full engine rebuild.

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
- Automated backend suite: **96 tests passed locally** (SQLite, mock PostgreSQL
  DDL test; no real PostgreSQL integration test). Production frontend build,
  proxy test, and pure reader geometry tests passed locally. Generated PDF API
  smoke through a local Next proxy and local FastAPI: 13 checks passed; this was
  not browser E2E, real storage, or a real textbook.

## Important remaining work

- Browser and real-device E2E for overlay position, edits, focus, zoom, rotation,
  scroll and resume; scanned/mixed and real textbook workflows remain unverified.
- Versioned analysis staging, stable question mapping, manual corrections and
  migration of unmappable student work; existing books cannot be re-analyzed.
- General multi-column, tables, diagrams, vector-drawn blanks, multiple-page
  exercises, headingless numbered content, reading and matching reconstruction.
- Browser OCR word boxes/rotation, OCR blank detection, Uzbek OCR data, scan
  quality evaluation, and accurate page-by-page completion reporting.
- Review interface, human verification of answer keys, partial scoring, and
  auditing previously parsed answer keys. Some historical `key` associations
  can be incorrect and need review before being trusted.
- Placement assessment and level-adapted vocabulary are not implemented.
- Optional vision page understanding is not implemented; no page images are sent
  to an AI service by this milestone. Do not enable external image processing
  without explicit consent and cost/privacy review.
- Durable job processing, monitoring and recovery, production storage verification,
  real PostgreSQL integration, deployment environment isolation and security
  dependency upgrades. `npm ci` reported 15 vulnerabilities (2 critical).

## Deployment

No database migration is included. Vercel deployment metadata reported current
main `ef00a52` as READY and selected Supabase DB/storage services as healthy;
this is not proof that production credentials, upload, OCR, workers, or a real
user workflow work. Production was not changed by this milestone. See
`docs/WORKBOOK_AUDIT.md` and `docs/DEPLOYMENT.md` before any deployment.
