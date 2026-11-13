# AI tutor architecture audit and vision-preview milestone

## Verified starting point

- Upload currently queues `Pipeline`, which extracts every page, optionally runs
  local OCR, detects rule-based structure and may run AI enrichment. This is not
  a shallow Vision book-mapping-first pipeline. Existing production Grammarway
  structure contains one fallback lesson and 0 detected exercises. Replacing
  this pipeline now would risk existing book/lesson/answer associations.
- `Book`, `BookPage`, `Chapter`, `Lesson`, `Exercise`, `ExerciseQuestion`,
  `StudentAnswer`, `LearningProgress`, vocabulary progress and revisions already
  exist. There are no separate versioned topic maps, topic-page mappings,
  topic-analysis snapshots or seven-stage lesson sessions. Current re-analysis
  is blocked instead of migrating student work. Existing vocabulary SM-2 and
  weak-topic revision are not the requested topic-review schedule.
- The provider abstraction supports image parts for OpenAI-compatible, Anthropic
  and Gemini, but vision model capability and pricing are provider-specific. The
  production provider is unconfigured. The task layer offers an in-process thread,
  sync execution or optional Celery; these do not establish durable serverless
  processing or safe recovery. Existing content is not a vision tutor.

## Implemented on this branch: bounded, read-only previews

- `POST /books/{id}/vision-map/preview` takes an explicit selection of 1–5
  one-based PDF pages. After authentication, ownership and image-sharing consent,
  it renders only those pages, sends only those images to the configured vision
  model, validates a strict JSON schema, checks evidence page references and
  ranges, and retries malformed JSON once. It is explicitly a **partial sample**.
- A separate `vision-topic/preview` lets the user select one candidate and 1–5
  pages for theory and exercise candidates, retaining shared context and
  questions, including possible cross-page context within the selected images.
  It displays empty results and model uncertainty, not fabricated success. Both
  calls can incur provider fees and record usage; errors do not create book data.
  Page images are sent only following per-action consent. Provider errors, PDF
  loading, rendering, invalid model responses and missing configuration surface
  errors. A configured model is *not* proof it supports vision.
- Candidate checkboxes default to the first two, but are not a personalized
  recommendation. They and temporary response inputs are not persisted or graded.
  AI output is unverified, can hallucinate and has no verified answer keys.
- These small previews run synchronously and do not cache. Their inclusion does
  not change the existing upload pipeline, add a durable worker, implement topic
  selection persistence, replace exercise records, or provide a seven-stage AI
  tutor. They are a development milestone, not a finished learning platform.
- The text-only OCR AI review from the prior turn is separate; it never sends
  images. Both previous unmerged changes and existing data are preserved.

## Actual Grammarway 3 observation, not AI acceptance

PyMuPDF locally rendered selected pages through the same vision rendering helper:
PDF pages 2 and 4, 7–9, and 16–17, respectively 2, 3 and 2 images at
1385×1800 pixels. No page images were sent to a provider during this test.
Visually PDF page 2 names Grammarway 3, Jenny Dooley and Virginia Evans; PDF
page 4 shows a contents page listing 16 units and 4 revisions. The first unit
begins on printed page 6 and the next on printed page 18; a page label is not
a proven PDF index. The existing local OCR/detector results and actual visual
exercise counts are recorded in `SCANNED_TEXTBOOK_STATUS.md`.

There has been **no live AI mapping or deep analysis** and no acceptance result
for topic bounds, exercise 9, pictures, vocabulary, answers, interactive lesson
or persisted progress using Vision AI. The synthetic provider tests cannot prove
model accuracy. A live, explicitly configured vision-capable provider, cost and
consent review, isolated end-to-end environment and real-page comparisons are
still required. Provider settings in production remain untouched.

## Remaining architecture work

A versioned mapping and analysis schema with migrations and immutable provenance;
selected-topic persistence and resume; durable asynchronous worker with leases,
retries, idempotency, bounded batches, content-hash/model/prompt keyed caching,
and visible per-page errors; reliable shared-page/continuation boundaries;
review/verification and safe promotion to existing exercises; learner-profile
adaptation, all seven tutor stages, honest answer provenance and scoring; topic
review schedule with adaptive 0/1/3/7/14/30-day intervals; and browser/live
PostgreSQL/real-provider E2E tests all remain to be implemented. No production
migration was applied and no existing user data was deleted or remapped.
