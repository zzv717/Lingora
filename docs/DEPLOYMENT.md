# Deployment Guide

Lingora'ni ishlab chiqarishga chiqarishning 2 ta yo'li bor.

---

## 1-variant: VPS (Docker Compose) — tavsiya etiladi

### Talablar
- Ubuntu 22.04+ VPS (2 vCPU / 2GB yetadi MVP uchun)
- Domain (ixtiyoriy, HTTPS uchun Caddy/nginx)

### Qadamlar

```bash
# 1. Repo
git clone <your-repo-url> lingora && cd lingora

# 2. Environment
cp .env.example .env
nano .env   # quyidagi "Env o'zgaruvchilar" bo'limiga qarang

# 3. Kerakli minimal sozlamalar
#    SECRET_KEY:  python3 -c "import secrets; print(secrets.token_hex(32))"
#    CORS_ORIGINS: https://sizning-domain.uz
#    DATABASE_URL: postgres yoki Supabase (pastda)

# 4. Ishga tushirish
docker compose up -d --build
docker compose exec backend alembic upgrade head   # birinchi marta

# 5. Tekshirish
curl http://localhost:8000/api/v1/health
curl http://localhost:3000
curl http://localhost:3000/backend/api/v1/health  # frontend proxy orqali API
```

### HTTPS (Caddy misol)

```
lingora.example.uz {
    reverse_proxy /backend/* localhost:3000
    reverse_proxy localhost:3000
}
```

---

## 2-variant: Supabase + Railway/Fly.io

### Supabase sozlash

1. [supabase.com](https://supabase.com) → New project
2. **Database**: Project Settings → Database → Connection string (Pooler) →
   `DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`
3. **Sxema**: FastAPI backend uchun `alembic upgrade head` ishlating.
   `database/supabase_schema.sql` alohida Supabase-native sxema bo'lib, FastAPI
   Alembic sxemasi bilan o'zaro almashtirilmaydi; ikkalasini bir bazada qo'llamang.
   Supabase `public` sxemasi Data API orqali ko'rinishi mumkin: barcha yangi
   FastAPI jadvallarida RLS yoqing va `anon`, `authenticated` hamda `PUBLIC`
   rollaridan bevosita jadval ruxsatlarini olib tashlang. FastAPI ma'lumotlarga
   o'zining server tomondagi PostgreSQL roli orqali murojaat qiladi, foydalanuvchi
   huquqlarini esa o'zi tekshiradi; Supabase Auth RLS siyosatlariga tayanmaydi.
   Har bir keyingi migratsiyada yangi jadvallarni ham xuddi shunday himoyalang.
   Tanlangan Lingora loyihasining boshlang'ich Alembic jadvallariga bu cheklovlar
   alohida Supabase migratsiyasi bilan qo'llangan.
4. **Storage** (ixtiyoriy): New bucket → `lingora-books` → **Private** →
   `.env`: `STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
   (service key: Settings → API → service_role — **faqat server**, hech qachon frontendga bermang!)

### Railway misol

- **Backend service**: root=`backend`, build=`pip install -r requirements.txt`,
  start=`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Frontend service**: root=`frontend`, build=`npm run build`, start=`npm start`,
  env: `BACKEND_URL=https://<backend-domain>` (FastAPI serverining asosiy manzili;
  `/api/v1` qo'shmang). Bu qiymat frontend ishga tushganda o'qiladi.
- Har ikkisiga `.env` qiymatlarini Variables bo'limida kiritng.

### Render backend + Vercel frontend

Repo ildizidagi `render.yaml` Render Blueprint uchun FastAPI xizmatini tayyorlaydi.
Render'da GitHub reposini ulang va Blueprint yaratishda kerakli branchni tanlang.
So'raladigan qiymatlar:

- `DATABASE_URL`: Lingora uchun alohida PostgreSQL bazasining ulanish manzili.
  Supabase'dan foydalansangiz, **Lingora uchun alohida loyiha** yoki boshqa ilova
  ma'lumotlari bilan aralashmaydigan baza tayyorlang. Parolni faqat Render'ning
  Environment sozlamasiga kiriting, chat yoki Git'ga emas.
- `FRONTEND_URL` va `CORS_ORIGINS`: frontendning HTTPS manzili, masalan
  `https://lingora-mocha.vercel.app`.
- `SECRET_KEY`: Blueprint tasodifiy qiymat yaratadi. Uni o'zgartirish mavjud
  sessiyalarni bekor qilishi mumkin.

Backend build tugagach, uning `https://...onrender.com/api/v1/health` manzilini
tekshiring va Vercel'da `BACKEND_URL` ga faqat `https://...onrender.com` ni
kiriting. Frontendning yangi kodini ham deploy qilish zarur. Bepul Render
xizmati uxlab qolishi va dastlabki so'rov sekinlashishi mumkin; xizmat va baza
rejasi shartlari Render/Supabase tomonidan o'zgartirilishi mumkin.

**Fayllar:** Render'ning vaqtinchalik local diski qayta deploy yoki qayta ishga
tushganda saqlanmaydi. Kitoblarni doimiy saqlash uchun private Supabase Storage
bucket va backendda `STORAGE_BACKEND`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`SUPABASE_STORAGE_BUCKET` sozlamalarini ulang. Free service ishlab chiqarishdagi
fayl va background joblar uchun mosligi alohida baholanishi kerak.

### Vercel frontend (Cloudflare'siz)

Vercel **faqat frontendni** xizmat qiladi: Next.js sahifalari va `/backend/*`
proxy route'i. FastAPI backend Render'da turadi (`render.yaml`), shuning uchun
serverless funksiya ichida background ish qilish muammosi umuman paydo bo'lmaydi.

**Cloudflare Workers ishlatilmaydi.** Ilgari `lingora` worker'i production'ni
egallab olgan va `main`dan ajralgan eski branch'dan (`arena/c54ee9f4-lingora`,
2026-11-13) qurilib qolgan edi: har bir build yiqilardi, sayt esa eski kodda
qotib qolardi. Cloudflare'dagi servis o'chirilgach, Vercel yagona manzil bo'lib qoladi.

Sozlamalar (Vercel → Project → Settings):

| Sozlama | Qiymat |
|---|---|
| Root Directory | **bo'sh** (repo ildizi) |
| Framework Preset | Next.js |
| Production Branch | `main` |
| Env: `BACKEND_URL` | Vercel Services binding beradi; alohida backend bo'lsa `https://<render-xizmat>.onrender.com` (`/api/v1` qo'shmasdan) |
| Env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | faqat to'g'ridan-to'g'ri yuklash (TUS) ishlatilsa |

