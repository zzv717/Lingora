"""Deterministic textbook structure detection (rule-based core of the AI Book Analyzer).

Finds: chapters/units, lessons, exercises (8 types), questions, multiple-choice options,
matching pairs, vocabulary lists, answer keys — while preserving page numbers and
bounding boxes. AI enrichment (optional) refines this result afterwards; it never
replaces it silently.

Design rules:
- Never invent content: only structures actually observed in the text.
- Anything ambiguous is kept but flagged with needs_review / warnings.
"""
import difflib
import re
from dataclasses import dataclass, field
from typing import Any

BLANK_RE = re.compile(r"_{2,}|\.{4,}|\[\s*\]|…{1,}")
NUM_ITEM_RE = re.compile(r"^(\d{1,3})\s*[\.\)\:]\s*(.+)$")
OPTION_RE = re.compile(r"^\(?([A-Za-z])[\)\.]\s+(.+)$")
EXERCISE_RE = re.compile(
    r"^(exercise|ex\.\s?|task|mashq|topshiriq|practice|activity)\s*\.?\s*(\d+)?\s*[\.:—–-]?\s*(.*)$",
    re.IGNORECASE,
)
CHAPTER_RE = re.compile(
    r"^(unit|chapter|bob|bo['`’]bob|modul|module|qism|part)\s+([0-9IVXLC]+)\b[\s\.:—–-]*(.*)$",
    re.IGNORECASE,
)
LESSON_RE = re.compile(
    r"^(lesson|dars)\s*\d*|^(grammar|reading|writing|speaking|listening)\b|^(vocabulary|word)\s*\d+|"
    r"^(review|check\s+your\s+(progress|knowledge|answers?)|test\s+yourself|progress\s+check)\b[\s\.:—–-]*(.*)$",
    re.IGNORECASE,
)
INSTRUCTION_RE = re.compile(
    r"^(?:complete|fill\s+in|choose|match|read\s+(?:and\s+answer|the\s+(?:text|passage|story))|"
    r"write\s+about|rewrite|put\s+the\s+(?:words|verbs|sentences)|translate|"
    r"true\s+or\s+false|answer\s+the\s+questions|correct\s+the\s+(?:mistakes|errors|sentences)|"
    r"use\s+the\s+word\s+given|form\s+(?:a|the)\s+word|word\s+formation)\b", re.IGNORECASE)
NUMBERED_INSTRUCTION_RE = re.compile(r"^(\d{1,3})\s*[.):]?\s+(.+)$")
KEY_HEADER_RE = re.compile(r"^(answer\s*keys?|keys?|answers?|javoblar)\b[\s:—–-]*$", re.IGNORECASE)
VOCAB_PAIR_RE = re.compile(r"^([A-Za-z][A-Za-z'’\-\. ]{1,48}?)\s*(?:[—–·•]| - |\t|=|\s{3,}|\|)\s*(.{1,120})$")
DASH_PAIR_RE = re.compile(r"^(.{1,60}?)\s*(?:[—–·•]| - )\s*(.{1,120})$")
TRUE_FALSE_HINT = re.compile(r"true\s*(/|or|\)\s*)?\s*false|to['`’]g['`’]ri\s*/?\s*noto", re.IGNORECASE)
TRANSLATE_HINT = re.compile(r"translat|tarjima\s*(qil|king)?", re.IGNORECASE)
MATCH_HINT = re.compile(r"match|moslashtir|juftlang|connect", re.IGNORECASE)
WRITE_HINT = re.compile(r"write\s+(a|an|about|your|the)?\s*(essay|composition|paragraph|letter|story|about)|yozing", re.IGNORECASE)
ORDER_HINT = re.compile(r"(put|arrange).*(words|order)|so['`’]zlar.*joyla|gap\s*(tuz|qur)", re.IGNORECASE)
READ_HINT = re.compile(r"read\s+(the\s+)?(text|passage|story|dialog)|matnni\s*o['`’]qi", re.IGNORECASE)

TOPIC_PATTERNS = [
    ("Present Simple", r"present\s+simple|present\s+indefinite"),
    ("Present Continuous", r"present\s+continuous|progressive"),
    ("Past Simple", r"past\s+simple|past\s+indefinite"),
    ("Present Perfect", r"present\s+perfect"),
    ("Past Continuous", r"past\s+continuous"),
    ("Future Simple", r"future\s+simple|will\b.*\bfuture|future\s+indefinite"),
    ("Passive Voice", r"passive"),
    ("Reported Speech", r"reported\s+speech|indirect\s+speech"),
    ("Articles", r"\barticles?\b|a/an/the"),
    ("Plural nouns", r"plural"),
    ("Comparatives", r"comparative|superlative|daraja"),
    ("Modal verbs", r"modal\s*(verbs?)?|can/could/must"),
    ("Prepositions", r"preposition|predlog"),
    ("Conditionals", r"conditional|shart\s+mayli"),
    ("Irregular verbs", r"irregular\s+verbs?"),
    ("Question forms", r"questions?\s+form|special\s+questions|tag\s+questions"),
    ("Pronouns", r"pronoun"),
    ("There is/are", r"there\s+is/are|there\s+is\s*,?\s*there\s+are"),
    ("Gerund / Infinitive", r"gerund|infinitive"),
    ("Phrasal verbs", r"phrasal\s+verbs?"),
]


@dataclass
class DetectedQuestion:
    number: str
    prompt: str
    options: list[dict[str, Any]] = field(default_factory=list)
    blanks: list[dict[str, Any]] = field(default_factory=list)
    matching_pairs: list[dict[str, Any]] = field(default_factory=list)
    bbox: list[float] | None = None
    needs_review: bool = False


@dataclass
class DetectedExercise:
    title: str
    ref: str
    instructions: str
    page_number: int
    exercise_type: str
    questions: list[DetectedQuestion] = field(default_factory=list)
    bbox: list[float] | None = None
    topic: str = ""
    needs_review: bool = False


