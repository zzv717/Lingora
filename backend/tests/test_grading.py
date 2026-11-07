"""Grading engine: normalization, alternatives, typos, key priority, answer types."""
from app.models import Exercise, ExerciseQuestion, ExerciseOption
from app.services.grading import answers_match, grade_question_deterministic, levenshtein, normalize


def mk_question(exercise_type: str, *, correct_answers=None, options=None,
                blanks=None, matching_pairs=None, answer_source="key") -> tuple[Exercise, ExerciseQuestion]:
    ex = Exercise(book_id="b", exercise_type=exercise_type, title="t")
    q = ExerciseQuestion(exercise_id="x", order_index=0, number="1", prompt="p",
                         correct_answers=correct_answers or [], answer_source=answer_source,
                         blanks=blanks or [], matching_pairs=matching_pairs or [])
    q.exercise = ex
    ex.questions = [q]
    for letter, text, is_c in (options or []):
        q.options.append(ExerciseOption(question_id="x", letter=letter, text=text, is_correct=is_c))
    return ex, q


def test_normalization():
    assert normalize("  Goes!  ") == "goes"
    assert normalize("O‘zbekiston") == normalize("o'zbekiston")
    assert normalize("hello,   world.") == "hello, world"


def test_levenshtein():
    assert levenshtein("goes", "goes") == 0
    assert levenshtein("goes", "goe") == 1
    assert levenshtein("cat", "dog") == 3


def test_answers_match_basic():
    assert answers_match("goes", ["goes"])
    assert answers_match("GOES", ["goes"])
    assert answers_match("goes.", ["goes"])
    assert answers_match("is  reading", ["is reading"])
    assert not answers_match("went", ["goes"])


def test_typo_tolerance_for_long_words():
    assert answers_match("tehcher", ["teacher"])  # 1 typo, len>=4
    assert not answers_match("teachrs", ["teacher"])  # 2 typos -> wrong
    assert not answers_match("go", ["goe"])  # short words: exact only


def test_exact_mode_no_typos():
    assert answers_match("teacher", ["teacher"], exact=True)
    assert not answers_match("tehcher", ["teacher"], exact=True)


def test_mc_by_options_is_correct_flag():
    ex, q = mk_question("multiple_choice", options=[("A", "go", False), ("B", "goes", True), ("C", "going", False)])
    assert grade_question_deterministic(q, {"selection": "B"})[0] is True
    assert grade_question_deterministic(q, {"selection": "A"})[0] is False
    assert grade_question_deterministic(q, {"selection": "b"})[0] is True  # case-insensitive


def test_mc_by_key_without_option_flags():
    ex, q = mk_question("multiple_choice", correct_answers=["B"], answer_source="key")
    assert grade_question_deterministic(q, {"selection": "B"})[0] is True
    assert grade_question_deterministic(q, {"selection": "C"})[0] is False


def test_mc_without_key_unverifiable():
    ex, q = mk_question("multiple_choice", answer_source="unknown")
    assert grade_question_deterministic(q, {"selection": "A"})[0] is None


def test_fill_blank_multi():
    ex, q = mk_question("fill_blank", correct_answers=["is reading"],
                        blanks=[{"id": "b1", "bbox": None}, {"id": "b2", "bbox": None}])
    ok, _ = grade_question_deterministic(q, {"blanks": {"b1": "is", "b2": "reading"}})
    assert ok is True
    ok, _ = grade_question_deterministic(q, {"blanks": {"b1": "is", "b2": "read"}})
    assert ok is False


def test_fill_blank_alternatives():
    ex, q = mk_question("fill_blank", correct_answers=["does"])
    ok, _ = grade_question_deterministic(q, {"blanks": {"b1": "Does"}})
    assert ok is True


def test_true_false_with_key():
    ex, q = mk_question("true_false", correct_answers=["true"])
    assert grade_question_deterministic(q, {"selection": "to'g'ri"})[0] is True
    assert grade_question_deterministic(q, {"selection": "false"})[0] is False


def test_matching_pairs():
    ex, q = mk_question("matching", matching_pairs=[
        {"left": "big", "right": "katta"}, {"left": "small", "right": "kichik"}])
    ok, given = grade_question_deterministic(q, {"pairs": {"0": "katta", "1": "kichik"}})
    assert ok is True
    ok, given = grade_question_deterministic(q, {"pairs": {"0": "kichik", "1": "kichik"}})
    assert ok is False


def test_translation_without_key_unverifiable():
    ex, q = mk_question("translation", answer_source="unknown")
    assert grade_question_deterministic(q, {"text": "I go to school"})[0] is None


def test_writing_always_needs_ai():
    ex, q = mk_question("writing", answer_source="unknown")
    assert grade_question_deterministic(q, {"text": "My hobby is reading books."})[0] is None
