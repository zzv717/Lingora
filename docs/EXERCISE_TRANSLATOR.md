# Mashqdagi mini tarjimon

Mini tarjimon Vision mavzu sinovidagi mashqlarda va reader'dagi saqlangan mashqlarda mavjud. Qo'lda so'z yoki jumla kiritish, yo'nalishni inglizcha → o'zbekcha yoki o'zbekcha → inglizchaga almashtirish mumkin. Ko'rsatmani yoki Vision sinovida savol matnini tanlash uni faqat tarjimon maydoniga joylaydi; so'rov avtomatik yuborilmaydi. 1000 belgidan uzun matnning faqat dastlabki 1000 belgisi olinadi va ogohlantirish ko'rsatiladi.

Tarjima uchun alohida rozilik va tugmani bosish zarur. Faqat maydondagi matn (PDF rasmi va boshqa javoblar emas) sozlangan tashqi AI provayderiga yuboriladi. Provayder tariflari, ma'lumotlardan foydalanish qoidalari va ilovaning AI kvotalari qo'llanadi. Tarjimalar vaqtinchalik, AI xato qilishi mumkin; mashq javoblari yoki baholash natijalariga yozilmaydi.

Backend: autentifikatsiya talab qiluvchi `POST /api/v1/tutor/translate`; `text` (1–1000 belgi), `direction` (`en-uz` yoki `uz-en`), `consent_text_to_provider` maydonlari kerak. Ilovaning kunlik so'rov kvotasi hozircha o'chirilgan; qisqa vaqtli so'rov limiti, sozlangan token limiti, provayder cheklovlari va `translator` usage accounting amal qiladi. Provider javobi JSON sifatida tekshiriladi, muvaffaqiyatsizlik foydalanuvchiga xabar qilinadi.

Vision sinovi mashqlari endi javob kiritish jarayonini (baho emas), savol kartalarini va AI natijalarini ko'rsatadi. Multiple-choice savollarida variantni tanlash matnni javob maydoniga kiritadi; u baribir erkin tahrirlanishi mumkin. AI tekshiruvi taxminiy va rozilik talab qiladi. Saqlangan reader mashqlarining baholash va autosave mexanizmlari o'zgartirilmagan.