@dataclass
class DetectedStructure:
    chapters: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[dict[str, Any]] = field(default_factory=list)
    exercises: list[DetectedExercise] = field(default_factory=list)
    vocabulary: list[dict[str, Any]] = field(default_factory=list)
    # Word + visual block pairs found on dictionary pages. The picture is described
    # as a normalized box so the client can crop it from the original PDF itself.
    pictures: list[dict[str, Any]] = field(default_factory=list)
    # "textbook" (grammar units with exercises) or "dictionary" (word-list pages with
    # definitions and illustrations). The layout changes how units are grouped.
    layout: str = "textbook"
    answer_key_entries: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def guess_topic(text: str) -> str:
    low = text.lower()
    for topic, pat in TOPIC_PATTERNS:
        if re.search(pat, low):
            return topic
    return ""


def _blank_bboxes(line: dict[str, Any], page_width: float) -> list[list[float] | None]:
    """Union real glyph boxes only; never guess from line width or missing OCR geometry."""
    text = line["text"]
    chars = line.get("chars") or []
    boxes = []
    for match in BLANK_RE.finditer(text):
        glyphs = chars[match.start():match.end()] if len(chars) == len(text) else []
        if len(glyphs) != len(match.group()) or any(not box for box in glyphs):
            boxes.append(None)
        else:
            boxes.append(_union_bbox(glyphs))
    return boxes


def _classify_exercise(instruction: str, items: list[dict[str, Any]]) -> str:
    has_options = any(it["options"] for it in items)
    has_blanks = any(it["blanks"] for it in items)
    if MATCH_HINT.search(instruction) and (len(items) >= 3):
        return "matching"
    if has_options:
        return "multiple_choice"
    if TRUE_FALSE_HINT.search(instruction) or (items and all(
            re.search(r"\b(true|false|to['`’]g['`’]ri|noto['`’]g['`’]ri)\b", it["prompt"], re.IGNORECASE)
            for it in items)):
        return "true_false"
    if TRANSLATE_HINT.search(instruction):
        return "translation"
    # Specific instructions are candidates, not evidence of a verified key.
    if re.search(r"\b(?:rewrite|rephrase|transform)\b", instruction, re.I):
        return "sentence_transformation"
    if re.search(r"\b(?:word formation|form (?:a |the )?(?:correct )?word|use the word given)\b", instruction, re.I):
        return "word_formation"
    if re.search(r"\b(?:correct|find)\s+the\s+(?:mistakes|errors|sentences)\b", instruction, re.I):
        return "error_correction"
    if re.search(r"\banswer\s+the\s+questions\b", instruction, re.I) and not READ_HINT.search(instruction):
        return "short_answer"
    if WRITE_HINT.search(instruction) and not has_blanks and len(items) <= 2:
        return "writing"
    if ORDER_HINT.search(instruction):
        return "sentence_construction"
    if READ_HINT.search(instruction) or any(it.get("passage") for it in items):
        return "reading_comprehension"
    if has_blanks:
        return "fill_blank"
    if not items and WRITE_HINT.search(instruction):
        return "writing"
    return "fill_blank" if has_blanks else "fill_blank"


def _parse_exercise_block(header: dict[str, Any], body_lines: list[dict[str, Any]],
                          page_number: int, structure: DetectedStructure) -> DetectedExercise:
    m = EXERCISE_RE.match(header["text"])
    numbered = NUMBERED_INSTRUCTION_RE.match(header["text"].strip()) if not m else None
    num = (m.group(2) or "").strip() if m else (numbered.group(1) if numbered else "")
    instr = (m.group(3) or "").strip() if m else (numbered.group(2).strip() if numbered else header["text"].strip())
    ref = f"Exercise {num}" if num else f"Exercise (p.{page_number},{header.get('seq', '?')})"

    questions: list[DetectedQuestion] = []
    current: dict[str, Any] | None = None
    instruction_parts = [instr] if instr else []

    for line in body_lines:
        text = line["text"]
        nm = NUM_ITEM_RE.match(text)
        om = OPTION_RE.match(text)
        if nm and not om:
            if current:
                questions.append(_finish_question(current))
            current = {
                "number": nm.group(1), "prompt": nm.group(2).strip(),
                "bbox": line["bbox"], "page": page_number,
                "chars": (line.get("chars") or [None] * len(text))[nm.start(2):nm.end(2)],
            }
            continue
        if om and current is not None:
            current.setdefault("options", []).append(
                {"letter": om.group(1).upper(), "text": om.group(2).strip()}
            )
            continue
        # continuation text (instruction or wrapped prompt)
        if current is not None and (len(text) < 3 or NUM_ITEM_RE.match(text) is None) and not EXERCISE_RE.match(text):
            if len(text.split()) <= 14 and not current["prompt"]:
                instruction_parts.append(text)
            else:
                current["prompt"] = (current["prompt"] + " " + text).strip()
                current["chars"] += [None] + (line.get("chars") or [None] * len(text))
        else:
            instruction_parts.append(text)

    if current:
        questions.append(_finish_question(current))

    exercise_type = _classify_exercise(" ".join(instruction_parts), [
        {"options": q.options, "blanks": q.blanks, "prompt": q.prompt} for q in questions])

    all_bboxes = [header["bbox"]] + [q.bbox for q in questions if q.bbox]
    bbox = _union_bbox(all_bboxes)
    ex = DetectedExercise(
        title=ref, ref=ref, instructions=" ".join(instruction_parts).strip()[:1000],
        page_number=page_number, exercise_type=exercise_type, questions=questions, bbox=bbox,
        topic=guess_topic(" ".join(instruction_parts)),
        needs_review=(not m) or len(questions) == 0 or any(q.needs_review for q in questions),
    )
    if not questions:
        structure.warnings.append({
            "page": page_number, "code": "EXERCISE_NO_QUESTIONS",
            "message_uz": f"{ref} (sahifa {page_number}): topshiriq matni topildi, lekin savollar ajratib olinmadi.",
        })
    if any(q.needs_review for q in questions):
        structure.warnings.append({"page": page_number, "code": "BLANK_LOCATION_UNKNOWN",
                                   "message_uz": "Ba'zi bo'sh joylar joylashuvi aniqlanmadi; javobni kartada kiriting."})
    return ex


