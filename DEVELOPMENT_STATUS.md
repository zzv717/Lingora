# Lingora — DEVELOPMENT STATUS

Oxirgi yangilanish: 2026-11-07 · Holat: **MVP barcha fazalari ishlaydi (Fazalar 1–7), 8-faza (deploy/docs) tayyor**

## ✅ Yakunlangan funksiyalar

### Fazalar 1–2: Foundation + AI Book Analyzer
- [x] FastAPI backend, mustaqil REST API (`/api/v1`), OpenAPI docs (`/docs`)
- [x] 27 jadvallik PostgreSQL sxema (UUID PK, FK, indekslar, timestamps), Alembic migratsiyasi
- [x] Supabase-native sxema + 37 ta owner-only RLS siyosati (`database/supabase_schema.sql`)
- [x] Auth: ro'yxatdan o'tish, login, **refresh rotatsiyasi**, parol o'zgartirish, reset (SMTP ixtiyoriy — sozlanmagan dev rejimda havola ochiq beriladi, soxta "yuborildi" xabari yo'q), hisobni to'liq o'chirish
- [x] Xavfsiz yuklash: PDF magic-bytes, hajm/sahifa limitlari, muallif huquqi roziligi majburiy, plan limitlari
- [x] Pipeline: matn ajratish (PyMuPDF, koordinatalar bilan) → OCR (mavjud bo'lsa) → struktura detektor → saqlash → ixtiyoriy AI boyitish → validatsiya → ready
- [x] Struktura detektori (deterministik, AI'siz ishlaydi): boblar/unitlar, darslar, 8 xil mashq turi, savollar, MC opsiyalari, moslashtirish juftliklari (2 ustun + chiziqcha), lug'at ro'yxatlari, javoblar kaliti (global ketma-ketlik + ref bo'yicha)
- [x] Har savol uchun PDF-koordinatali bo'sh joy bboxlari → reader overlaylari uchun
- [x] Processing progress: stage'lar o'zbek tilida, polling API, server restartida "qotib qolgan" joblar ochiq `INTERRUPTED` deb belgilanadi
- [x] OCR binary yo'q bo'lsa: sahifa ochiq `OCR_UNAVAILABLE` warning bilan chetlab o'tiladi (hech narsa o'ylab topilmaydi)

