"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get } from "@/lib/api";
import type { Book, Dashboard } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, EmptyState, Progress, Spinner } from "@/components/ui";
import { BarChart, StatCard } from "@/components/charts";
import { UploadModal } from "@/components/upload-modal";

const DAYS_UZ = ["Yak", "Du", "Se", "Cho", "Pay", "Ju", "Sha"];

export default function DashboardPage() {
  const [stats, setStats] = useState<Dashboard | null>(null);
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [d, b] = await Promise.all([
          get<Dashboard>("/progress/dashboard"),
          get<Book[]>("/books"),
        ]);
        setStats(d);
        setBooks(b);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const dayLabel = (iso: string) => DAYS_UZ[new Date(iso + "T00:00:00").getDay()];
  const goalPct = stats ? Math.min(100, Math.round((stats.today_minutes / Math.max(stats.daily_goal_minutes, 1)) * 100)) : 0;

  return (
    <>
      <TopBar title="Boshqaruv paneli" />
      <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8">
        {loading ? (
          <div className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></div>
        ) : !stats ? (
          <EmptyState title="Ma'lumot yuklanmadi" />
        ) : books.length === 0 ? (
          <div className="space-y-6">
            <WelcomeHero onStart={() => setUploadOpen(true)} />
          </div>
        ) : (
          <div className="space-y-6">
            {/* Daily goal */}
            <Card className="bg-gradient-to-r from-brand-600 to-violet-600 text-white dark:border-brand-800">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-sm opacity-80">Kunlik maqsad</p>
                  <p className="text-2xl font-bold">
                    {stats.today_minutes} / {stats.daily_goal_minutes} daqiqa
                  </p>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-center">
                    <div className="text-3xl font-extrabold">{stats.streak_days}</div>
                    <div className="text-xs opacity-80">kunlik seriya 🔥</div>
                  </div>
                  <div className="w-40">
                    <Progress value={goalPct} tone="green" className="bg-white/30" />
                    <p className="mt-1 text-right text-xs opacity-75">{goalPct}% bajarildi</p>
                  </div>
                </div>
              </div>
            </Card>

            {/* Stats grid */}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatCard title="Kitoblar" value={stats.books_total} sub={`${stats.books_ready} ta tayyor`}
                icon={<BookIcon />} />
              <StatCard title="Mashqlar" value={stats.exercises_checked} sub="tekshirilgan"
                tone="blue" icon={<CheckIcon />} />
              <StatCard title="O'rtacha aniqlik" value={`${stats.avg_accuracy}%`} tone="green"
                icon={<TargetIcon />} />
              <StatCard title="Lug'at" value={stats.vocab_words_total}
                sub={`${stats.vocab_mastered} o'zlashtirilgan · ${stats.vocab_due} takrorlash`} tone="amber"
                icon={<WordIcon />} />
            </div>

            {/* Activity chart + continue learning */}
            <div className="grid gap-6 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">
                  Faoliyat (14 kun)
                </h2>
                <BarChart
                  data={stats.activity_last_14d.map((a) => ({ label: dayLabel(a.day), value: a.minutes }))}
                  goal={stats.daily_goal_minutes}
                />
              </Card>
              <ContinueCard books={books} />
            </div>

            {/* Weak / strong topics */}
            {(stats.weak_topics.length > 0 || stats.strong_topics.length > 0) && (
              <div className="grid gap-6 md:grid-cols-2">
                <Card>
                  <h2 className="mb-3 font-semibold text-slate-800 dark:text-slate-100">
                    📌 Mustahkamlash kerak
                  </h2>
                  <div className="space-y-3">
                    {stats.weak_topics.length === 0 && (
                      <p className="text-sm text-slate-400">Zaif mavzu topilmadi — zo'r!</p>
                    )}
                    {stats.weak_topics.map((t) => (
                      <Link key={t.topic} href="/progress"
                        className="block rounded-lg border border-red-100 bg-red-50/60 px-3 py-2 text-sm text-slate-700 transition hover:border-red-200 dark:border-red-900/40 dark:bg-red-950/20 dark:text-slate-300">
                        <span className="font-medium">{t.topic}</span>
                        <span className="float-right text-xs text-red-500">{t.accuracy}%</span>
                      </Link>
                    ))}
                  </div>
                </Card>
                <Card>
                  <h2 className="mb-3 font-semibold text-slate-800 dark:text-slate-100">
                    ⭐ Kuchli tomonlaringiz
                  </h2>
                  <div className="space-y-3">
                    {stats.strong_topics.length === 0 && (
                      <p className="text-sm text-slate-400">Mashqlarni bajarib ko'ring — natijalar shu yerda ko'rinadi.</p>
                    )}
                    {stats.strong_topics.map((t) => (
                      <Link key={t.topic} href="/progress"
                        className="block rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-sm text-slate-700 transition hover:border-emerald-200 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-slate-300">
                        <span className="font-medium">{t.topic}</span>
                        <span className="float-right text-xs text-emerald-600">{t.accuracy}%</span>
                      </Link>
                    ))}
                  </div>
                </Card>
              </div>
            )}
          </div>
        )}
      </main>
      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  );
}

