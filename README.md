# Lingora — AI-Powered Interactive Learning Platform

**Lingora** ingliz tili o'rganish uchun an'anaviy PDF darsliklarni interaktiv, avtomatik
tekshiriladigan raqamli o'quv muhitiga aylantiradi. Foydalanuvchi kitobini yuklaydi — AI
kitob tuzilmasini (boblar, darslar, mashqlar, lug'at, javoblar kaliti) ajratib oladi va
uni to'ldiriladigan mashqlarga aylantiradi.

> **Falsafa:** Kitobni ALMASHTIRMANG — uni interaktiv AI qudratiga ega o'quv tajribasiga AYLANTIRING.

---

## ✨ Imkoniyatlar

| Modul | Tavsif |
|---|---|
| 📖 **AI Book Analyzer** | PDF (matnli/skaner/aralash) → boblar, darslar, 8 xil mashq turi, lug'at, javoblar kaliti. Joyedagi (rule-based) detektor + ixtiyoriy AI boyitish. Progress real vaqtda o'zbek tilida ko'rinadi. |
| 📚 **Interactive Reader** | Asl PDF sahifasi pdf.js bilan chiziladi; bo'sh joylar (`____`) aynan kitobdagi koordinatalarida to'ldiriladigan inputlarga aylanadi. Test, moslashtirish, tarjima, yozish, to'g'ri/xato mashqlari panellari. Javoblar avtosaqlanadi — sahifa yangilansa ham yo'qolmaydi. |
| ✅ **AI Exercise Checker** | Baholash ustuvorligi: **1)** kitob kaliti → **2)** deterministik qoidalar → **3)** kontekstli AI → **4)** noaniq = "tekshiruv kerak". Muqobil to'g'ri javoblar qabul qilinadi. Xatolar o'zbek tilida tushuntiriladi. AI sozlanmagan bo'lsa — soxta baholash EMAS, ochiq "AI kerak" holati. |
| 🧠 **Vocabulary Challenge** | Aralash savol turlari (tanlash, yozma eslash, imlo, tinglash-TTS, gap to'ldirish), randomizatsiya, xato so'zlarni qayta berish, SM-2 spaced repetition, darslararo **lug'at darvozasi** (keyingi dars faqat test o'tilgach ochiladi). |
| 🤖 **AI Personal Tutor** | Kitob/dars/mashq/xatolar kontekstida ishlaydigan chat. O'zbek tilida tushuntiradi. Qo'shimcha mashqlar generatsiyasi. Ovozli kiritish (Web Speech API). |
| 📊 **Progress & Revision** | Kunlik seriya, faollik grafiklari, zaif/kuchli grammatika mavzulari, lug'at masterligi. Real natijalar asosida **aqlli takrorlash** seanslari. |
| 🔐 **Security** | JWT + refresh rotatsiyasi, scrypt parollar, mulkdorlik tekshuruvi (boshqa foydalanuvchi kitobi = 404), private storage, rate limiting, yuklash validatsiyasi, muallif huquqi roziligi, to'liq hisob o'chirish. |
| 💳 **Subscription-ready** | `free/pro/premium` reja limitlari va AI usage hisoblagichi mavjud. **MVP'da to'lovlar yo'q** — faqat arxitektura tayyor. |

---

## 🏗 Arxitektura

```
lingora/
├── backend/            # FastAPI (Python) — mustaqil REST API (mobil/desktop uchun ham xizmat qiladi)
│   ├── app/
│   │   ├── api/v1/     # auth, books, exercises, vocabulary, tutor, progress
│   │   ├── services/   # pipeline, structure_detector, grading, vocab_engine, srs,
│   │   │   └── ai/     # provider-agnostic AI qatlami (OpenAI-compatible/Anthropic/Gemini)
│   │   ├── models/     # SQLAlchemy 2.0 — 27 jadval (UUID, FK, indekslar)
│   │   └── core/       # config (env), security, rate limit, errors
│   ├── alembic/        # DB migratsiyalari
│   └── tests/          # 48+ pytest (haqiqiy PDF'lar bilan E2E)
├── frontend/           # Next.js 14 + TypeScript + Tailwind (PWA manifest)
│   └── src/app/        # login, dashboard, books, reader, vocabulary, practice, tutor, progress, settings
├── database/
│   └── supabase_schema.sql   # Supabase-native deploy uchun DDL + RLS siyosatlari
├── docs/               # DEPLOYMENT.md, API.md, ARCHITECTURE.md
├── docker-compose.yml
└── .env.example
```