def _finish_question(cur: dict[str, Any]) -> DetectedQuestion:
    prompt = cur["prompt"]
    blanks = []
    matches = list(BLANK_RE.finditer(prompt))
    # Compute all blank boxes once; recomputing per match was O(blanks^2).
    boxes = _blank_bboxes({"text": prompt, "chars": cur.get("chars", [])}, 0) if matches else []
    for i, m in enumerate(matches, 1):
        bbox = boxes[i - 1] if i - 1 < len(boxes) else None
        blanks.append({"id": f"b{i}", "bbox": bbox, "geometry": "native_chars" if bbox else "unlocated"})
    # build display prompt with {bN} placeholders
    display = ""
    last = 0
    for i, m in enumerate(matches, 1):
        display += prompt[last:m.start()] + f"{{b{i}}}"
        last = m.end()
    display += prompt[last:]
    # matching pairs via dash
    pairs = []
    dm = DASH_PAIR_RE.match(prompt)
    if dm and not matches:
        pairs = [{"left": dm.group(1).strip(), "right": dm.group(2).strip()}]
    return DetectedQuestion(
        number=cur["number"], prompt=display if matches else prompt,
        options=cur.get("options", []), blanks=blanks, matching_pairs=pairs, bbox=cur["bbox"],
        needs_review=any(not b["bbox"] for b in blanks),
    )


def _union_bbox(bboxes: list[list[float]]) -> list[float] | None:
    xs0 = [b[0] for b in bboxes if b]
    ys0 = [b[1] for b in bboxes if b]
    xs1 = [b[2] for b in bboxes if b]
    ys1 = [b[3] for b in bboxes if b]
    if not xs0:
        return None
    return [round(min(xs0), 2), round(min(ys0), 2), round(max(xs1), 2), round(max(ys1), 2)]


def _detect_vocabulary(pages: list[dict[str, Any]], structure: DetectedStructure,
                       occupied_pages: set[int]) -> None:
    for page in pages:
        lines = page["lines"]
        run: list[dict[str, Any]] = []
        runs: list[list[dict[str, Any]]] = []
        for line in lines:
            vm = VOCAB_PAIR_RE.match(line["text"])
            if vm and not EXERCISE_RE.match(line["text"]) and not NUM_ITEM_RE.match(line["text"]):
                run.append({"line": line, "term": vm.group(1).strip(), "translation": vm.group(2).strip()})
            else:
                if len(run) >= 3:
                    runs.append(run)
                run = []
        if len(run) >= 3:
            runs.append(run)
        for run in runs:
            for item in run:
                structure.vocabulary.append({
                    "term": item["term"], "translation_uz": item["translation"],
                    "definition_en": "", "example_sentence": "",
                    "page_number": page["page_number"],
                    "needs_translation": not item["translation"].strip(),
                })


# Dictionary-style entry head: "afraid [afreid] adj.", "agree v.", "bottom n."
# The part of speech must close the line; a definition on the same line is not
# expected on picture-dictionary pages and made ordinary sentences match.
_POS_LABELS = {"n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb",
               "prep": "preposition", "pron": "pronoun", "conj": "conjunction",
               "num": "numeral", "art": "article", "interj": "interjection", "phr": "phrase"}
VOCAB_SKIP_RE = re.compile(
    r"^(answer|unit|lesson|about|target|page|contents|introduction|photo|isbn)\b", re.IGNORECASE)
_PLAIN_WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'’\-]*$")
# A pronunciation token: bracketed, slashed, or carrying a digit/IPA/stress glyph.
_PRON_RE = re.compile(r"[\[\]/:ˈˌ0-9əʃʒθðŋæɑɒɛɜɪʊʌ*]")
# "beach ......... 57" — an index entry with a dotted leader, never a word-list entry.
_INDEX_LINE_RE = re.compile(r"\.{4,}\s*\d{1,3}\s*$")


def _clean_term(term: str) -> str:
    """Normalise the book's mixed casing; never invent letters."""
    words = [w for w in re.split(r"\s+", term.strip()) if w]
    return " ".join(word.lower() if sum(ch.isupper() for ch in word) > 1 else word
                    for word in words[:3]).strip(" -—–·•'’")[:255]


def _collapse_letter_spacing(text: str, drop_bullet: bool = True) -> str:
    """Glyph boxes sometimes split one word into pieces: "l o t" / "b e n e f it" / "C le r k".

    A stretch of very short tokens holding at least two single letters is one word —
    that is how this PDF breaks spelled-out headwords. Ordinary prose has no such
    stretches, and "a lot" / "one million" keep their space.
    """
    tokens = text.split()
    # The book's bullet glyph ("r afraid", "r- position") is not part of the headword.
    if drop_bullet and len(tokens) > 1 and len(re.sub(r"[^A-Za-z]", "", tokens[0])) <= 1 \
            and tokens[0].lower() not in ("a", "i"):
        tokens = tokens[1:]
    out: list[str] = []
    index = 0
    while index < len(tokens):
        end = index
        while end < len(tokens) and len(tokens[end]) <= 4 and _PLAIN_WORD_RE.match(tokens[end]):
            end += 1
        run = tokens[index:end]
        singles = sum(1 for item in run if len(item) == 1)
        if len(run) >= 2 and singles >= 2 and len("".join(run)) >= 3:
            out.append("".join(run))
            index = end
            continue
        out.append(tokens[index])
        index += 1
    return " ".join(out)


# Phrasal-verb particles, prepositions and articles can be part of a headword
# ("look after", "a lot", "give up").
TARGET_WORDS_HEADING_RE = re.compile(r"^(target words|word list|vocabulary list)$", re.IGNORECASE)


def _key_letters(text: str) -> str:
    """Letters only: glyph noise, spacing and punctuation must not affect matching."""
    return re.sub(r"[^a-z]", "", text.lower())


def _target_words(pages: list[dict[str, Any]]) -> list[str]:
    """The book's own index of target words ("Target Words" page with comma lists).

    The headword line of an entry is often damaged by the PDF's letter spacing
    ("b e n e f it", "r trick im n."), but the same words appear intact in the index,
    so the index is used to repair a headword instead of trusting broken glyphs.
    """
    words: list[str] = []
    seen: set[str] = set()
    for page in pages:
        if not any(TARGET_WORDS_HEADING_RE.match(line["text"].strip()) for line in page["lines"]):
            continue
        lists = []
        for line in page["lines"]:
            parts = [part.strip().rstrip(".") for part in line["text"].split(",") if part.strip()]
            # A target-word row is nothing but plain words; definitions that happen to
            # contain commas are rejected as a whole.
            if len(parts) >= 3 and all(re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*", part)
                                       for part in parts):
                lists.append(parts)
        if len(lists) < 3:
            continue
        for parts in lists:
            for part in parts:
                key = _key_letters(part)
                if key and key not in seen:
                    seen.add(key)
                    words.append(part)
    return words