function WelcomeHero({ onStart }: { onStart: () => void }) {
  const steps = [
    { n: 1, title: "PDF kitobingizni yuklang", desc: "Grammar, vocabulary yoki umumiy ingliz tili darsligi bo'lishi mumkin." },
    { n: 2, title: "AI kitobni tahlil qiladi", desc: "Boblar, darslar, mashqlar, lug'at va javoblar kaliti ajratib olinadi." },
    { n: 3, title: "Interaktiv o'rganing", desc: "Mashqlarni to'ldiring, AI tekshiradi va o'zbek tilida tushuntiradi." },
  ];
  return (
    <div>
      <Card className="bg-gradient-to-r from-brand-600 to-violet-600 text-white">
        <h1 className="text-2xl font-extrabold">Lingora'ga xush kelibsiz! 👋</h1>
        <p className="mt-1 max-w-lg text-sm opacity-90">
          Birinchi kitobingizni yuklang — AI uni interaktiv mashqlar, lug'at testlari va
          shaxsiy murabbiyga aylantiradi.
        </p>
        <Button variant="secondary" onClick={onStart} className="mt-4 !bg-white !text-brand-700 hover:!bg-brand-50">
          Kitob yuklash
        </Button>
      </Card>
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {steps.map((s) => (
          <Card key={s.n}>
            <div className="mb-2 flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 font-bold text-brand-600 dark:bg-brand-900/40 dark:text-brand-300">
              {s.n}
            </div>
            <h3 className="font-semibold text-slate-800 dark:text-slate-100">{s.title}</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{s.desc}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}

function ContinueCard({ books }: { books: Book[] }) {
  const ready = books.filter((b) => b.status === "ready").slice(0, 4);
  return (
    <Card>
      <h2 className="mb-3 font-semibold text-slate-800 dark:text-slate-100">Davom ettirish</h2>
      {ready.length === 0 ? (
        <p className="text-sm text-slate-400">Tayyor kitob yo'q. Yuklang va boshlang!</p>
      ) : (
        <div className="space-y-2">
          {ready.map((b) => (
            <Link key={b.id} href={`/reader/${b.id}`}
              className="flex items-center gap-3 rounded-xl border border-slate-200 px-3 py-2.5 text-sm transition hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-700 dark:hover:border-brand-700 dark:hover:bg-brand-900/20">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-100 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300">
                <BookIcon small />
              </span>
              <span className="flex-1 truncate font-medium text-slate-700 dark:text-slate-200">{b.title}</span>
              <Badge>{b.page_count} bet</Badge>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}

const BookIcon = ({ small }: { small?: boolean }) => (
  <svg className={small ? "h-4 w-4" : "h-5 w-5"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.247m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.247" />
  </svg>
);
const CheckIcon = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);
const TargetIcon = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);
const WordIcon = () => (
  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
  </svg>
);
