// Shared API types mirroring the FastAPI schemas.
export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

export interface Profile {
  interface_language: string;
  learning_language: string;
  explanation_language: string;
  theme: "light" | "dark" | "system";
  daily_goal_minutes: number;
  vocab_pass_score: number;
  vocabulary_gating: boolean;
  timezone: string;
}

export interface Book {
  id: string;
  title: string;
  original_filename: string;
  status: "uploading" | "uploaded" | "processing" | "ready" | "failed";
  page_count: number;
  file_size_bytes: number;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  book_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  stage: string;
  stage_label_uz: string;
  warnings: { page: number; code: string; message_uz: string }[];
  error_code: string;
  error_message: string;
}

export interface Chapter {
  id: string;
  title: string;
  kind: string;
  number: string;
  page_start: number;
  page_end: number;
  order_index: number;
}

export interface Lesson {
  id: string;
  chapter_id: string | null;
  title: string;
  topic: string;
  page_start: number;
  page_end: number;
  order_index: number;
  grammar_explanation_uz: string;
  summary: string;
}

export interface LessonProgress {
  status: string;
  exercises_checked: number;
  time_spent_seconds: number;
  last_page: number;
  last_visited_at: string | null;
  vocab_gate_passed: boolean;
  has_vocabulary: boolean;
  locked: boolean;
}

export interface Structure {
  book: Book;
  chapters: Chapter[];
  lessons: Lesson[];
  lessons_progress: Record<string, LessonProgress>;
  coverage: {
    exercises: number;
    questions: number;
    questions_with_key: number;
    vocabulary: number;
    pages_ocr_used: number;
    pages_needing_ocr: number;
    pages_with_warnings: number;
    ocr_available: boolean;
  };
  answer_key_pages: number[];
}

export interface Option {
  id: string;
  letter: string;
  text: string;
  is_correct: boolean | null;
}

export interface Question {
  id: string;
  number: string;
  order_index: number;
  prompt: string;
  passage: string;
  blanks: { id: string; bbox: number[] | null }[];
  matching_pairs: { left: string; right: string }[];
  options: Option[];
}

export interface Exercise {
  id: string;
  book_id: string;
  lesson_id: string | null;
  exercise_type: string;
  title: string;
  instructions: string;
  ref: string;
  page_number: number;
  bbox: { x0: number; y0: number; x1: number; y1: number } | null;
  topic: string;
  explanation_uz: string;
  order_index: number;
  detection: string;
  needs_review: boolean;
  questions: Question[];
}

export interface Verdict {
  question_id: string;
  number: string;
  correct: boolean | null;
  confidence: number;
  given: string;
  expected: string;
  explanation_uz: string;
  source: string;
  grammar_note_uz: string;
}

export interface CheckResult {
  attempt_id: string;
  score: number;
  max_score: number;
  percent: number;
  uncertain: boolean;
  ai_used: boolean;
  verdicts: Verdict[];
  overall_feedback_uz: string;
}

export interface VocabWord {
  id: string;
  term: string;
  translation_uz: string;
  definition_en: string;
  example_sentence: string;
  part_of_speech: string;
  page_number: number;
  lesson_id: string | null;
  needs_translation: boolean;
}

export interface VocabItem {
  item_id: string;
  word_id: string;
  type: string;
  prompt: string;
  options: { key: string; text: string }[];
  audio_text: string;
  sentence: string;
  hint: string;
}

export interface VocabSession {
  id: string;
  kind: string;
  status: string;
  required_score: number;
  score: number;
  total_items: number;
  answered_items: number;
  items: VocabItem[];
}

export interface VocabAnswerResult {
  item_id: string;
  correct: boolean;
  expected: string;
  response: string;
  word_id: string;
  term: string;
  translation_uz: string;
  requeued_item?: VocabItem | null;
}

export interface Dashboard {
  books_total: number;
  books_ready: number;
  lessons_completed: number;
  lessons_total: number;
  exercises_checked: number;
  avg_accuracy: number;
  vocab_words_total: number;
  vocab_mastered: number;
  vocab_learning: number;
  vocab_due: number;
  study_minutes_total: number;
  streak_days: number;
  daily_goal_minutes: number;
  today_minutes: number;
  activity_last_14d: { day: string; minutes: number; exercises: number }[];
  weak_topics: { topic: string; attempts: number; accuracy: number }[];
  strong_topics: { topic: string; attempts: number; accuracy: number }[];
}

export interface Conversation {
  id: string;
  title: string;
  book_id: string | null;
  lesson_id: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  model: string;
  created_at: string;
}

export interface ExtraExercise {
  exercise_type: string;
  instructions: string;
  topic: string;
  questions: {
    number: string;
    prompt: string;
    options: { letter: string; text: string }[];
    correct_answers: string[];
  }[];
}

export interface ApiErrorBody {
  error: { code: string; message_uz: string; details?: unknown };
}
