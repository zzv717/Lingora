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
3. **Sxema** (2 yo'l):
   - **A (tavsiya)**: backend `alembic upgrade head` ishga tushiring
   - **B (Supabase-native, RLS bilan)**: `database/supabase_schema.sql` ni SQL Editor'da ishga tushiring
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

### Vercel frontend

Hozirgi Vercel sozlamasi faqat Next.js frontendni ishga tushiradi; FastAPI
backendni alohida ishga tushirish va unga doimiy PostgreSQL bazasini ulash kerak.
Vercel Services ham frontend va FastAPI xizmatini bitta loyihada ishlata oladi.
Repo ildizidagi `vercel.json` shu yo'nalish uchun dastlabki konfiguratsiya, lekin
u hali ishlab chiqarish uchun tayyor emas: katta PDF uchun to'g'ridan-to'g'ri
Storage yuklash, ishonchli background worker va Vercel muhitida sinov zarur.
Mavjud frontend loyihasining root directory qiymati `frontend`; bu fayldan
foydalanish uchun alohida preview sozlamasida repo ildizi kerak bo'ladi.

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
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_STORAGE_BUCKET` | supabase storage uchun | — | |
| `UPLOAD_MAX_MB` / `MAX_PAGES` | — | 50 / 300 | yuklash limitlari |
| `AI_PROVIDER` | — | `none` | `openai_compatible` / `anthropic` / `gemini` |
| `AI_API_KEY` / `AI_MODEL` | AI uchun ✅ | — | kalit faqat serverda |
| `AI_BASE_URL` | — | openai | Groq/OpenRouter/vLLM uchun o'zgartiring |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | — | 60 / 2 | |
| `TASK_BACKEND` | — | `inline` | `celery` + `REDIS_URL` |
| `FREE_MAX_BOOKS` va boshqa plan limitlari | — | 3/25/100 | reja limitlari |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | — | — | parol tiklash emaili |
| `BACKEND_URL` | frontend uchun | `http://127.0.0.1:8000` | FastAPI asosiy manzili (`/api/v1` siz); Docker Compose da `http://backend:8000` |
| `FRONTEND_URL` | — | localhost:3000 | reset linklari uchun |

**Muhim:** hech qanday kalit frontendga yoki gitga yozilmaydi. `frontend` faqat
`BACKEND_URL` bilan proxy qiladi — brauzer to'g'ridan-to'g'ri AI provayderlariga ulanmaydi.

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
