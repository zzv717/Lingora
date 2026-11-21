# Vocabulary extraction

How a book's words reach the **Lug'at** screen, what each layer guarantees, and how to
diagnose a book that stays empty. Nothing here is specific to one publisher's layout: the
rule detector describes a *shape*, the vision path reads a *page image*, and both write to
the same tables.

## Two paths, one table

| Path | Input | When it runs | Cost |
| --- | --- | --- | --- |
| Rule detector (`services/structure_detector.py`) | PDF text layer | automatically, in the analyse pipeline | free |
| Vision extraction (`services/ai/vision_vocabulary.py`) | rendered page image | user presses «Lug'atni o'qish» | one model call per page |

The rule detector runs first and is enough for a born-digital book. The vision path is the
fallback for a book whose text layer is a scan (or whose layout the rules do not describe),
and it is the only path that can read a photocopied page. Both write `vocabulary_words`
rows; the source is recorded in `source` (`"book"` for the rules, `"vision"` for the model).

## What the rule detector recovers

Per entry it stores the headword, part of speech, definition, example, page number, the
headword's bounding box and, when the illustration can be located geometrically, its crop
box. It reads:

* the headword grammars `headword [pronunciation] pos` with or without the leading bullet
  glyph, a damaged bracket (`angry [sengro adj.`), a scanned `y`/`u` for `v`, and
  letter-spaced text (`p u b lis h`);
* the definition as the sentence between two headwords, skipping bullet lines, stray
  glyph runs and illustration fragments (`_looks_like_sentence`);
* the example as the bullet-marked line (`»`, `-»`, `►`), falling back to the indented
  column.

A headword the book's own index does not recognise, and whose two possible readings
disagree, is **dropped rather than guessed**. A book-wide summary is logged at
`lingora.structure`:

```
structure: 196 pages, 600 words, 30 lessons; word-list-shaped pages: [9, 10, 15, ...]
```

If the log says “word-list pages but only N words parsed”, the headword grammar does not
match the book: use the vision path instead of editing regexes for one book.

## Automatic fallback: the user never presses a button

A text layer is not proof that the words are recoverable. When the pipeline measures the
text parser's result (`books.text_vocabulary_count`) and finds fewer than
`VOCAB_VISION_FALLBACK_MIN_ENTRIES` entries (default 10), it reads up to
`VOCAB_VISION_FALLBACK_PAGES` pages (default 24) with the vision model **inside the same
analysis job** and writes the result to the same table. Properties:

* nothing is replaced, nothing is translated, existing progress is untouched;
* pages already read (`book_pages.vocab_scanned_at`) are skipped, so a re-analysis does not
  pay twice;
* a vision failure never fails the upload — the book still becomes `ready`;
* the reason is written to `books.vocabulary_note_uz` and shown on the Lug'at screen, so an
  incomplete Lug'at explains itself instead of saying "no vocabulary found";
* `0` disables the fallback.

## What the vision path guarantees

* Strict output contract
  `{page, unit, entries: [{word, part_of_speech, definition, example, translation_uz?}]}`
  plus `is_word_list`, `heading`, `warnings`. The page image is rendered server-side and
  sent with a **strict JSON schema** (`VOCABULARY_JSON_SCHEMA` → the provider's
  `json_schema` mode), so the model cannot answer with prose or a renamed field. Invalid
  JSON is repaired once, then rejected — no half-parsed entry is stored.
* `translation_uz` is stored **only when the page prints it**. A model-supplied translation
  is discarded, so a row is never a fabrication; such rows keep `needs_translation = true`
  and are excluded from tests until a human translates them.
* Normalisation: pronunciation, POS and punctuation stripped from the word; case folded;
  duplicates collapsed; junk (numbers, sentence-length “words”) rejected; at most 40
  entries per page.
* Existing rows are never replaced or deleted, and progress is untouched: a term already
  present is skipped.
* Each analysed page is stamped in `book_pages.vocab_scanned_at`, so a page that turned
  out not to be a word list is not paid for twice.

