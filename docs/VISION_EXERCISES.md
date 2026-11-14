# Vision AI orqali mashqlarni topish (skaner kitoblar)

## Muammo
OCR (Tesseract) doira ichidagi mashq raqamlarini (91, 92, 93) o'qiy olmaydi (`Gt`, `2)`, `@` chiqadi),
`structure_detector.py` esa faqat `Exercise/Task/Mashq...` so'zini qidiradi. Natijada mashqlar topilmaydi.

## Yechim
Sahifa rasmi vision modelga (OpenAI) yuboriladi, model mashqlarni JSON qilib qaytaradi. Backend uni tekshiradi
va `Exercise` / `ExerciseQuestion` / `ExerciseOption` jadvallariga `detection="vision"`, `needs_review=true`
bilan yozadi. **Javob kalitlari hech qachon yaratilmaydi.** Mavjud (rule/ocr/manual) mashqlar o'zgarmaydi.

## Sozlash (Render / Docker env)
```
AI_PROVIDER=openai_compatible
AI_API_KEY=sk-...
AI_MODEL=<matn modeli>
AI_VISION_MODEL=<rasm qabul qiladigan model>   # bo'sh bo'lsa AI_MODEL ishlatiladi
VISION_EXERCISE_PAGES_PER_DAY=150              # foydalanuvchi uchun kunlik sahifa limiti, 0 = cheksiz
```
Tavsiya: rasm qabul qiladigan, reasoning bo'lmagan model tanlang (OCR vazifasi uchun arzon va tez).
`gpt-5` / `o`-seriyali modellar ham ishlaydi (kod `max_completion_tokens` ishlatadi), lekin sekinroq va qimmatroq.
API kalit faqat backend muhitida turadi, frontendga chiqmaydi.

## API
| Endpoint | Vazifa |
|---|---|
| `GET  /books/{id}/vision-exercises/pending?include_text_pages=false` | Tahlil qilinmagan sahifalar ro'yxati |
| `POST /books/{id}/vision-exercises/pages/{n}/preview` | Bitta sahifani tahlil qiladi, **saqlamaydi** |
| `POST /books/{id}/vision-exercises/pages/{n}` | Tahlil qiladi va saqlaydi |

Body: `{"consent_images_to_provider": true, "replace": false}`. Rozilik bo'lmasa 422.
`replace=true` faqat avvalgi *vision* mashqlarni almashtiradi va ularda foydalanuvchi javoblari bo'lsa rad etadi.

## Limit
Ilovaning kunlik AI so'rov va Vision sahifa limitlari hozircha o'chirilgan. `AI_DAILY_REQUEST_LIMITS_ENABLED=true` qilib qayta yoqish mumkin; shunda alohida `VISION_EXERCISE_PAGES_PER_DAY` limiti qo'llanadi va u umumiy 20/300/2000 AI chaqiruv limitidan hisoblanmaydi. Foydalanish hisobga olinadi. Alohida token limiti sozlangan bo'lsa, qisqa vaqtli so'rov limitlari va AI provayderining kvotalari hamon amal qiladi.

## Cheklovlar
- Rasmga tayanadigan mashqlarning ("Look at the picture...") savollari qisqa bo'ladi; rasm sahifada qoladi.
- Matching mashqlarida o'ng ustun tartibi faqat ko'rsatish uchun; baholanmaydi (kalit yo'q).
- Mashq ikki sahifaga o'tsa, har sahifa alohida mashq sifatida saqlanadi (qo'lda tekshirish kerak).
- Model xato qilishi mumkin: hammasi `needs_review` bilan belgilanadi.
