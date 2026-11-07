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
  env: `BACKEND_URL=https://<backend-domain>`
- Har ikkisiga `.env` qiymatlarini Variables bo'limida kiritng.

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