def _unit_target_words(pages: list[dict[str, Any]]) -> list[list[str]]:
    """The book's index grouped per unit: 20 target words, in the book's own order.

    The index rows are "word, word, ..." lines separated by the unit number and page.
    Groups of 20 make the index usable as a per-unit whitelist: a damaged headword on
    unit 7's pages can only be one of unit 7's words, which resolves OCR ambiguity
    ("llOne" on unit 4's page is "none", never "lone").
    """
    flat: list[str] = []
    seen: set[str] = set()
    for page in pages:
        if not any(TARGET_WORDS_HEADING_RE.match(line["text"].strip()) for line in page["lines"]):
            continue
        rows = []
        for line in page["lines"]:
            parts = [part.strip().rstrip(".") for part in line["text"].split(",") if part.strip()]
            if len(parts) >= 3 and all(re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*", part) for part in parts):
                rows.append(parts)
        if len(rows) < 3:
            continue
        for row in rows:
            for word in row:
                key = _key_letters(word)
                if key and key not in seen:
                    seen.add(key)
                    flat.append(word)
    return [flat[index:index + 20] for index in range(0, len(flat), 20)]


def _match_target_word(term: str, targets: dict[str, str]) -> str | None:
    """Repair a damaged headword against the book's own word index.

    A match must be the same word once letters only remain, cover most of the headword
    ("trick im" -> trick), or differ by a single edit ("bum" -> burn). A short index word
    can therefore never truncate a longer word ("competition" must not become "pet").
    """
    key = _key_letters(term)
    if not key:
        return None
    if key in targets:
        return targets[key]
    best: tuple[float, str] | None = None
    for target_key, target in targets.items():
        if len(target_key) < 5 or target_key not in key:
            continue
        score = len(target_key) / len(key)
        if score >= 0.6 and (best is None or score > best[0]):
            best = (score, target)
    if best:
        return best[1]
    # The noise is usually glued to the END of the real word ("officer loofisad",
    # "error lerad", "occur teri"), so an index word that opens the headword is the
    # headword whenever it covers most of what precedes the noise.
    for target_key, target in targets.items():
        if len(target_key) >= 4 and key.startswith(target_key) \
                and (len(target_key) >= 5 or len(key) == len(target_key)):
            return target
    # One damaged glyph in a short word ("bum" for "burn", "seve" for "seven"): a single
    # edit is enough, provided the length matches and exactly one index word fits.
    if len(key) >= 3:
        close = [target for target_key, target in targets.items()
                 if abs(len(target_key) - len(key)) <= 1
                 and difflib.SequenceMatcher(None, key, target_key).ratio() >= 0.55]
        if len(close) == 1:
            return close[0]
    return None


def _split_head_tokens(tokens: list[str]) -> tuple[str, str] | None:
    """Split "r afraid [afreid] adj." into ("afraid", "adj").

    Returns None when the line is not shaped like a dictionary headword: one to three
    plain words, then optionally a pronunciation token, then optionally a part of
    speech, and nothing else. A leading single letter is the book's bullet glyph
    ("r afraid", "c reply") and is dropped unless it is the article of "a lot".
    """
    if not tokens:
        return None
    merged: list[str] = []
    for token in tokens:
        if merged and (merged[-1].count("[") > merged[-1].count("]")
                       or merged[-1].count("/") % 2 == 1):
            merged[-1] += " " + token
        else:
            merged.append(token)
    tokens = merged
    # A leading glyph token is the book's bullet ("r afraid", "r- position", "O sense");
    # the article "a" keeps its place so "a lot" survives.
    if len(tokens) > 1 and len(re.sub(r"[^A-Za-z]", "", tokens[0])) <= 1 \
            and tokens[0].lower() not in ("a", "i"):
        tokens = tokens[1:]
    for size in range(min(3, len(tokens)), 0, -1):
        head = tokens[:size]
        if not all(_PLAIN_WORD_RE.match(token) for token in head):
            continue
        rest = tokens[size:]
        pos = ""
        if rest and _PRON_RE.search(rest[0]):
            rest = rest[1:]
        if rest:
            if len(rest) != 1:
                continue
            pos = rest[0].lower().rstrip(".,;:*/^*\"")
            if pos not in _POS_LABELS:
                continue
        return " ".join(head), pos
    return None


def _repair_word(term: str, word_index: dict[str, str], fallback: dict[str, str] | None
                 ) -> tuple[str, int] | None:
    """Best index match for a damaged headword and how confident it is.

    Confidence 2 is an exact letter match, 1 a spelled-out or noise-glued variant of
    exactly one index word ("b e n e f it", "officer loofisad"), 0 a fuzzy match.
    """
    keys: list[str] = []
    parts = term.split()
    keys.append(_key_letters(term))
    if len(parts) > 1:
        # "b e n e f it" is one word, "look after" is not: only a spelled-out or
        # noise-glued head is joined.
        if sum(1 for part in parts if len(part) == 1) >= 2 or len(parts[1]) <= 3:
            keys.append(_key_letters("".join(parts)))
        keys.append(_key_letters(parts[0]))
    for index in (word_index, fallback or {}):
        for key in keys:
            if key and key in index:
                return index[key], 2
    for index in (word_index, fallback or {}):
        for candidate in [term] + ([" ".join(parts[:1])] if len(parts) > 1 else []):
            repaired = _match_target_word(candidate, index)
            if repaired:
                return repaired, 1
        if len(parts) > 1:
            joined = ["".join(parts)] + [" ".join(parts[:size])
                                         for size in range(2, len(parts) + 1)]
            for candidate in joined:
                if _key_letters(candidate) in index:
                    return index[_key_letters(candidate)], 1
    return None


def _dictionary_entry(line: dict[str, Any], targets: dict[str, str] | None = None,
                      heading: bool = False, fallback: dict[str, str] | None = None
                      ) -> dict[str, Any] | None:
    """One dictionary headword with its part of speech, if the line looks like one.

    ``heading`` marks a page that already proved itself a word list, where a bare
    headword line ("r village") is acceptable. ``fallback`` is the book-wide index used
    when the unit-scoped index does not know the word.
    """
    word_index = targets or {}
    raw = line["text"].strip()
    if not raw or len(raw) > 120 or VOCAB_SKIP_RE.match(raw):
        return None
    # Two readings: with the bullet glyph dropped ("r afraid") and kept, because a single
    # letter can also be the first letter of a spelled-out word ("l o t").
    readings: list[tuple[str, str, str]] = []
    for drop_bullet in (True, False):
        text = _collapse_letter_spacing(raw, drop_bullet=drop_bullet)
        parsed = _split_head_tokens(text.split())
        if parsed:
            readings.append((text, parsed[0], parsed[1]))
        elif not readings:
            readings.append((text, "", ""))
    if not readings:
        return None
    # Prefer the reading the book's own index recognises best; without an index, prefer
    # the reading that keeps the most letters ("l o t" is lot, not "o t").
    best: tuple[str, str, str] | None = None
    best_score = -1
    for text, term, pos in readings:
        if not term:
            continue
        if word_index:
            found = _repair_word(term, word_index, fallback)
            score = (found[1] + (1 if pos else 0)) if found else 0
        else:
            score = len(_key_letters(term)) + (1 if pos else 0)
        if score > best_score:
            best, best_score = (text, term, pos), score
    if best is None:
        text, term, pos = readings[0]
    else:
        text, term, pos = best
    if not term:
        # The part of speech is sometimes destroyed by OCR ("hide [haid] y.",
        # "c reply [npiao *", "r real irf»n adj."). Such a line is only accepted when it
        # carries a pronunciation or a part-of-speech token AND the book's own index
        # knows the word; otherwise ordinary prose would become vocabulary.
        if not word_index:
            return None
        cleaned = re.sub(r"[\[\]/]", " ", text)
        words = [token for token in cleaned.split() if _PLAIN_WORD_RE.match(token)]
        if not words:
            return None
        last = cleaned.split()[-1].lower().rstrip(".,;:*/^*")
        if not ("[" in text or "]" in text or last in _POS_LABELS):
            return None
        if len(words) > 1 and len(words[0]) == 1 and words[0].lower() not in ("a", "i"):
            words = words[1:]
        for size in range(1, min(3, len(words)) + 1):
            found = _repair_word(" ".join(words[:size]), word_index, fallback)
            if found:
                return {"term": _clean_term(found[0]), "part_of_speech": _POS_LABELS.get(last, ""),
                        "definition": "", "bbox": line.get("bbox")}
        return None
    # The book's entries always carry at least a bullet glyph, a pronunciation or a word
    # type; a plain word ("seven", "one million") in a table is not a headword.
    if not pos and not _PRON_RE.search(raw) and len(raw.split()) <= 2 and raw == text:
        return None
    single = len(text.split()) == 1 or not pos
    parts = term.split()
    wordlike = [part for part in parts if len(part) > 1]
    keep_phrase = (len(parts) > 1 and len(wordlike) == 1 and parts[0].lower() in ("a", "an", "the")) \
        or (len(wordlike) == 2 and all(len(part) > 2 for part in wordlike))
    if len(parts) > 1 and not keep_phrase:
        term = parts[0]
    if word_index:
        found = _repair_word(term, word_index, fallback)
        if found:
            term = found[0]
        elif single:
            # A bare word line ("r village") is only a headword when the book's index
            # knows the word: on any other page it is an answer option or a stray glyph.
            return None
    elif not pos:
        # Without the book's index a line with no part of speech and no pronunciation is
        # just a word from the page ("seven" in a number table), not a headword.
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z'’\-]*(?: [A-Za-z][A-Za-z'’\-]*)?", term):
        return None
    return {"term": _clean_term(term), "part_of_speech": _POS_LABELS.get(pos, ""),
            "definition": "", "bbox": line.get("bbox")}


