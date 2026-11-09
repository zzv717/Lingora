# Lingora — DEVELOPMENT STATUS

Oxirgi yangilanish: 2026-11-09 · Holat: **Barcha fazalar (1–8) to'liq auditdan o'tgan, mustahkamlangan va 63/63 testlar bilan tasdiqlangan**

## ✅ Yakunlangan funksiyalar va Xavfsizlik Auditi

### 1. Xavfsizlik va Auth
- [x] **Password Reset Token xavfsizligi**: Production rejimida token API javobida va loglarda hech qachon oshkor bo'lmaydi. Bir martalik ishlatiladi va avvalgi barcha faol sessiyalarni bekor qiladi.
- [x] **Tutor & Mashq IDOR himoyasi**: Foydalanuvchi faqat o'ziga tegishli kitob, dars yoki mashq bo'yicha suhbat ochishi mumkin (`_verify_tutor_scope`). Boshqa foydalanuvchilar resurslari 404/403 bilan qat'iy bloklanadi.
- [x] **Lug'at darvozasi (Vocabulary Gate)**: Backend darajasida `LESSON_LOCKED` 403 xatosi bilan to'liq himoyalangan (faqat UI'da tugmani o'chirib qo'yish bilan cheklanmagan).
- [x] **Atomik Refresh Token rotatsiyasi**: Poyga (race condition) va token o'g'irlanishini aniqlash (`replay detection`) bilan to'liq himoyalangan.
- [x] **Rate Limiting**: Redis qo'llab-quvvatlaydi, reverse proxy uchun `trusted_proxies` orqali IP spoofing'dan himoyalangan.
- [x] **Production SECRET_KEY**: Ishlab chiqarish rejimida bo'sh yoki xavfli standart kalitda server darhol to'xtaydi (fail-fast).
- [x] **Xavfsiz fayl boshqaruvi**: Path traversal hujumlariga qarshi tekshiruv va atomik fayllarni o'chirish.

### 2. Database & Supabase RLS
- [x] Barcha 27 ta jadval uchun PostgreSQL DDL va to'liq RLS siyosatlari (`database/supabase_schema.sql`).
- [x] Custom JWT va Supabase Auth o'rtasidagi arxitektura mosligi (`lingora_current_user_id()` funksiyasi orqali).
- [x] PostgreSQL drayverlari (`psycopg2-binary`, `asyncpg`) to'liq qo'shilgan.
- [x] Docker Compose: PostgreSQL 16, Redis 7, Celery Worker, FastAPI backend va Next.js frontend to'liq integratsiyasi.

### 3. PDF Interaktiv Tahlil va Grading
- [x] PDF.js va PyMuPDF yordamida original sahifa koordinatalari (`bbox`) bo'yicha interaktiv bo'shliqlar joylashtiriladi.
- [x] Skanerlangan sahifalar uchun OCR holati haqiqiy va xolis ko'rsatiladi.
- [x] Qayta tahlil qilinganda ma'lumotlar xavfsiz transactional tarzda qayta tiklanadi.
- [x] Baholash ustuvorligi: Kitob javoblar kaliti > Deterministik qoidalar > AI baholash > Tekshirilmagan (unverified).
- [x] Ko'p bo'shliqli mashqlar va muqobil to'g'ri javoblar to'liq qo'llab-quvvatlanadi.

### 4. Vocabulary, Spaced Repetition (SM-2) & Revision
- [x] Kitobdagi barcha so'zlar to'liq qamrab olinadi va kontekstiga qarab ajratiladi.
- [x] 6 xil savol turlari, aralashtirilgan variantlar va majburiy yozma eslab qolish.
- [x] Xato qilingan so'zlar avtomatik ravishda dars oxiriga qayta qo'shiladi (`requeued_item`).
- [x] SM-2 algoritmi: qiyin yoki xato qilingan so'zlarda interval 0 ga tushib darhol qayta navbatga qo'yiladi.
- [x] Server-side deterministik baholanadigan maxsus takrorlash sessiyalari (`revision sessions`).

### 5. Progress, Dashboard & Frontend
- [x] Heartbeat vaqt hisobi: soxtalashtirishdan himoyalangan (ko'pi bilan 60s/so'rov, kuniga 10 soat limit), foydalanuvchi profilidagi vaqt zonasi (`timezone`) hisobga olinadi.
- [x] Frontend to'liq TypeScript va Next.js 14 optimallashtirilgan holatda qurilgan (0 xato).
- [x] Barcha sahifalar, dark/light rejim, PWA manifest va offline pdf.worker to'liq ishlaydi.

### 6. Testlar va Sifat Kafolati
- [x] **Backend Pytest to'plami: 63/63 PASS (100%)**
- [x] **E2E Smoke: 13/13 PASS (100%)**
- [x] **Frontend Build: 14/14 static va dynamic routelar muvaffaqiyatli qurildi**
- [x] **GitHub Actions CI workflow: `.github/workflows/ci.yml` yaratildi**

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
