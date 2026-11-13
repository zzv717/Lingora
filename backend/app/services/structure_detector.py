"""Deterministic textbook structure detection (rule-based core of the AI Book Analyzer).

Finds: chapters/units, lessons, exercises (8 types), questions, multiple-choice options,
matching pairs, vocabulary lists, answer keys — while preserving page numbers and
bounding boxes. AI enrichment (optional) refines this result afterwards; it never
replaces it silently.

Design rules:
- Never invent content: only structures actually observed in the text.
- Anything ambiguous is kept but flagged with needs_review / warnings.
"""
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
    r"^(?:complete|fill\s+in|choose|match|read\s+and\s+answer|write\s+about|rewrite|"
    r"put\s+the\s+words|translate|true\s+or\s+false|answer\s+the\s+questions)\b", re.IGNORECASE)
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
    num = (m.group(2) or "").strip() if m else ""
    instr = (m.group(3) or "").strip() if m else header["text"].strip()
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
    for i, m in enumerate(matches, 1):
        boxes = _blank_bboxes({"text": prompt, "chars": cur.get("chars", [])}, 0)
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
    from collections import Counter
    refs = Counter(ex.ref.lower() for ex in structure.exercises)
    numbers = Counter(q.number for ex in structure.exercises for q in ex.questions)
    for ex in structure.exercises:
        ref = ex.ref.lower()
        for q in ex.questions:
            labelled = [e for e in structure.answer_key_entries if e["exercise_ref"] == ref
                        and e["question_number"] == q.number] if refs[ref] == 1 else []
            unlabelled = [e for e in structure.answer_key_entries if not e["exercise_ref"]
                          and e["question_number"] == q.number] if numbers[q.number] == 1 else []
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

    # ---- chapters & lessons ----
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
    last_page = max((p["page_number"] for p in pages), default=1)
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

    # ---- exercises ----
    for page in pages:
        # Exercise labels inside an answer-key section are references, not exercises.
        key_index = next((i for i, ln in enumerate(page["lines"]) if KEY_HEADER_RE.match(ln["text"].strip())), len(page["lines"]))
        content_lines = page["lines"][:key_index]
        hdr_idx = [i for i, ln in enumerate(content_lines) if EXERCISE_RE.match(ln["text"].strip())]
        if not hdr_idx:
            # Conservative fallback: an instruction followed nearby by numbered items.
            # Do not infer headingless exercises from arbitrary numbered prose alone.
            hdr_idx = [i for i, ln in enumerate(content_lines) if INSTRUCTION_RE.match(ln["text"].strip())
                       and any(NUM_ITEM_RE.match(nxt["text"].strip()) for nxt in content_lines[i+1:i+5])]
        for j, i in enumerate(hdr_idx):
            header = {**content_lines[i], "seq": i + 1}
            end = hdr_idx[j + 1] if j + 1 < len(hdr_idx) else len(content_lines)
            body = content_lines[i + 1:end]
            structure.exercises.append(_parse_exercise_block(header, body, page["page_number"], structure))

    # ---- matching: two-column layout when "match" instruction present ----
    for ex in structure.exercises:
        if ex.exercise_type == "matching" and not any(q.matching_pairs for q in ex.questions):
            _parse_two_column_matching(page_lookup={p["page_number"]: p for p in pages}, ex=ex)

    # ---- vocabulary & answer keys ----
    occupied = {ex.page_number for ex in structure.exercises}
    _detect_vocabulary(pages, structure, occupied)
    _detect_answer_keys(pages, structure)
    _attach_answer_keys(structure)

    # per-question topic inheritance
    topic_by_page: dict[int, str] = {}
    for lesson in structure.lessons:
        if lesson["topic"]:
            for pnum in range(lesson["page_start"], lesson["page_end"] + 1):
                topic_by_page[pnum] = lesson["topic"]
    for ex in structure.exercises:
        ex.topic = ex.topic or topic_by_page.get(ex.page_number, "")

    if not structure.exercises:
        structure.warnings.append({
            "page": 0, "code": "NO_EXERCISES",
            "message_uz": "Kitobda mashq (Exercise/Task/Mashq) bloklari topilmadi. Matn faqat o'qish rejimida mavjud.",
        })
    return structure


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