def _entry_key(term: str) -> str:
    """Case/punctuation-insensitive key for de-duplicating the same headword."""
    return _key_letters(term)[:60]


def _is_dictionary_page(lines: list[dict[str, Any]], targets: dict[str, str] | None = None
                        ) -> bool:
    """A page whose leading lines are mostly dictionary entries, not prose.

    Word-list pages can carry a heading and a few stray glyphs before the first entry,
    so the first 30 lines are scanned instead of the whole page.
    """
    if _is_not_word_list_page(lines):
        return False
    head = lines[:30]
    if not head:
        return False
    hits = sum(1 for line in head if _dictionary_entry(line, targets))
    return hits >= 4 and hits >= len(head) * 0.25


def _is_not_word_list_page(lines: list[dict[str, Any]]) -> bool:
    """Exercise, index and appendix pages list words too, but they are not word lists."""
    if sum(1 for line in lines if _INDEX_LINE_RE.search(line["text"])) >= 3:
        return True
    if sum(1 for line in lines if NUM_ITEM_RE.match(line["text"].strip())) >= 2:
        return True
    return any(EXERCISE_RE.match(line["text"].strip()) for line in lines)


def _detect_dictionary_entries(pages: list[dict[str, Any]], structure: DetectedStructure,
                               targets: dict[str, str] | None = None,
                               units: list[list[str]] | None = None) -> None:
    """Recognise vocabulary books where every headword owns a definition and a picture.

    A page in this shape repeats "headword [pronunciation] pos." a dozen times, with the
    definition and an illustration beside it — for example 4000 Essential English Words.
    Only a strong run (>= 4 entries on one page) is accepted, so ordinary exercise pages
    are never turned into vocabulary lists. The picture is stored as a NORMALIZED box on
    the original PDF page; nothing is rendered or guessed here.
    """
    word_index = targets or {}
    unit_words = units or []
    seen_terms: set[str] = set()
    for page in pages:
        # An exercise page lists words too ("a. afraid"), so it must never be read as a
        # word list: numbered items, instructions and index leaders are the giveaway.
        if _is_not_word_list_page(page["lines"]):
            continue
        # The unit whose pages this is, from the book's index: a damaged headword can only
        # be one of that unit's twenty target words.
        scoped = word_index
        if unit_words:
            for position, chapter in enumerate(structure.chapters):
                if chapter["page_start"] <= page["page_number"] <= chapter["page_end"] \
                        and position < len(unit_words) and unit_words[position]:
                    scoped = {_key_letters(word): word for word in unit_words[position]}
                    break
        # Pass 1: only entries that carry a part of speech or a pronunciation. A page with
        # four of those is a word list, and only then may bare headword lines count too.
        strong = [line for line in page["lines"] if _dictionary_entry(line, scoped)]
        if len(strong) < 4:
            continue
        entries: list[tuple[dict[str, Any], dict[str, str]]] = []
        for line in page["lines"]:
            entry = _dictionary_entry(line, scoped, heading=True, fallback=word_index)
            if entry:
                entries.append((line, entry))
        if len(entries) < 4:
            continue
        page_width = float(page.get("width") or 0)
        page_height = float(page.get("height") or 0)
        if page_width <= 0 or page_height <= 0:
            continue
        # Appendix pages (numbers, colours) are plain word columns with no definitions;
        # a word-list page explains every word, so require that.
        explained = 0
        for position, (line, _entry) in enumerate(entries):
            limit = entries[position + 1][0]["bbox"][1] if position + 1 < len(entries) else page_height
            # The definition sits in the SAME column as its headword; another column's
            # text must not make an appendix page look explained.
            following = [other for other in page["lines"]
                         if line["bbox"][1] < other["bbox"][1] < limit
                         and other["bbox"][0] < line["bbox"][2] and other["bbox"][2] > line["bbox"][0]]
            if any(len(other["text"].split()) >= 3 for other in following):
                explained += 1
        if explained < max(2, len(entries) * 0.5):
            continue
        for index, (line, entry) in enumerate(entries):
            # Everything between this headword and the next one belongs to this word.
            start_y = line["bbox"][1]
            if index + 1 < len(entries):
                end_y = entries[index + 1][0]["bbox"][1]
            else:
                end_y = page_height
            body = [(other["text"].strip(), other["bbox"]) for other in page["lines"]
                    if other is not line and start_y <= other["bbox"][1] < end_y
                    and other["text"].strip() and not _dictionary_entry(other, word_index)
                    and not _page_noise(other["text"])]
            definition = ""
            for text, _ in body:
                if len(text) >= 3 and not text.startswith(("—", "-", "–")):
                    definition = text[:2000]
                    break
            example = ""
            for text, box in body:
                if text is not definition and (text.startswith(("—", "-", "–", "►", "*")) or box[0] > line["bbox"][0] + 20):
                    example = text.lstrip("—–-►*·• ")[:500]
                    break
            picture = _entry_picture(page, line, body, start_y, end_y, page_width, page_height)
            key = _entry_key(entry["term"])
            # A word appears once in the book; a repeated line on the next page (running
            # header or a duplicated glyph) is the same entry.
            if key and key in seen_terms:
                continue
            seen_terms.add(key)
            if not key or key in {_entry_key(item["term"]) for item in structure.vocabulary
                                  if item.get("part_of_speech")}:
                # The same headword may already be reported by the "word — translation"
                # column detector ("afraid afraid adj." style OCR); keep one entry.
                existing = next((item for item in structure.vocabulary
                                 if _entry_key(item.get("term", "")) == key), None)
                if existing:
                    existing["definition_en"] = existing.get("definition_en") or definition
                    existing.setdefault("bbox", entry.get("bbox"))
                    continue
            structure.vocabulary.append({
                "term": entry["term"], "translation_uz": "", "definition_en": definition,
                "example_sentence": example, "part_of_speech": entry["part_of_speech"][:32],
                "page_number": page["page_number"], "needs_translation": True,
                # The headword box lets the pipeline locate the illustration when the PDF
                # draws all pictures as one full-page background image.
                "bbox": entry.get("bbox"), "picture": picture,
            })
            if picture:
                structure.pictures.append({"term": entry["term"], **picture})


