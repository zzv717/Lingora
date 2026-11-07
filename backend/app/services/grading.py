"""Exercise grading engine.

Priority (per product spec):
1. Verified textbook answer key      -> authoritative
2. Deterministic rules               -> normalization, numeric compare, letters, exact pairs
3. Context-aware AI evaluation       -> structured JSON verdicts with confidence
4. Human review flag                 -> low-confidence AI verdicts are surfaced as "uncertain",
                                        never presented as authoritative.

Legitimate alternative answers are supported (accepted alternatives from the key or AI).
Open-ended (writing/translation) tasks REQUIRE AI; without AI they are returned as
`unverified` — the app never pretends to have graded them.
"""
import logging
import re
import unicodedata

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AINotConfigured  # noqa: F401 (re-exported for API layer)
from app.models import Exercise, ExerciseQuestion
from app.services.ai import usage as usage_service
from app.services.ai.provider import ChatMessage, get_provider, structured


log = logging.getLogger("lingora.grading")

_WORD_RE = re.compile(r"[a-zа-яёʼ'`-]+", re.IGNORECASE)


def normalize(text: str, *, keep_letters_only: bool = False) -> str:
    text = unicodedata.normalize("NFKC", (text or "")).strip().lower()
    # Uzbek apostrophe variants (oʻ / o‘ / o' / o`) all normalize to a single form
    for ch in "\u2019\u2018\u02bb\u02bc\u0060\u2032":
        text = text.replace(ch, "'")
    text = re.sub(r"\s+", " ", text)
    if keep_letters_only:
        text = " ".join(_WORD_RE.findall(text))
    text = text.strip(" .!?;:,")
    return text


def levenshtein(a: str, b: str, cap: int = 3) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def answers_match(given: str, accepted: list[str], *, exact: bool = False) -> bool:
    """Deterministic comparison with sensible normalization. `exact` (spelling tests) allows zero typos."""
    g = normalize(given)
    if not g:
        return False
    for acc in accepted:
        a = normalize(acc)
        if not a:
            continue
        if g == a:
            return True
        if exact:
            continue
        # numeric equality (3 = three etc. handled by key alternatives)
        try:
            if abs(float(g.replace(",", ".")) - float(a.replace(",", "."))) < 1e-9:
                return True
        except ValueError:
            pass
        # single-token typo tolerance (leven<=1) for words of length>=4
        if len(a.split()) == 1 and len(g.split()) == 1 and min(len(a), len(g)) >= 4:
            if levenshtein(g, a, cap=1) <= 1:
                return True
    return False


# ---------- per-type deterministic grading ----------

def grade_question_deterministic(q: ExerciseQuestion, answer: dict) -> tuple[bool | None, str]:
    """Returns (correct|None, given_repr). None = cannot grade deterministically."""
    etype = q.exercise.exercise_type
    accepted = list(q.correct_answers or [])
    if etype == "multiple_choice":
        sel = (answer.get("selection") or "").strip().upper()
        correct_letters = [o.letter.upper() for o in q.options if o.is_correct]
        if correct_letters:
            return (sel in correct_letters), sel
        if accepted:
            acc_norm = {normalize(a).upper() for a in accepted}
            return (sel in acc_norm or normalize(sel) in acc_norm), sel
        return None, sel
    if etype == "true_false":
        given = normalize(answer.get("selection") or answer.get("text") or "")
        true_tokens = {"true", "t", "ha", "to'g'ri", "togri", "1", "да"}
        false_tokens = {"false", "f", "yo'q", "yoq", "noto'g'ri", "notogri", "0"}
        if accepted:
            acc = normalize(accepted[0])
            if acc in true_tokens or acc in false_tokens:
                return ((given in true_tokens) == (acc in true_tokens)), given
        if given in true_tokens or given in false_tokens:
            return None, given  # no key: cannot know the expected truth value
        return None, given
    if etype == "matching":
        pairs = q.matching_pairs or []
        given_pairs = answer.get("pairs") or {}
        if not pairs:
            return None, str(given_pairs)
        ok = 0
        for i, pair in enumerate(pairs):
            expect_right = normalize(pair.get("right", ""))
            got = normalize(str(given_pairs.get(str(i), given_pairs.get(i, ""))))
            if got and (got == expect_right or answers_match(got, [pair.get("right", "")])):
                ok += 1
        return (ok == len(pairs) and ok > 0), f"{ok}/{len(pairs)}"
    if etype == "fill_blank":
        blanks = q.blanks or [{"id": "b1"}]
        given_blanks = answer.get("blanks") or {}
        given_values = [
            normalize(str(given_blanks.get((b or {}).get("id", f"b{i+1}") or f"b{i+1}", "")))
            for i, b in enumerate(blanks)
        ]
        any_given = any(given_values)
        if not accepted:
            return None, str(given_blanks)
        if len(accepted) == 1 and len(blanks) > 1:
            # one combined key answer ("is reading") for several blanks -> split by words
            words = normalize(accepted[0]).split()
            if len(words) == len(blanks):
                ok = all(answers_match(g, [w]) for g, w in zip(given_values, words) if g) and any_given
                return (ok and any_given), str(given_blanks)
            ok = answers_match(" ".join(given_values), accepted)
            return (ok and any_given), str(given_blanks)
        ok = True
        for i in range(len(blanks)):
            if i < len(accepted):
                acc = accepted[i]
            elif len(accepted) < len(blanks):
                acc = accepted[i % len(accepted)]
            else:
                acc = accepted[-1]
            acc_list = [a for a in (acc if isinstance(acc, list) else [acc]) if a]
            if not given_values[i] or not (acc_list and answers_match(given_values[i], acc_list)):
                ok = False
        return (ok and any_given), str(given_blanks)
    if etype in ("sentence_construction",):
        given = answer.get("text") or ""
        if accepted:
            return answers_match(given, accepted, keep_letters_only=False) or None, given
        return None, given
    # translation / writing / reading_comprehension open answers: need AI (or key)
    given = answer.get("text") or ""
    if accepted and etype == "translation":
        return None, given  # open translation: many valid variants -> AI decides
    return None, given


