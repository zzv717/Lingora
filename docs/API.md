# API Reference (qisqa)

To'liq interaktiv hujjat: backend ishga tushganda **`/docs`** (Swagger UI).

Barcha endpointlar prefiksi: `/api/v1`. Auth: `Authorization: Bearer <access_token>`.
Xatolar yagona formatda: `{"error": {"code", "message_uz", "details"}}`.

## Auth
| Method | Path | Tavsif |
|---|---|---|
| POST | `/auth/register` | `{email, password, full_name}` → token pair |
| POST | `/auth/login` | `{email, password}` → token pair |
| POST | `/auth/refresh` | `{refresh_token}` → yangi pair (rotatsiya) |
| POST | `/auth/logout` | refresh tokenni bekor qilish |
| GET | `/auth/me` | profil ma'lumoti |
| GET/PATCH | `/auth/me/profile` | mavzu, kunlik maqsad, lug'at balli, darvoza |
| POST | `/auth/change-password` | |
| POST | `/auth/forgot-password` / `/auth/reset-password` | |
| DELETE | `/auth/account` | hisob + barcha ma'lumotlar |

## Kitoblar va pipeline
| Method | Path | Tavsif |
|---|---|---|
| POST | `/books/upload` | multipart: `file`, `title`, `consent=true` → Book |
| GET | `/books` | ro'yxat |
| GET | `/books/{id}/status` | processing job: progress %, stage (uz), warnings |
| POST | `/books/{id}/reanalyze` | qayta tahlil |
| GET | `/books/{id}/structure` | boblar, darslar, coverage, lesson locks |
| GET | `/books/{id}/pages/{n}` | sahifa matni + bloklar (overlay fallback) |
| GET | `/books/{id}/file` | PDF stream (private, ownership tekshiriladi) |
| DELETE | `/books/{id}` | kitob + barcha bog'liq ma'lumotlar |

## Mashqlar
| Method | Path | Tavsif |
|---|---|---|
| GET | `/lessons/{id}/exercises` | mashqlar (javoblar kaliti ko'rsatilmaydi) |
| GET/PUT | `/exercises/{id}/answers` | javoblarni saqlash/olish (autosave) |
| POST | `/exercises/{id}/check` | baholash: kalit → qoidalar → AI → noaniq |
| GET | `/exercises/{id}/attempts` | tarix |

## Lug'at
| Method | Path | Tavsif |
|---|---|---|
| GET | `/books/{id}/vocabulary` | so'zlar |
| GET | `/vocabulary/stats` · `/vocabulary/due` · `/vocabulary/progress` | SM-2 holati |
| POST | `/vocabulary/sessions?lesson_id=&kind=` | test yaratish (darvoza tekshiruvi bilan) |
| POST | `/vocabulary/sessions/{id}/answer` | javob baholanadi, xato so'z qayta qo'shiladi |
| POST | `/vocabulary/sessions/{id}/complete` | ball, o'tdi/yo'q, darvoza ochilishi |

## AI Murabbiy
| Method | Path | Tavsif |
|---|---|---|
| GET | `/tutor/status` | AI sozlanganmi |
| POST/GET | `/tutor/conversations` | suhbatlar |
| GET | `/tutor/conversations/{id}/messages` | tarix |
| POST | `/tutor/conversations/{id}/messages` | savol → kontekstli javob (uz) |
| POST | `/tutor/lessons/{id}/extra-exercises` | AI qo'shimcha mashqlar |

## Progress
| Method | Path | Tavsif |
|---|---|---|
| GET | `/progress/dashboard` | statistika, seriya, faollik, mavzular |
| POST | `/progress/heartbeat` | o'qish vaqti |
| POST | `/revision/sessions` | aqlli takrorlash seansi (zaif mavzular + due so'zlar) |
| GET | `/me/plan` · `/ai/status` · `/health` | reja, AI holati, health |
