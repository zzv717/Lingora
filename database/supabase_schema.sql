-- ============================================================
-- Lingora — Supabase / PostgreSQL schema (production deployment)
-- ============================================================
-- This file is for the SUPABASE-NATIVE deployment path where the
-- database is accessed through Supabase with Row Level Security.
-- The default deployment (FastAPI owns the data path) uses Alembic:
--   cd backend && alembic upgrade head
--
-- Run this file in Supabase SQL Editor. It creates every table with
-- UUID PKs, FKs, indexes and OWNER-ONLY Row Level Security policies,
-- so even direct client access can never read another user's data.
-- ============================================================

CREATE TABLE users (
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	full_name VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_superuser BOOLEAN NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE TABLE profiles (
	user_id VARCHAR(36) NOT NULL, 
	interface_language VARCHAR(8) NOT NULL, 
	learning_language VARCHAR(8) NOT NULL, 
	explanation_language VARCHAR(8) NOT NULL, 
	theme VARCHAR(16) NOT NULL, 
	daily_goal_minutes INTEGER NOT NULL, 
	vocab_pass_score INTEGER NOT NULL, 
	vocabulary_gating BOOLEAN NOT NULL, 
	timezone VARCHAR(64) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_profiles_user_id ON profiles (user_id);
CREATE TABLE refresh_tokens (
	user_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	user_agent VARCHAR(255) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);
CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);
CREATE TABLE password_resets (
	user_id VARCHAR(36) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_password_resets_user_id ON password_resets (user_id);
CREATE UNIQUE INDEX ix_password_resets_token_hash ON password_resets (token_hash);
CREATE TABLE subscriptions (
	user_id VARCHAR(36) NOT NULL, 
	plan VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	current_period_start TIMESTAMP WITH TIME ZONE, 
	current_period_end TIMESTAMP WITH TIME ZONE, 
	payment_provider VARCHAR(32) NOT NULL, 
	external_ref TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_subscription_user UNIQUE (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE TABLE books (
	user_id VARCHAR(36) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	original_filename VARCHAR(512) NOT NULL, 
	storage_path VARCHAR(1024) NOT NULL, 
	file_size_bytes INTEGER NOT NULL, 
	page_count INTEGER NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	consent_confirmed_at TIMESTAMP WITH TIME ZONE, 
	description TEXT NOT NULL, 
	cover_page INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_books_user_id ON books (user_id);
CREATE TABLE activity_days (
	user_id VARCHAR(36) NOT NULL, 
	day VARCHAR(10) NOT NULL, 
	seconds INTEGER NOT NULL, 
	exercises_checked INTEGER NOT NULL, 
	answers_submitted INTEGER NOT NULL, 
	words_reviewed INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_activity_day UNIQUE (user_id, day), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_activity_days_day ON activity_days (day);
CREATE INDEX ix_activity_days_user_id ON activity_days (user_id);
CREATE TABLE usage_events (
	user_id VARCHAR(36) NOT NULL, 
	day VARCHAR(10) NOT NULL, 
	feature VARCHAR(48) NOT NULL, 
	provider VARCHAR(32) NOT NULL, 
	model VARCHAR(128) NOT NULL, 
	tokens_in INTEGER NOT NULL, 
	tokens_out INTEGER NOT NULL, 
	cost_estimate_usd FLOAT NOT NULL, 
	ok BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_usage_events_user_id ON usage_events (user_id);
CREATE INDEX ix_usage_user_day ON usage_events (user_id, day);
CREATE INDEX ix_usage_events_day ON usage_events (day);
CREATE TABLE processing_jobs (
	book_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	job_type VARCHAR(32) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	progress FLOAT NOT NULL, 
	stage VARCHAR(48) NOT NULL, 
	stage_label_uz VARCHAR(255) NOT NULL, 
	warnings JSON NOT NULL, 
	logs JSON NOT NULL, 
	error_code VARCHAR(64) NOT NULL, 
	error_message TEXT NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_jobs_book_status ON processing_jobs (book_id, status);
CREATE INDEX ix_processing_jobs_user_id ON processing_jobs (user_id);
CREATE INDEX ix_processing_jobs_book_id ON processing_jobs (book_id);
CREATE TABLE book_pages (
	book_id VARCHAR(36) NOT NULL, 
	page_number INTEGER NOT NULL, 
	width FLOAT NOT NULL, 
	height FLOAT NOT NULL, 
	text TEXT NOT NULL, 
	blocks JSON NOT NULL, 
	images JSON NOT NULL, 
	needs_ocr BOOLEAN NOT NULL, 
	ocr_used BOOLEAN NOT NULL, 
	has_warning BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_book_page UNIQUE (book_id, page_number), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE
);
CREATE INDEX ix_book_pages_book_id ON book_pages (book_id);
CREATE TABLE chapters (
	book_id VARCHAR(36) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	number VARCHAR(16) NOT NULL, 
	page_start INTEGER NOT NULL, 
	page_end INTEGER NOT NULL, 
	order_index INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE
);
CREATE INDEX ix_chapters_book_id ON chapters (book_id);
CREATE TABLE answer_keys (
	book_id VARCHAR(36) NOT NULL, 
	page_number INTEGER NOT NULL, 
	source VARCHAR(24) NOT NULL, 
	verified BOOLEAN NOT NULL, 
	raw_text TEXT NOT NULL, 
	entries JSON NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE
);
CREATE INDEX ix_answer_keys_book_id ON answer_keys (book_id);
CREATE TABLE revision_sessions (
	user_id VARCHAR(36) NOT NULL, 
	book_id VARCHAR(36), 
	status VARCHAR(24) NOT NULL, 
	focus VARCHAR(255) NOT NULL, 
	reason TEXT NOT NULL, 
	score FLOAT NOT NULL, 
	items JSON NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE SET NULL
);
CREATE INDEX ix_revision_sessions_user_id ON revision_sessions (user_id);
CREATE TABLE lessons (
	book_id VARCHAR(36) NOT NULL, 
	chapter_id VARCHAR(36), 
	title VARCHAR(512) NOT NULL, 
	topic VARCHAR(255) NOT NULL, 
	page_start INTEGER NOT NULL, 
	page_end INTEGER NOT NULL, 
	order_index INTEGER NOT NULL, 
	grammar_explanation_uz TEXT NOT NULL, 
	summary TEXT NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE, 
	FOREIGN KEY(chapter_id) REFERENCES chapters (id) ON DELETE SET NULL
);
CREATE INDEX ix_lessons_book_id ON lessons (book_id);
CREATE INDEX ix_lessons_chapter_id ON lessons (chapter_id);
CREATE TABLE exercises (
	book_id VARCHAR(36) NOT NULL, 
	lesson_id VARCHAR(36), 
	chapter_id VARCHAR(36), 
	exercise_type VARCHAR(32) NOT NULL, 
	title VARCHAR(512) NOT NULL, 
	instructions TEXT NOT NULL, 
	ref VARCHAR(64) NOT NULL, 
	page_number INTEGER NOT NULL, 
	source VARCHAR(24) NOT NULL, 
	bbox JSON, 
	topic VARCHAR(255) NOT NULL, 
	explanation_uz TEXT NOT NULL, 
	order_index INTEGER NOT NULL, 
	detection VARCHAR(16) NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE SET NULL, 
	FOREIGN KEY(chapter_id) REFERENCES chapters (id) ON DELETE SET NULL
);
CREATE INDEX ix_exercises_lesson_order ON exercises (lesson_id, order_index);
CREATE INDEX ix_exercises_book_id ON exercises (book_id);
CREATE TABLE vocabulary_words (
	book_id VARCHAR(36) NOT NULL, 
	lesson_id VARCHAR(36), 
	chapter_id VARCHAR(36), 
	term VARCHAR(255) NOT NULL, 
	translation_uz VARCHAR(512) NOT NULL, 
	definition_en TEXT NOT NULL, 
	example_sentence TEXT NOT NULL, 
	part_of_speech VARCHAR(32) NOT NULL, 
	page_number INTEGER NOT NULL, 
	source VARCHAR(16) NOT NULL, 
	needs_translation BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vocab_term UNIQUE (book_id, term), 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE SET NULL, 
	FOREIGN KEY(chapter_id) REFERENCES chapters (id) ON DELETE SET NULL
);
CREATE INDEX ix_vocabulary_words_book_id ON vocabulary_words (book_id);
CREATE TABLE vocabulary_sessions (
	user_id VARCHAR(36) NOT NULL, 
	book_id VARCHAR(36), 
	lesson_id VARCHAR(36), 
	kind VARCHAR(24) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	required_score INTEGER NOT NULL, 
	score FLOAT NOT NULL, 
	items JSON NOT NULL, 
	results JSON NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE
);
CREATE INDEX ix_vocabulary_sessions_user_id ON vocabulary_sessions (user_id);
CREATE TABLE learning_progress (
	user_id VARCHAR(36) NOT NULL, 
	lesson_id VARCHAR(36) NOT NULL, 
	book_id VARCHAR(36) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	exercises_checked INTEGER NOT NULL, 
	exercises_total INTEGER NOT NULL, 
	time_spent_seconds INTEGER NOT NULL, 
	last_page INTEGER NOT NULL, 
	vocab_gate_passed BOOLEAN NOT NULL, 
	last_visited_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_learning_progress UNIQUE (user_id, lesson_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE, 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE CASCADE
);
CREATE INDEX ix_learning_progress_lesson_id ON learning_progress (lesson_id);
CREATE INDEX ix_learning_progress_user_id ON learning_progress (user_id);
CREATE INDEX ix_learning_progress_book_id ON learning_progress (book_id);
CREATE TABLE exercise_questions (
	exercise_id VARCHAR(36) NOT NULL, 
	order_index INTEGER NOT NULL, 
	number VARCHAR(16) NOT NULL, 
	prompt TEXT NOT NULL, 
	passage TEXT NOT NULL, 
	blanks JSON NOT NULL, 
	matching_pairs JSON NOT NULL, 
	correct_answers JSON NOT NULL, 
	answer_source VARCHAR(16) NOT NULL, 
	explanation_uz TEXT NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE
);
CREATE INDEX ix_exercise_questions_exercise_id ON exercise_questions (exercise_id);
CREATE TABLE exercise_attempts (
	user_id VARCHAR(36) NOT NULL, 
	exercise_id VARCHAR(36) NOT NULL, 
	lesson_id VARCHAR(36), 
	score FLOAT NOT NULL, 
	max_score FLOAT NOT NULL, 
	percent FLOAT NOT NULL, 
	ai_used BOOLEAN NOT NULL, 
	uncertain BOOLEAN NOT NULL, 
	details JSON NOT NULL, 
	checked_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE CASCADE, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE SET NULL
);
CREATE INDEX ix_exercise_attempts_exercise_id ON exercise_attempts (exercise_id);
CREATE INDEX ix_exercise_attempts_user_id ON exercise_attempts (user_id);
CREATE INDEX ix_attempts_user_ex ON exercise_attempts (user_id, exercise_id);
CREATE TABLE vocabulary_attempts (
	user_id VARCHAR(36) NOT NULL, 
	word_id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36), 
	question_type VARCHAR(24) NOT NULL, 
	response TEXT NOT NULL, 
	is_correct BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(word_id) REFERENCES vocabulary_words (id) ON DELETE CASCADE, 
	FOREIGN KEY(session_id) REFERENCES vocabulary_sessions (id) ON DELETE SET NULL
);
CREATE INDEX ix_vocabulary_attempts_user_id ON vocabulary_attempts (user_id);
CREATE INDEX ix_vocab_attempts_user_word ON vocabulary_attempts (user_id, word_id);
CREATE INDEX ix_vocabulary_attempts_word_id ON vocabulary_attempts (word_id);
CREATE TABLE vocabulary_progress (
	user_id VARCHAR(36) NOT NULL, 
	word_id VARCHAR(36) NOT NULL, 
	ease_factor FLOAT NOT NULL, 
	interval_days FLOAT NOT NULL, 
	repetitions INTEGER NOT NULL, 
	lapses INTEGER NOT NULL, 
	total_reviews INTEGER NOT NULL, 
	correct_count INTEGER NOT NULL, 
	wrong_count INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_reviewed_at TIMESTAMP WITH TIME ZONE, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_vocab_progress UNIQUE (user_id, word_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(word_id) REFERENCES vocabulary_words (id) ON DELETE CASCADE
);
CREATE INDEX ix_vocabulary_progress_word_id ON vocabulary_progress (word_id);
CREATE INDEX ix_vocabulary_progress_due_at ON vocabulary_progress (due_at);
CREATE INDEX ix_vocabulary_progress_user_id ON vocabulary_progress (user_id);
CREATE TABLE ai_conversations (
	user_id VARCHAR(36) NOT NULL, 
	book_id VARCHAR(36), 
	lesson_id VARCHAR(36), 
	exercise_id VARCHAR(36), 
	title VARCHAR(255) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(book_id) REFERENCES books (id) ON DELETE SET NULL, 
	FOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE SET NULL, 
	FOREIGN KEY(exercise_id) REFERENCES exercises (id) ON DELETE SET NULL
);
CREATE INDEX ix_ai_conversations_user_id ON ai_conversations (user_id);
CREATE TABLE exercise_options (
	question_id VARCHAR(36) NOT NULL, 
	letter VARCHAR(4) NOT NULL, 
	text TEXT NOT NULL, 
	is_correct BOOLEAN, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(question_id) REFERENCES exercise_questions (id) ON DELETE CASCADE
);
CREATE INDEX ix_exercise_options_question_id ON exercise_options (question_id);
CREATE TABLE student_answers (
	user_id VARCHAR(36) NOT NULL, 
	question_id VARCHAR(36) NOT NULL, 
	content JSON NOT NULL, 
	is_submitted BOOLEAN NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_student_answer UNIQUE (user_id, question_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES exercise_questions (id) ON DELETE CASCADE
);
CREATE INDEX ix_student_answers_question_id ON student_answers (question_id);
CREATE INDEX ix_student_answers_user_id ON student_answers (user_id);
CREATE TABLE revision_items (
	session_id VARCHAR(36) NOT NULL, 
	item_type VARCHAR(24) NOT NULL, 
	word_id VARCHAR(36), 
	question_id VARCHAR(36), 
	payload JSON NOT NULL, 
	result BOOLEAN, 
	id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES revision_sessions (id) ON DELETE CASCADE, 
	FOREIGN KEY(word_id) REFERENCES vocabulary_words (id) ON DELETE CASCADE, 
	FOREIGN KEY(question_id) REFERENCES exercise_questions (id) ON DELETE CASCADE
);
CREATE INDEX ix_revision_items_session_id ON revision_items (session_id);
CREATE TABLE ai_messages (
	conversation_id VARCHAR(36) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	content TEXT NOT NULL, 
	model VARCHAR(128) NOT NULL, 
	tokens_in INTEGER NOT NULL, 
	tokens_out INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES ai_conversations (id) ON DELETE CASCADE
);
CREATE INDEX ix_ai_messages_conv ON ai_messages (conversation_id, created_at);
CREATE INDEX ix_ai_messages_conversation_id ON ai_messages (conversation_id);

-- ============ ROW LEVEL SECURITY ============
-- NOTE: refresh_tokens/password_resets/usage_events are server-only tables;
-- the API uses the service connection which bypasses RLS. Policies below are
-- a defense-in-depth layer for any direct client (Supabase JS) access.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_resets ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE books ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE book_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE chapters ENABLE ROW LEVEL SECURITY;
ALTER TABLE lessons ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercises ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE exercise_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocabulary_words ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocabulary_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocabulary_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE vocabulary_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_days ENABLE ROW LEVEL SECURITY;
ALTER TABLE revision_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE revision_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_owner_all" ON users
  FOR ALL USING (id::text = auth.uid()::text) WITH CHECK (id::text = auth.uid()::text);
CREATE POLICY "profiles_owner_all" ON profiles
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "refresh_tokens_owner_all" ON refresh_tokens
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "password_resets_owner_all" ON password_resets
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "subscriptions_owner_all" ON subscriptions
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "books_owner_all" ON books
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "processing_jobs_owner_all" ON processing_jobs
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "book_pages_owner_all" ON book_pages
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "chapters_owner_all" ON chapters
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "lessons_owner_all" ON lessons
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "exercises_owner_all" ON exercises
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "exercise_questions_owner_all" ON exercise_questions
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "exercise_options_owner_all" ON exercise_options
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "answer_keys_owner_all" ON answer_keys
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "student_answers_owner_all" ON student_answers
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "exercise_attempts_owner_all" ON exercise_attempts
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "vocabulary_words_owner_all" ON vocabulary_words
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "vocabulary_sessions_owner_all" ON vocabulary_sessions
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "vocabulary_attempts_owner_all" ON vocabulary_attempts
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "vocabulary_progress_owner_all" ON vocabulary_progress
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "learning_progress_owner_all" ON learning_progress
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "activity_days_owner_all" ON activity_days
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "revision_sessions_owner_all" ON revision_sessions
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "revision_items_owner_all" ON revision_items
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "ai_conversations_owner_all" ON ai_conversations
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "ai_messages_owner_all" ON ai_messages
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);
CREATE POLICY "usage_events_owner_all" ON usage_events
  FOR ALL USING (user_id::text = auth.uid()::text) WITH CHECK (user_id::text = auth.uid()::text);

DROP POLICY IF EXISTS "book_pages_owner_all" ON book_pages;
CREATE POLICY "book_pages_owner_all" ON book_pages
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = book_pages.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = book_pages.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "chapters_owner_all" ON chapters;
CREATE POLICY "chapters_owner_all" ON chapters
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = chapters.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = chapters.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "lessons_owner_all" ON lessons;
CREATE POLICY "lessons_owner_all" ON lessons
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = lessons.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = lessons.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "exercises_owner_all" ON exercises;
CREATE POLICY "exercises_owner_all" ON exercises
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = exercises.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = exercises.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "answer_keys_owner_all" ON answer_keys;
CREATE POLICY "answer_keys_owner_all" ON answer_keys
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = answer_keys.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = answer_keys.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "vocabulary_words_owner_all" ON vocabulary_words;
CREATE POLICY "vocabulary_words_owner_all" ON vocabulary_words
  FOR ALL USING (EXISTS (SELECT 1 FROM books b WHERE b.id = vocabulary_words.book_id AND b.user_id::text = auth.uid()::text))
  WITH CHECK (EXISTS (SELECT 1 FROM books b WHERE b.id = vocabulary_words.book_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "exercise_questions_owner_all" ON exercise_questions;
CREATE POLICY "exercise_questions_owner_all" ON exercise_questions
  FOR ALL USING (EXISTS (SELECT 1 FROM exercises e JOIN books b ON b.id = e.book_id WHERE e.id = exercise_questions.exercise_id AND b.user_id::text = auth.uid()::text)) WITH CHECK (EXISTS (SELECT 1 FROM exercises e JOIN books b ON b.id = e.book_id WHERE e.id = exercise_questions.exercise_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "exercise_options_owner_all" ON exercise_options;
CREATE POLICY "exercise_options_owner_all" ON exercise_options
  FOR ALL USING (EXISTS (SELECT 1 FROM exercise_questions eq JOIN exercises e ON e.id = eq.exercise_id JOIN books b ON b.id = e.book_id WHERE eq.id = exercise_options.question_id AND b.user_id::text = auth.uid()::text)) WITH CHECK (EXISTS (SELECT 1 FROM exercise_questions eq JOIN exercises e ON e.id = eq.exercise_id JOIN books b ON b.id = e.book_id WHERE eq.id = exercise_options.question_id AND b.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "revision_items_owner_all" ON revision_items;
CREATE POLICY "revision_items_owner_all" ON revision_items
  FOR ALL USING (EXISTS (SELECT 1 FROM revision_sessions rs WHERE rs.id = revision_items.session_id AND rs.user_id::text = auth.uid()::text)) WITH CHECK (EXISTS (SELECT 1 FROM revision_sessions rs WHERE rs.id = revision_items.session_id AND rs.user_id::text = auth.uid()::text));
DROP POLICY IF EXISTS "ai_messages_owner_all" ON ai_messages;
CREATE POLICY "ai_messages_owner_all" ON ai_messages
  FOR ALL USING (EXISTS (SELECT 1 FROM ai_conversations c WHERE c.id = ai_messages.conversation_id AND c.user_id::text = auth.uid()::text)) WITH CHECK (EXISTS (SELECT 1 FROM ai_conversations c WHERE c.id = ai_messages.conversation_id AND c.user_id::text = auth.uid()::text));