def _page_noise(text: str) -> bool:
    """Watermarks, page numbers and running headers are not word content."""
    stripped = text.strip()
    return (stripped.isdigit() or len(stripped) <= 2 or "&" in stripped
            or stripped.lower().startswith(("elbarskhan", "compass", "www.", "http")))


def _entry_picture(page: dict[str, Any], line: dict[str, Any], body: list[tuple[str, list[float]]],
                   start_y: float, end_y: float, page_width: float, page_height: float
                   ) -> dict[str, Any] | None:
    """Pick the illustration that sits beside this entry, not a decoration band."""
    box_left, box_right = line["bbox"][0], line["bbox"][2]
    for text, box in body:
        box_left = min(box_left, box[0])
        box_right = max(box_right, box[2])
    best, best_area = None, 0.0
    for image in page.get("images") or []:
        box = image.get("bbox") or []
        if len(box) != 4:
            continue
        center_y = (box[1] + box[3]) / 2
        if not start_y - 4 <= center_y < end_y:
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        # Skip icons and page-wide decoration bands.
        if width * height < 2500 or width > page_width * 0.9 or height > page_height * 0.9:
            continue
        if not (box[2] <= box_left + 8 or box[0] >= box_right - 8):
            continue
        if width * height > best_area:
            best, best_area = box, width * height
    if not best:
        return None
    return {"page_number": page["page_number"], "bbox": [
        round(max(0.0, min(1.0, best[0] / page_width)), 4),
        round(max(0.0, min(1.0, best[1] / page_height)), 4),
        round(max(0.0, min(1.0, best[2] / page_width)), 4),
        round(max(0.0, min(1.0, best[3] / page_height)), 4)]}


def _detect_answer_keys(pages: list[dict[str, Any]], structure: DetectedStructure) -> None:
    in_key = False
    current_ref = ""
    for page in pages:
        # OCR can corrupt answers or exercise references; never treat it as a verified key.
        if page.get("ocr_used"):
            continue
        for line in page["lines"]:
            text = line["text"].strip()
            if KEY_HEADER_RE.match(text) and len(text) < 40:
                in_key = True
                current_ref = ""
                continue
            if not in_key:
                continue
            header = EXERCISE_RE.match(text)
            if header:
                num = header.group(2)
                current_ref = f"exercise {num}" if num else ""
                continue
            if CHAPTER_RE.match(text):
                in_key = False
                current_ref = ""
                continue
            consumed = False
            for m in re.finditer(r"(\d{1,3})\s*[\.\)\-:]?\s+([A-Da-d]\b|[\w'’\.,;\- ]{1,60}?)(?=\s+\d{1,3}[\.\)\-:]?\s|\s*$)", text):
                structure.answer_key_entries.append({
                    "exercise_ref": current_ref, "question_number": m.group(1),
                    "answers": [a.strip() for a in re.split(r"[,;/]", m.group(2)) if a.strip()],
                    "page": page["page_number"],
                })
                consumed = True
            if not consumed:
                nm = NUM_ITEM_RE.match(text)
                if nm:
                    structure.answer_key_entries.append({
                        "exercise_ref": current_ref, "question_number": nm.group(1),
                        "answers": [a.strip() for a in re.split(r"[,;/]", nm.group(2)) if a.strip()],
                        "page": page["page_number"],
                    })