### Fazalar 3–4: Interactive Reader + AI Assessment
- [x] pdf.js renderer (worker bundled, CDN yo'q — offline preview ishlaydi)
- [x] Asl PDF sahifasi USTIDA bo'sh joy inputlari (ajratib olingan bbox koordinatalarida)
- [x] Barcha mashq turlari uchun interaktiv panellar: MC, moslashtirish (tanlov-based, touch-friendly), tarjima, yozish, to'g'ri/xato, gap to'ldirish
- [x] **Avtosaqlash** (debounce) + sahifa yangilanganda javoblarni tiklash (E2E test bilan tasdiqlangan)
- [x] Baholash ustuvorligi: kitob kaliti → deterministik (normalizatsiya, raqamli, harf, juftlik, 1-xato tolerantligi) → AI (bitta strukturli JSON chaqiruvi, confidence) → noaniq = `unverified` (ochiq aytiladi)
- [x] Muqobil javoblar, katta-kichik harf/belgisiz solishtirish, ko'p bo'shliqli savollar (kalit so'zlarga bo'lib baholanadi)
- [x] Yozish/tarjima: AI talab qilinadi; AI yo'q bo'lsa "tekshirilmagan" + izoh (soxta baholash yo'q)
- [x] AI ishlatilganda usage tracking + kunlik plan limitlari + xarajat bahosi

### Faza 5: Vocabulary
- [x] Kitob/dars lug'atlari; AI sozlanganda avtomatik o'zbekcha tarjima
- [x] Challenge generator: 7 savol turi, aralash, random tartib/opsiyalar, yozma recall MAJBURIY
- [x] Xato so'zlar seans oxirida qayta beriladi; birinchi urinish bahoga asos
- [x] SM-2 spaced repetition (toza funksiya, unit-testlangan), due-tracking, lapses, masterlik
- [x] **Lug'at darvozasi**: keyingi dars faqat oldingi dars testi o'tilgach (sozlanadigan ball, default 80%) ochiladi
- [x] Tinglash savollari brauzer TTS orqali (cloud yo'q)

### Faza 6: AI Tutor
- [x] Kontekstli chat: kitob + dars + mashq + oxirgi xatolar DB'dan yig'iladi
- [x] O'zbek tili system prompt, kitob kontentini o'ylab topish taqiqlangan
- [x] Qo'shimcha mashq generatsiyasi (strukturli, validatsiyali)
- [x] Suhbatlar/messages saqlanadi; ovozli kiritish (Web Speech API), AI sozlanmagan bo'lsa ochiq banner
- [x] TTS: brauzer native (offline)

### Faza 7: Progress
- [x] Dashboard: kitoblar, darslar, mashqlar, aniqlik, lug'at masterligi, o'qish vaqti, kunlik seriya, 14 kunlik faollik grafigi
- [x] Zaif/kuchli mavzular (real urinishlar statistikasi asosida)
- [x] Heartbeat (o'qish vaqti hisoblanadi), kunlik maqsad progressi
- [x] Aqlli takrorlash: zaif mavzular savollari + SM-2 due so'zlar + muvaffaqiyatsiz testlar → revision seans

### Faza 8: Production readiness
- [x] 48 pytest: auth, rotatsiya, **mulkdorlik izolyatsiyasi**, yuklash validatsiyasi, to'liq pipeline (haqiqiy PDF), OCR halolligi, grading qoidalari, vocab randomizatsiya/darvoza/SM-2, dashboard, AI honesty
- [x] E2E smoke (Next proxy → API): **18/18** tekshiruv
- [x] Docker (backend, frontend, compose + postgres), `.env.example`, deploy hujjatlari
- [x] Security: scrypt, JWT, refresh hash saqlash, rate limiting, xavfsizlik headerlari, path-traversal himoyasi, SQL ORM orqali, xatolarda stack-trace oshkor qilinmaydi

## ⚠️ Muhit cheklovlari (halol holat)

| Cheklov | Holat | Yechni |
|---|---|---|
| AI kalitlari yo'q | Deterministik tahlil/grading ishlaydi; tutor/ochiq baholash/tarjima 503 `AI_NOT_CONFIGURED` | `.env` ga kalit qo'yish kifoya — kod to'liq tayyor |
| Tesseract binary yo'q | Skaner sahifalar ochiq warning bilan o'tkazib yuboriladi | `apt install tesseract-ocr` + `pip install pytesseract` |
| Redis/Celery yo'q (sandbox) | `TASK_BACKEND=inline` (thread-pool) ishlaydi | Prod: `TASK_BACKEND=celery` + `REDIS_URL` |
| SQLite (sandbox dev) | PostgreSQL bilan bir xil modellar; `DATABASE_URL` almashadi | Supabase pooler URL |
| Supabase credentials yo'q | Lokal storage backend ishlaydi; Supabase Storage adapteri kodda tayyor | `STORAGE_BACKEND=supabase` + keylar |
| VoIP mikrofon preview iframe'da bloklangan | STT real browser/deployda ishlaydi, previewda tugma ko'rinmaydi | — |

## 🧪 Kerakli tashqi credentiallar (ishlatish uchun ixtiyoriy)

| Env | Maqsad | Bo'lmasa |
|---|---|---|
| `AI_PROVIDER`+`AI_API_KEY`+`AI_MODEL` | Tutor, ochiq javollar bahosi, tarjimalar, grammatika tushuntirishlari | Deterministik rejim (qolgan hammasi ishlaydi) |
| `DATABASE_URL` | Prod: Supabase PostgreSQL | SQLite (dev) |
| `SUPABASE_URL`+`SUPABASE_SERVICE_KEY` | Supabase Storage (private bucket) | Lokal disk storage |
| `SMTP_*` | Parol tiklash emaili | Dev rejimda havola UI'da ko'rsatiladi |
| `REDIS_URL` | Celery queue + distributed rate limit | Inline thread pool |

## 🔜 Keyingi qadamlar (tavsiya)
1. Production deploy (VPS yoki Railway/Fly) + Supabase Postgres ulash
2. AI kalit ulash → tutor va tarjimalarni yoqish
3. Tesseract o'rnatish → skaner kitoblar
4. Kelajakda: React Native ilova (shu API ustidan), to'lov provayderi (subscription schema tayyor), qo'shimcha tillar