# ---------- AI evaluation ----------

class VerdictItem(BaseModel):
    question_number: str
    correct: bool | None
    confidence: float = 0.0
    expected_answer: str = ""
    accepted_alternatives: list[str] = []
    explanation_uz: str = ""
    grammar_note_uz: str = ""


class VerdictSchema(BaseModel):
    verdicts: list[VerdictItem]
    overall_feedback_uz: str = ""


TUTOR_GRADING_SYSTEM = (
    "Siz ingliz tili o'qituvchisisz. O'quvchining javoblarini baholaysiz. JAVOB FAQAT JSON formatida.\n"
    "Qoidalar:\n"
    "- Grammatik to'g'ri alternativ javobni noto'g'ri deb baho Lamang (kitobdagi aniq so'zlashdan farq qilsa ham).\n"
    "- Har bir savol uchun: correct (true/false), confidence (0-1), expected_answer, "
    "accepted_alternatives, explanation_uz (o'zbek tilida, qisqa va tushunarli), grammar_note_uz.\n"
    "- Ishonchingiz kam bo'lsa confidence past bo'lsin va correct=null.\n"
    "- Kitobda yo'q faktlarni o'ylab topmang.\n"
    'Format: {"verdicts":[{"question_number":"1","correct":true,"confidence":0.95,'
    '"expected_answer":"goes","accepted_alternatives":["is going"],'
    '"explanation_uz":"...","grammar_note_uz":"..."}],"overall_feedback_uz":"..."}'
)


def grade_with_ai(db: Session, user_id: str, exercise: Exercise,
                  answers: dict[str, dict]) -> tuple[dict[str, dict], bool, bool]:
    """AI evaluation of a whole exercise in ONE structured call.
    Returns (verdicts_by_question_id, uncertain_any, ok).
    Never silently fakes: if AI unconfigured/unreachable the caller falls back honestly."""
    usage_service.enforce_ai_quota(db, user_id, "grading")
    lines = []
    for q in exercise.questions:
        given = answers.get(q.id, {})
        lines.append({
            "question_number": q.number or str(q.order_index + 1),
            "type": exercise.exercise_type,
            "prompt": q.prompt,
            "options": [{"letter": o.letter, "text": o.text} for o in q.options],
            "key_available": list(q.correct_answers or []) or None,
            "student_answer": given,
        })
    user_prompt = {
        "exercise_type": exercise.exercise_type,
        "instructions": exercise.instructions,
        "topic": exercise.topic,
        "questions": lines,
    }
    import json as _json

    schema, resp = structured(
        VerdictSchema,
        [ChatMessage(role="system", content=TUTOR_GRADING_SYSTEM),
         ChatMessage(role="user", content=_json.dumps(user_prompt, ensure_ascii=False))],
    )
    usage_service.record_usage(db, user_id, "grading", get_provider().name, resp.model,
                               resp.tokens_in, resp.tokens_out)
    by_number = {v.question_number: v.model_dump() for v in schema.verdicts}
    out: dict[str, dict] = {}
    uncertain_any = False
    for q in exercise.questions:
        num = q.number or str(q.order_index + 1)
        v = by_number.get(num)
        if not v:
            out[q.id] = {"correct": None, "confidence": 0.0, "expected": "", "explanation_uz": "",
                         "source": "unverified", "grammar_note_uz": ""}
            uncertain_any = True
            continue
        low_conf = v["correct"] is None or v["confidence"] < 0.7
        uncertain_any = uncertain_any or low_conf
        out[q.id] = {
            "correct": None if low_conf else v["correct"],
            "confidence": v["confidence"],
            "expected": v["expected_answer"],
            "alternatives": v["accepted_alternatives"],
            "explanation_uz": v["explanation_uz"],
            "grammar_note_uz": v["grammar_note_uz"],
            "source": "ai",
        }
    return out, uncertain_any, True