Ildizdagi `vercel.json` **Vercel Services** tavsifidir: `frontend` (Next.js) va
`backend` (FastAPI) xizmatlari bitta loyihada, `frontend` esa `BACKEND_URL`
binding'ini avtomatik oladi. Uni oddiy root-build sozlamalari bilan
almashtirmang — sinab ko'rildi va preview deploy darhol yiqildi: loyiha aynan
shu tavsif orqali xizmat qiladi.

`BACKEND_URL` Next.js ishga tushganda o'qiladi (build vaqtida emas), shuning
uchun Render manzili o'zgarsa faqat env o'zgaruvchini yangilash kifoya —
frontendni qayta build qilish shart emas.

**Deploy chiqqanini tekshirish.** `GET /api/v1/health` endi qaysi commit'dan
qurilganini qaytaradi:

```json
{"status": "ok", "app": "Lingora API", "env": "prod", "revision": "14509e2"}
```

Frontend orqali: `https://<domain>/backend/api/v1/health`. `revision` `main`dagi
oxirgi commit bilan bir xil bo'lishi kerak. `BACKEND_UNAVAILABLE` qaytsa —
`BACKEND_URL` noto'g'ri yoki Render xizmati uxlab yotgan (bepul rejada birinchi
so'rov sekin).

**Storage.** Render'ning diski deploy'da o'chib ketadi, shuning uchun yuklangan
PDF'lar yo'qoladi. Ikki yo'l: Render'ga persistent disk ulash
(`STORAGE_DIR` ni disk yo'liga qo'ying), yoki private Supabase bucket:
`STORAGE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`SUPABASE_STORAGE_BUCKET`. Service kalit **faqat serverda** turadi.
`SUPABASE_DIRECT_UPLOAD_ENABLED=true` qilishdan oldin bucket hajmini aniq
52428800 bayt (50 MiB) qiling; Vercel Function'ning 4.5 MB request chegarasi
faylga qo'llanmaydi, chunki yuklash imzolangan TUS bilan bevosita Storage'ga
ketadi. Yuklash to'xtasa rezerv kitob joy egallaydi, muddati 2 soat.

**Analysis.** `TASK_BACKEND=inline` (default) Render'ning uzoq yashovchi
jarayonida ThreadPool'da ishlaydi va 60–200 soniyalik skanerlashni oxirigacha
yetkazadi. `TASK_BACKEND=sync` serverless uchun, lekin request timeout'iga
tushib qoladi — bu loyihada ishlatilmaydi.

### Sxema migratsiyasi (majburiy qadam)

Yangi reliz yangi ustun qo'shsa (masalan `vocabulary_words.picture_page`), bazaga
`alembic upgrade head` qo'llanilmasa API ishlash paytida
`column ... does not exist` xatosi bilan yiqiladi — lug'at sahifasi aynan shunday
500 qaytargan.

- Docker / Render: `alembic upgrade head` start buyrug'ida bo'lgani uchun hech narsa
  qilish kerak emas.
- Vercel Services va start buyrug'i ishlamaydigan boshqa xostlar: `ENV=prod` bo'lsa ham
  API ishga tushishda sxemani **faqat qo'shish** yo'li bilan yangilaydi
  (`AUTO_SCHEMA_UPGRADE=true` yoki `VERCEL` muhit o'zgaruvchisi). Ustunlar qo'shilsa,
  baza eng yangi Alembic reviziyasi bilan belgilanadi, shuning uchun keyin qo'lda
  bajarilgan `alembic upgrade head` hech narsani qayta qo'shmaydi.
- Migratsiyalarning o'zi ham idempotent: ustun allaqachon bo'lsa, qayta qo'shilmaydi.

Alohida backend serveridan foydalanilganda Vercel
sozlamalarida `BACKEND_URL` qiymatini FastAPI serverining HTTPS asosiy manziliga
(masalan, `https://api.example.uz`, `/api/v1` qo'shmasdan) o'rnating va frontendni
qayta deploy qiling. `localhost` yoki `127.0.0.1` Vercel'dan alohida backendga
ishora qilmaydi. Supabase loyihasining URL manzili FastAPI backend URL o'rnini
bosmaydi.

Deploydan keyin `https://<frontend-domain>/backend/api/v1/health` va
`https://<backend-domain>/api/v1/health` JSON javob qaytarishini tekshiring.

---

## Env o'zgaruvchilar (to'liq ro'yxat)

| Env | Majburiy | Default | Tavsif |
|---|---|---|---|
| `SECRET_KEY` | ✅ | — | `openssl rand -hex 32` |
| `ENV` | — | `dev` | prod'da `create_all` o'chiq, faqat Alembic |
| `DATABASE_URL` | — | sqlite | PostgreSQL/Supabase pooler URL |
| `CORS_ORIGINS` | ✅ prod | localhost:3000 | vergul bilan |
| `STORAGE_BACKEND` | — | `local` | `local` yoki `supabase` |
| `STORAGE_DIR` | — | `./data/storage` | local backend uchun |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_STORAGE_BUCKET` | supabase storage uchun | — | service key faqat serverda |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase browser upload uchun | — | public/anon key; service key emas |
| `SUPABASE_DIRECT_UPLOAD_ENABLED` | direct upload uchun | false | bucket 50 MiB limiti tekshirilgach yoqing |
| `UPLOAD_MAX_MB` / `MAX_PAGES` | — | 50 / 300 | yuklash limitlari |
| `AI_PROVIDER` | — | `none` | `openai_compatible` / `anthropic` / `gemini` |
| `AI_API_KEY` / `AI_MODEL` | AI uchun ✅ | — | kalit faqat serverda |
| `AI_BASE_URL` | — | openai | Groq/OpenRouter/vLLM uchun o'zgartiring |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | — | 60 / 2 | |
| `AI_ENRICH_WORKERS` | — | 4 | lug'at/dars AI boyitishini parallel qiladi; provayder rate-limit qilsa pasaytiring |
| `OCR_MAX_WORKERS` / `OCR_MAX_PARALLEL_MB` | — | 4 / 256 | skanerlangan sahifalarni parallel OCR qilish uchun ishchilar va xotira chegarasi |
| `TASK_BACKEND` | — | `inline` | `celery` + `REDIS_URL`; `sync` faqat qisqa request-bound ishlar uchun |
| `FREE_MAX_BOOKS` va boshqa plan limitlari | — | 3/25/100 | reja limitlari |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | — | — | parol tiklash emaili |
| `BACKEND_URL` | frontend uchun | `http://127.0.0.1:8000` | FastAPI asosiy manzili (`/api/v1` siz); Docker Compose da `http://backend:8000` |
| `FRONTEND_URL` | — | localhost:3000 | reset linklari uchun |

**Muhim:** service va AI secret kalitlari frontendga yoki gitga yozilmaydi.
Browserga faqat Supabase public key va vaqtinchalik imzolangan upload token beriladi;
brauzer to'g'ridan-to'g'ri AI provayderlariga ulanmaydi.

---

## Backup strategiyasi

- **PostgreSQL**: Supabase auto-backup (Pro) yoki cron: `pg_dump $DATABASE_URL > backup_$(date +%F).sql`
- **Fayllar (local storage)**: `backend/data/storage/` katalogini rsync/S3'ga zaxiralang.
  Supabase Storage ishlatilsa — Supabase zaxirasiga kiradi.
- **SQLite (dev)**: faylni to'xtatib zaxiralash (`data/lingora.db`).

## Monitoring

- Health: `GET /api/v1/health`
- AI usage: har bir chaqiruv `usage_events` jadvalida (tokens, cost estimate)
- Logs: `docker compose logs -f backend`