**Muhim arxitektura qarorlari:**
- **Backend mustaqil** — kelajakdagi React Native / Tauri ilovalari xuddi shu API'dan foydalanadi.
- **AI ixtiyoriy**: AI kaliti bo'lmasa ham kitob tahlili (deterministik) va kalitli mashqlarni
  baholash to'liq ishlaydi. AI talab qiladigan funksiyalar (tutor, ochiq javoblarni baholash,
  tarjimalar) ochiq 503 `AI_NOT_CONFIGURED` qaytaradi — hech qachon soxta javob berilmaydi.
- **DB**: prod = PostgreSQL (Supabase), lokal = SQLite (`DATABASE_URL` orqali).
- **Queue**: `TASK_BACKEND=inline` (Thread pool, har joyda ishlaydi) yoki `celery` (Redis bilan).

---

## 🚀 Ishga tushirish (lokal)

### Talablar: Python 3.11+, Node 18+

```bash
# 1) Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env                              # kerakli env'larni to'ldiring
uvicorn app.main:app --reload --port 8000            # http://localhost:8000/docs

# 2) Frontend (yangi terminal)
cd frontend
npm install
BACKEND_URL=http://127.0.0.1:8000 npm run dev        # http://localhost:3000
```

Brauzerda `http://localhost:3000` → ro'yxatdan o'ting → kitob yuklang.

### Testlar

```bash
cd backend
python -m pytest tests/ -v        # 48 test: auth, permissions, pipeline, grading, vocab, progress
```

Testlar haqiqiy PyMuPDF bilan generatsiya qilingan PDF darsliklar ustida to'liq pipeline'ni,
mallkdorlik izolyatsiyasini, baholash qoidalari va SM-2 jadvalini tekshiradi.

---

## 🐳 Docker

```bash
cp .env.example .env     # SECRET_KEY va (ixtiyoriy) AI kalitlarini to'ldiring
docker compose up --build
# frontend: http://localhost:3000  ·  api: http://localhost:8000/docs  ·  postgres: 5432
```

---

## 🔑 AI provayderlarni sozlash

`.env` da **bittasini** tanlang:

```env
# OpenAI yoki mos sondagi (Groq, OpenRouter, Ollama...)
AI_PROVIDER=openai_compatible
AI_API_KEY=sk-...
AI_BASE_URL=https://api.openai.com/v1     # Groq: https://api.groq.com/openai/v1
AI_MODEL=gpt-4o-mini

# Anthropic
# AI_PROVIDER=anthropic
# AI_MODEL=claude-3-5-sonnet-latest

# Google Gemini
# AI_PROVIDER=gemini
# AI_MODEL=gemini-2.0-flash
```

Kalitlar **faqat backend** env'ida saqlanadi, frontend/hech qanday DB'da emas.

### OCR (skanerlangan PDF'lar uchun, ixtiyoriy)

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-uzb
pip install pytesseract
```

---

## 📖 Hujjatlar

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Supabase/VPS/Docker deploy, env'lar to'liq ro'yxati
- [docs/API.md](docs/API.md) — endpoint'lar
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — pipeline va ma'lumot modeli
- [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) — nima tayyor, nima navbatda

---

## 📜 Muallif huquqi

Foydalanuvchi faqat o'zi qayta ishlash huquqiga ega bo'lgan kitoblarni yuklaydi (yuklashda
tasdiqlaydi). Kitoblar **private bucket**'da saqlanadi, faqat mulkdori ko'radi va hech qachon
ommaga tarqatilmaydi. Har qanday kitob va uning barcha ma'lumotlarini o'chirish mumkin.
