"""API request/response schemas (Pydantic v2)."""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---------- Auth ----------

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(default="", max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    created_at: datetime


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    interface_language: str
    learning_language: str
    explanation_language: str
    theme: str
    daily_goal_minutes: int
    vocab_pass_score: int
    vocabulary_gating: bool
    timezone: str


class ProfileUpdateIn(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    theme: Optional[Literal["light", "dark", "system"]] = None
    daily_goal_minutes: Optional[int] = Field(default=None, ge=5, le=600)
    vocab_pass_score: Optional[int] = Field(default=None, ge=50, le=100)
    vocabulary_gating: Optional[bool] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    interface_language: Optional[str] = Field(default=None, max_length=8)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordOut(BaseModel):
    delivered: bool
    # dev-only: when SMTP is not configured we surface the link so the flow is testable.
    reset_link: Optional[str] = None
    message_uz: str


# ---------- Books / pipeline ----------

class BookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    original_filename: str
    status: str
    page_count: int
    file_size_bytes: int
    description: str
    created_at: datetime
    updated_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    book_id: str
    status: str
    progress: float
    stage: str
    stage_label_uz: str
    warnings: list[Any] = []
    error_code: str
    error_message: str


class ChapterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    kind: str
    number: str
    page_start: int
    page_end: int
    order_index: int


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    chapter_id: Optional[str]
    title: str
    topic: str
    page_start: int
    page_end: int
    order_index: int
    grammar_explanation_uz: str
    summary: str


class BookStructureOut(BaseModel):
    book: BookOut
    chapters: list[ChapterOut]
    lessons: list[LessonOut]
    lessons_progress: dict[str, Any]  # lesson_id -> {status, exercises_checked, exercises_total, vocab_gate_passed, locked}
    coverage: dict[str, Any]
    answer_key_pages: list[int]


class PageOut(BaseModel):
    page_number: int
    width: float
    height: float
    text: str
    blocks: list[Any]
    images: list[Any]
    needs_ocr: bool
    ocr_used: bool
    has_warning: bool


# ---------- Exercises ----------

class OptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    letter: str
    text: str
    is_correct: Optional[bool]


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    number: str
    order_index: int
    prompt: str
    passage: str
    blanks: list[Any] = []
    matching_pairs: list[Any] = []
    options: list[OptionOut] = []
    # NOTE: correct_answers are never exposed to students before checking.


class ExerciseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    book_id: str
    lesson_id: Optional[str]
    exercise_type: str
    title: str
    instructions: str
    ref: str
    page_number: int
    bbox: Optional[dict[str, Any]]
    topic: str
    explanation_uz: str
    order_index: int
    detection: str
    needs_review: bool
    questions: list[QuestionOut] = []


class AnswerSaveIn(BaseModel):
    question_id: str
    content: dict[str, Any]


class AnswersSaveIn(BaseModel):
    answers: list[AnswerSaveIn]
    submit: bool = False


class VerdictOut(BaseModel):
    question_id: str
    number: str
    correct: Optional[bool]
    confidence: float
    given: str
    expected: str
    explanation_uz: str
    source: str  # key | deterministic | ai | unverified
    grammar_note_uz: str = ""


class CheckOut(BaseModel):
    attempt_id: str
    score: float
    max_score: float
    percent: float
    uncertain: bool
    ai_used: bool
    verdicts: list[VerdictOut]
    overall_feedback_uz: str


# ---------- Vocabulary ----------

class VocabWordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    term: str
    translation_uz: str
    definition_en: str
    example_sentence: str
    part_of_speech: str
    page_number: int
    lesson_id: Optional[str]
    needs_translation: bool


class VocabSessionItemOut(BaseModel):
    item_id: str
    word_id: str
    type: str
    prompt: str
    options: list[dict[str, str]] = []
    audio_text: str = ""
    sentence: str = ""
    hint: str = ""


class VocabSessionOut(BaseModel):
    id: str
    kind: str
    status: str
    required_score: int
    score: float
    total_items: int
    answered_items: int
    items: list[VocabSessionItemOut]


class VocabAnswerIn(BaseModel):
    item_id: str
    response: str


class VocabAnswerOut(BaseModel):
    item_id: str
    correct: bool
    expected: str
    response: str
    word_id: str
    term: str
    translation_uz: str


class VocabSessionCompleteOut(BaseModel):
    status: str
    score: float
    required_score: int
    passed: bool
    gate_opened: bool
    message_uz: str


# ---------- Tutor ----------

class ConversationCreateIn(BaseModel):
    book_id: Optional[str] = None
    lesson_id: Optional[str] = None
    exercise_id: Optional[str] = None
    title: str = Field(default="Yangi suhbat", max_length=255)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    book_id: Optional[str]
    lesson_id: Optional[str]
    created_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: str
    content: str
    model: str
    created_at: datetime


class MessageSendIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ExtraExerciseOut(BaseModel):
    exercise_type: str
    instructions: str
    topic: str
    questions: list[dict[str, Any]]


class TutorMessageOut(BaseModel):
    message: MessageOut
    extra_exercises: list[ExtraExerciseOut] = []


# ---------- Progress ----------

class DashboardOut(BaseModel):
    books_total: int
    books_ready: int
    lessons_completed: int
    lessons_total: int
    exercises_checked: int
    avg_accuracy: float
    vocab_words_total: int
    vocab_mastered: int
    vocab_learning: int
    vocab_due: int
    study_minutes_total: int
    streak_days: int
    daily_goal_minutes: int
    today_minutes: int
    activity_last_14d: list[dict[str, Any]]
    weak_topics: list[dict[str, Any]]
    strong_topics: list[dict[str, Any]]


class PlanOut(BaseModel):
    plan: str
    status: str
    max_books: int
    ai_calls_per_day: int
    ai_calls_today: int
    ai_configured: bool
    ai_provider: str


# ---------- Misc ----------

class OkOut(BaseModel):
    ok: bool = True
    message_uz: str = ""
