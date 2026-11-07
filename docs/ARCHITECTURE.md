# Architecture

## Umumiy manzara

```
┌─────────────┐     same-origin proxy      ┌──────────────────┐
│  Browser     │ ──── /backend/api/v1/* ──▶ │  FastAPI (REST)  │
│  Next.js 14  │                            │  ├─ Auth (JWT)   │
│  pdf.js UI   │                            │  ├─ Pipeline     │
└─────────────┘                             │  ├─ Grading      │
                                            │  ├─ Vocab/SM-2   │
                                            │  └─ AI layer ────┼──▶ OpenAI/Anthropic/Gemini
┌─────────────┐                            └───────┬──────────┘
│ RN / Tauri  │ ────────── xuddi shu REST ────────▶│
└─────────────┘                                    ▼
                                        PostgreSQL (Supabase) / SQLite
                                        Storage: local disk / Supabase bucket
```

Frontend biznes-logikani O'ZIDA saqlamaydi — u faqat API klienti. Shu sababli kelajakdagi
mobil/desktop ilovalar backend'ni o'zgartirmasin ishlaydi.

## AI Book Analyzer pipeline

```
PDF bytes
  │ validate (magic, size, pages)
  ▼
extract per page (PyMuPDF): lines + bboxes + font sizes + images
  │ minimal matn → OCR (pytesseract, ixtiyoriy) — bo'lmasa: page-level warning
  ▼
structure detector (deterministik):
  chapters (UNIT/Chapter + shrift) → lessons (Lesson/Dars/...) →
  exercises (Exercise/Task/Mashq) → questions (raqamli bandlar) →
  MC options (A) B) C)) → blanks (____ + bbox) → matching (2-ustun/chiziqcha) →
  vocab ro'yxatlari (term — tarjima) → answer key (Answer key/Answers/Javoblar)
  ▼
persist: chapters, lessons, exercises, questions(+blanks bbox), options,
         vocabulary, answer_keys, book_pages
  ▼
[AI configured bo'lsa] enrich: yetishmagan javoblar, grammatika tushuntirishlari (uz),
  lug'at tarjimalari — hammasi pydantic bilan validatsiya, xato bo'lsa rule-natija saqlanadi
  ▼
validate + warnings (ANSWERS_UNKNOWN, OCR_UNAVAILABLE, KEY_PARTIAL...) → book.status=ready
```

Progress `processing_jobs` jadvalida yashaydi — UI polling orqali o'zbek tilida ko'rsatadi.

## Baholash (grading) ustuvorligi

1. **Kitob kaliti** (`answer_source=key`) — deterministik solishtirish (normalizatsiya,
   raqamlar, MC harflar, juftliklar, ko'p bo'shliqlar, ≤1 xato uzoq so'zlarda).
2. **Deterministik qoidalar** — kalit yo'q, lekin turi aniq (MC opsiyasi belgilangan...).
3. **AI** — ochiq javoblar (tarjima/yozish/o'qish) va noaniq holatlar; bitta strukturli JSON
   chaqiruv, `confidence<0.7` yoki `null` → **noaniq**, hech qachon "authoritative" ko'rsatilmaydi.
4. **Noaniq** — `correct=null`, foydalanuvchiga "AI kerak / murabbiy tekshirsin" deb ochiq aytiladi.

AI sozlanmagan bo'lsa 3-4 bosqich ochiq halol holatda qoladi (soxta baholash YO'Q).

## Lug'at darvozasi va SM-2

- Har dars lug'ati uchun `lesson_gate` testi: aralash 7 tur, random tartib, yozma recall,
  xato so'z qayta beriladi, birinchi urinish bahoga asos, o'tish balli profil sozlamasida.
- `learning_progress.vocab_gate_passed` keyingi darsni ochadi (o'chiriladigan sozlama).
- Har javob SM-2 bo'yicha `vocabulary_progress`ni yangilaydi (ease, interval, due, lapses).
  Due so'zlar navbatdagi seanslarga ustuvor qo'shiladi.

## Xavfsizlik modeli

- Auth: scrypt parollar, access JWT (30m) + refresh rotatsiya (hash bazada, revoke qilinadi).
- Mulkdorlik: har so'rovda ownership tekshiruvi — boshqa user resursi **404** (mavjudligi oshkor qilinmaydi).
- RLS: Supabase-native yo'lda ham jadval darajasida owner-only siyosatlar (defense-in-depth).
- Yuklash: magic bytes, hajm/sahifa cap, consent majburiy, fayl nomi sanitizatsiya, UUID yo'llar.
- Storage: private; fayl faqat auth'dan o'tgan mulkdorga stream qilinadi.
- Rate limit: IP/user + bucket asosida (global + endpoint-specific), 429 Uzbek xabar bilan.
- Xatolar: stack trace oshkor qilinmaydi; kodlar (`AI_NOT_CONFIGURED`, `PLAN_LIMIT`, ...) bilan.

## Migratsiyalar

- Alembic (backend/alembic) — `alembic upgrade head`.
- `database/supabase_schema.sql` — Supabase SQL Editor uchun to'liq DDL + RLS.