## Serverless execution and failure handling

One request cannot scan 196 pages. `POST /books/{id}/vision-vocabulary/batch` reads at most
`VISION_VOCABULARY_BATCH` (10) pages, reports each page's status and returns
`remaining_pages`; the client loops, and stops the loop as soon as an error is one that
would repeat (quota, provider, configuration). A single bad page never loses the batch.

Three failure modes are handled explicitly, because each one loses already-paid work:

| Failure | Handling |
| --- | --- |
| Provider timeout / 5xx / 429 | retried inside `analyse_page` with `AI_MAX_RETRIES` and backoff; a 4xx configuration error is raised immediately (it would fail on every page) |
| Function timeout | the batch watches the clock (`VOCAB_VISION_BATCH_SECONDS`, default 45) and stops **starting** new pages; the rest come back as `deferred` with `remaining_pages`, and the client asks again |
| Dropped DB connection (SSL reset, pooler recycle) | `pool_pre_ping` verifies a connection before use, `pool_recycle` retires idle ones, and a write that fails with a connection error is retried on a fresh connection — the model answer is reused, not re-bought |

| Endpoint | Purpose |
| --- | --- |
| `GET  /books/{id}/vision-vocabulary/pending` | pages still to read, batch size, batch count |
| `POST /books/{id}/vision-vocabulary/pages/{n}` | read one page (preview or save) |
| `POST /books/{id}/vision-vocabulary/batch` | read the next ≤10 pages |
| `GET  /books/{id}/vocabulary/units` | stored words grouped by unit, orphans last |

## Database

`pool_pre_ping=True`, `pool_recycle=DB_POOL_RECYCLE` (300 s) and a bounded pool keep the
app's pooled connection to a pooler healthy. Schema work uses `DATABASE_MIGRATION_URL`
when set — a **direct** (non-pooler) connection — because adding a column or taking an
advisory lock through a transaction pooler is unreliable. `ensure_schema()` retries on
`OperationalError` (4 attempts) and never aborts startup.

Schema changes in this task: `book_pages.vocab_scanned_at` (Alembic `d8e2f5a1c734`, also
added tolerantly at startup).

## Environment variables

| Variable | Meaning |
| --- | --- |
| `AI_PROVIDER`, `AI_API_KEY`, `AI_BASE_URL` | the provider used for every AI call |
| `AI_VISION_MODEL` | model that reads page images (works without `AI_MODEL`) |
| `VOCAB_VISION_FALLBACK_MIN_ENTRIES` | text entries below which vision runs automatically (10; 0 = off) |
| `VOCAB_VISION_FALLBACK_PAGES` | pages the automatic pass may read (24) |
| `VOCAB_VISION_BATCH_SECONDS` | wall-clock budget of one batch request (45) |
| `DATABASE_URL` | pooled app connection |
| `DATABASE_MIGRATION_URL` | direct connection for Alembic/startup DDL (recommended) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` | pool sizing (5 / 5 / 300) |

Without a provider key the vision buttons return `AI_NOT_CONFIGURED` and say so in the UI;
the rule detector keeps working, so a text-layer book still fills the Lug'at.

## Verifying by hand

```bash
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "backend")
import fitz
from app.services.pdf_extractor import extract_document
from app.services.structure_detector import detect_structure
doc = fitz.open("samples/essential.pdf")
pages, _ = extract_document(doc, start=0.0, end=100.0,
                            source_bytes=open("samples/essential.pdf", "rb").read())
st = detect_structure(pages)
print(len(st.vocabulary), "words;", sum(1 for w in st.vocabulary if not w["part_of_speech"]), "without POS")
PY
```

Reference result on `4000 Essential English Words, Book 1` (196 pages): **600 words, 30
units**, 10 entries on each of pages 9, 10, 15, 16, 21, every one with a definition and an
example; the remaining entries without a part of speech are pages where the scan destroyed
the label entirely (printed as `*`), and the vision path fills those in.