def _attach_answer_keys(structure: DetectedStructure) -> None:
    """Match only unique explicit exercise+question refs, or globally unique unlabelled numbers."""
    from collections import Counter, defaultdict
    refs = Counter(ex.ref.lower() for ex in structure.exercises)
    numbers = Counter(q.number for ex in structure.exercises for q in ex.questions)
    # Index key entries once; scanning the whole list per question was O(Q*K).
    labelled_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unlabelled_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in structure.answer_key_entries:
        if entry["exercise_ref"]:
            labelled_index[(entry["exercise_ref"], entry["question_number"])].append(entry)
        else:
            unlabelled_index[entry["question_number"]].append(entry)
    for ex in structure.exercises:
        ref = ex.ref.lower()
        for q in ex.questions:
            labelled = labelled_index.get((ref, q.number), []) if refs[ref] == 1 else []
            unlabelled = unlabelled_index.get(q.number, []) if numbers[q.number] == 1 else []
            candidates = labelled or unlabelled
            if len(candidates) == 1 and candidates[0]["answers"]:
                q.correct_answers = candidates[0]["answers"]
                q.answer_source = "key"
            elif labelled or unlabelled or structure.answer_key_entries:
                q.needs_review = True
                ex.needs_review = True
                structure.warnings.append({"page": ex.page_number, "code": "KEY_AMBIGUOUS",
                    "message_uz": f"{ex.ref}, {q.number}: javob kaliti ishonchli moslanmadi."})


def detect_structure(pages: list[dict[str, Any]]) -> DetectedStructure:
    structure = DetectedStructure()
    body_sizes = [ln["size"] for p in pages for ln in p["lines"]]
    body_size = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 10.0

    # ---- flatten lines with page context ----
    flat: list[dict[str, Any]] = []
    seq = 0
    for page in pages:
        for line in page["lines"]:
            seq += 1
            flat.append({**line, "page": page["page_number"], "seq": seq})

    last_page = max((p["page_number"] for p in pages), default=1)

    # ---- dictionary-style books: group by word-list pages, not by exercise headers ----
    # A word-list page has no "Exercise 1" heading, so the generic heuristics below would
    # turn every page into its own chapter. Group into one unit per word-list page instead.
    # The book's own word index repairs headwords damaged by the PDF's letter spacing.
    unit_words = _unit_target_words(pages)
    targets = {_key_letters(word): word for word in _target_words(pages)}
    dictionary_pages = [page for page in pages if _is_dictionary_page(page["lines"], targets)]
    if not dictionary_pages:
        targets = {}
    if len(dictionary_pages) >= 3:
        structure.layout = "dictionary"
        # Consecutive word-list pages belong to ONE unit (a unit's list often spans two
        # pages); the exercise pages that follow them stay in that unit too.
        runs: list[list[dict[str, Any]]] = []
        for page in dictionary_pages:
            if runs and page["page_number"] == runs[-1][-1]["page_number"] + 1:
                runs[-1].append(page)
            else:
                runs.append([page])
        for index, run in enumerate(runs):
            page_start = run[0]["page_number"]
            page_end = runs[index + 1][0]["page_number"] - 1 if index + 1 < len(runs) else last_page
            terms: list[str] = []
            for page in run:
                for line in page["lines"]:
                    entry = _dictionary_entry(line, targets)
                    if not entry:
                        continue
                    # "error lerad" is OCR noise glued to the headword; keep the word only.
                    word = (_match_target_word(entry["term"], targets) or entry["term"]).split(" ")[0]
                    if word and word not in terms:
                        terms.append(word)
            title = f"Unit {index + 1}"
            if terms:
                title += " · " + ", ".join(terms[:4]) + ("…" if len(terms) > 4 else "")
            structure.chapters.append({"title": title, "kind": "unit", "number": str(index + 1),
                                       "page_start": page_start, "page_end": page_end,
                                       "order_index": index})
            structure.lessons.append({"chapter_index": index, "title": title,
                                      "page_start": page_start, "page_end": page_end,
                                      "topic": ""})
    else:
        _detect_chapters_and_lessons(flat, body_size, last_page, structure)

    _detect_exercises(pages, structure)
    # Dictionary pages first: the column-pair detector below must not also report the
    # same headwords from their definition lines.
    _detect_dictionary_entries(pages, structure, targets, unit_words if structure.layout == "dictionary" else None)
    _detect_vocabulary(pages, structure, {ex.page_number for ex in structure.exercises})
    _detect_answer_keys(pages, structure)
    _attach_answer_keys(structure)
    _finish_structure(structure)
    return structure


def _detect_chapters_and_lessons(flat: list[dict[str, Any]], body_size: float, last_page: int,
                                 structure: DetectedStructure) -> None:
    chapter_starts: list[dict[str, Any]] = []
    lesson_starts: list[dict[str, Any]] = []
    for line in flat:
        text = line["text"].strip()
        if len(text) > 120:
            continue
        big = line["size"] >= body_size * 1.25 or line["bold"]
        cm = CHAPTER_RE.match(text)
        if cm and (big or line["size"] >= body_size):
            chapter_starts.append(line)
            continue
        if LESSON_RE.match(text) and not EXERCISE_RE.match(text) and not KEY_HEADER_RE.match(text):
            lesson_starts.append(line)
            continue
        if KEY_HEADER_RE.match(text) or EXERCISE_RE.match(text):
            continue
        if cm:
            chapter_starts.append(line)
            continue
        if (big and len(text.split()) <= 12 and line["page"] > 0
                and not text.endswith((".", ",", ";", "?")) and not NUM_ITEM_RE.match(text)
                and not OPTION_RE.match(text)
                and not re.search(r"^(vocabulary|word\s*list|lug['`’]at)\b", text, re.I)):
            chapter_starts.append(line)
            continue

    # dedupe chapter starts on same page (keep first)
    seen_pages: set[int] = set()
    chapters: list[dict[str, Any]] = []
    for line in chapter_starts:
        if line["page"] in seen_pages:
            continue
        seen_pages.add(line["page"])
        cm = CHAPTER_RE.match(line["text"].strip())
        chapters.append({
            "title": line["text"].strip()[:200],
            "kind": "unit" if cm and cm.group(1).lower().startswith("unit") else "chapter",
            "number": (cm.group(2) if cm else "")[:16],
            "page_start": line["page"],
        })
    for i, ch in enumerate(chapters):
        ch["page_end"] = chapters[i + 1]["page_start"] - 1 if i + 1 < len(chapters) else last_page
        ch["order_index"] = i
    if not chapters:
        chapters = [{"title": "Kitob", "kind": "chapter", "number": "",
                     "page_start": 1, "page_end": last_page, "order_index": 0}]
        structure.warnings.append({
            "page": 0, "code": "NO_CHAPTERS",
            "message_uz": "Bob/Unit sarlavhalari aniqlanmadi — butun kitob bitta bo'lim sifatida ochildi.",
        })
    structure.chapters = chapters

    # lessons: explicit lesson headers inside chapters, else chapter==lesson
    for ch in chapters:
        in_lessons = [l for l in lesson_starts if ch["page_start"] <= l["page"] <= ch["page_end"]]
        if in_lessons:
            for j, l in enumerate(in_lessons):
                structure.lessons.append({
                    "chapter_index": ch["order_index"], "title": l["text"].strip()[:200],
                    "page_start": l["page"],
                    "page_end": in_lessons[j + 1]["page"] - 1 if j + 1 < len(in_lessons) else ch["page_end"],
                    "topic": guess_topic(l["text"]),
                })
        else:
            structure.lessons.append({
                "chapter_index": ch["order_index"], "title": ch["title"],
                "page_start": ch["page_start"], "page_end": ch["page_end"],
                "topic": guess_topic(ch["title"]),
            })


def _detect_exercises(pages: list[dict[str, Any]], structure: DetectedStructure) -> None:
    for page in pages:
        # Exercise labels inside an answer-key section are references, not exercises.
        key_index = next((i for i, ln in enumerate(page["lines"]) if KEY_HEADER_RE.match(ln["text"].strip())), len(page["lines"]))
        content_lines = page["lines"][:key_index]
        hdr_idx = []
        for i, ln in enumerate(content_lines):
            text = ln["text"].strip()
            if EXERCISE_RE.match(text):
                hdr_idx.append(i)
                continue
            numbered = NUMBERED_INSTRUCTION_RE.match(text)
            instruction = numbered.group(2) if numbered else text
            # Only propose an instruction header when numbered questions follow nearby.
            # A headingless or OCR-derived candidate always requires review.
            if INSTRUCTION_RE.match(instruction) and any(
                    NUM_ITEM_RE.match(nxt["text"].strip()) for nxt in content_lines[i+1:i+5]):
                if (hdr_idx and EXERCISE_RE.match(content_lines[hdr_idx[-1]]["text"].strip())
                        and not any(NUM_ITEM_RE.match(prev["text"].strip())
                                    for prev in content_lines[hdr_idx[-1]+1:i])):
                    continue  # instruction belonging to the immediately preceding labelled exercise
                hdr_idx.append(i)
        for j, i in enumerate(hdr_idx):
            header = {**content_lines[i], "seq": i + 1}
            end = hdr_idx[j + 1] if j + 1 < len(hdr_idx) else len(content_lines)
            body = content_lines[i + 1:end]
            structure.exercises.append(_parse_exercise_block(header, body, page["page_number"], structure))

    # ---- matching: two-column layout when "match" instruction present ----
    page_lookup = {p["page_number"]: p for p in pages}
    for ex in structure.exercises:
        if ex.exercise_type == "matching" and not any(q.matching_pairs for q in ex.questions):
            _parse_two_column_matching(page_lookup=page_lookup, ex=ex)


def _finish_structure(structure: DetectedStructure) -> None:
    # per-question topic inheritance
    topic_by_page: dict[int, str] = {}
    for lesson in structure.lessons:
        if lesson["topic"]:
            for pnum in range(lesson["page_start"], lesson["page_end"] + 1):
                topic_by_page[pnum] = lesson["topic"]
    for ex in structure.exercises:
        ex.topic = ex.topic or topic_by_page.get(ex.page_number, "")

    if not structure.vocabulary:
        structure.warnings.append({
            "page": 0, "code": "NO_VOCABULARY",
            "message_uz": "Kitobda lug'at yozuvlari aniqlanmadi. Lug'at ro'yxati bo'lsa, sahifa bo'limlarini tekshiring.",
        })
    if not structure.exercises:
        structure.warnings.append({
            "page": 0, "code": "NO_EXERCISES",
            "message_uz": "Kitobda mashq (Exercise/Task/Mashq) bloklari topilmadi. Matn faqat o'qish rejimida mavjud.",
        })


def _parse_two_column_matching(page_lookup: dict[int, dict[str, Any]], ex: DetectedExercise) -> None:
    page = page_lookup.get(ex.page_number)
    if not page:
        return
    mid = page["width"] / 2
    left_items: list[tuple[str, str]] = []
    right_items: list[tuple[str, str]] = []
    for line in page["lines"]:
        if ex.bbox and not (ex.bbox[1] - 10 <= line["bbox"][1] <= ex.bbox[3] + 120):
            continue
        nm = NUM_ITEM_RE.match(line["text"])
        om = OPTION_RE.match(line["text"])
        if not (nm or om):
            continue
        label = nm.group(1) if nm else om.group(1).upper()
        value = (nm.group(2) if nm else om.group(2)).strip()
        if line["bbox"][2] <= mid:
            left_items.append((label, value))
        else:
            right_items.append((label, value))
    if len(left_items) >= 3 and len(right_items) >= 3:
        ex.questions = [
            DetectedQuestion(
                number=str(i + 1), prompt=f"{lv}",
                matching_pairs=[{"left": lv, "right": rv}],
                bbox=None,
            )
            for i, (ll, lv) in enumerate(left_items)
            for rv in [right_items[i][1] if i < len(right_items) else ""]
        ]
        for i, q in enumerate(ex.questions):
            q.matching_pairs = [{"left": left_items[i][1], "right": right_items[i][1] if i < len(right_items) else ""}]
