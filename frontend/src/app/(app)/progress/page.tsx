"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { get, post } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Button, Card, EmptyState, Spinner, useToast } from "@/components/ui";
import { BarChart, StatCard, TopicBar } from "@/components/charts";

const DAYS_UZ = ["Yak", "Du", "Se", "Cho", "Pay", "Ju", "Sha"];

export default function ProgressPage() {
  const [stats, setStats] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    get<Dashboard>("/progress/dashboard")
      .then(setStats)
      .finally(() => setLoading(false));
  }, []);

  const buildRevision = async () => {
    setBuilding(true);
    try {
      const res = await post<{ created: boolean; message_uz?: string }>("/revision/sessions");
      if (res.created) {
        toast("Takrorlash seansi tayyor!", "success");
      } else {
        toast(res.message_uz || "Takrorlash materiali topilmadi");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    } finally {
      setBuilding(false);
    }
  };

  if (loading) {
    return (
      <>
        <TopBar title="Natijalar" />
        <main className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></main>
      </>
    );
  }
  if (!stats) {
    return (
      <>
        <TopBar title="Natijalar" />
        <main className="mx-auto max-w-4xl px-4 py-10"><EmptyState title="Ma'lumot yo'q" /></main>
      </>
    );
  }

  return (
    <>
      <TopBar title="Natijalar" />
      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 lg:px-8">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard title="Yakunlangan darslar" value={`${stats.lessons_completed}/${stats.lessons_total}`} />
          <StatCard title="Tekshirilgan mashqlar" value={stats.exercises_checked} tone="blue" />
          <StatCard title="O'rtacha aniqlik" value={`${stats.avg_accuracy}%`} tone="green" />
          <StatCard title="Jami o'qish vaqti" value={`${stats.study_minutes_total} daq`} tone="amber" />
        </div>

        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800 dark:text-slate-100">Faoliyat (14 kun)</h2>
            <Button size="sm" variant="secondary" onClick={buildRevision} loading={building}>
              🧠 Aqlli takrorlash seansi tuzish
            </Button>
          </div>
          <BarChart
            data={stats.activity_last_14d.map((a) => ({
              label: DAYS_UZ[new Date(a.day + "T00:00:00").getDay()],
              value: a.minutes,
            }))}
            goal={stats.daily_goal_minutes}
          />
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <h2 className="mb-3 font-semibold text-red-600 dark:text-red-400">📌 Zaif mavzular</h2>
            {stats.weak_topics.length === 0 ? (
              <p className="text-sm text-slate-400">
                Hali zaif mavzu aniqlanmadi. Mashqlar bajarilgach, tizim xatolarni tahlil qilib,
                qaysi mavzuni mustahkamlash kerakligini ko'rsatadi.
              </p>
            ) : (
              <div className="space-y-3">
                {stats.weak_topics.map((t) => (
                  <TopicBar key={t.topic} topic={t.topic} accuracy={t.accuracy} attempts={t.attempts} weak />
                ))}
              </div>
            )}
          </Card>
          <Card>
            <h2 className="mb-3 font-semibold text-emerald-600 dark:text-emerald-400">⭐ Kuchli mavzular</h2>
            {stats.strong_topics.length === 0 ? (
              <p className="text-sm text-slate-400">Mashqlarni bajarishda davom eting!</p>
            ) : (
              <div className="space-y-3">
                {stats.strong_topics.map((t) => (
                  <TopicBar key={t.topic} topic={t.topic} accuracy={t.accuracy} attempts={t.attempts} weak={false} />
                ))}
              </div>
            )}
          </Card>
        </div>

        <Card>
          <h2 className="mb-3 font-semibold text-slate-800 dark:text-slate-100">Lug'at holati</h2>
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-xl bg-brand-50 py-3 dark:bg-brand-900/20">
              <p className="text-2xl font-bold text-brand-600 dark:text-brand-300">{stats.vocab_learning}</p>
              <p className="text-xs text-slate-500">o'rganilmoqda</p>
            </div>
            <div className="rounded-xl bg-emerald-50 py-3 dark:bg-emerald-900/20">
              <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-300">{stats.vocab_mastered}</p>
              <p className="text-xs text-slate-500">o'zlashtirilgan</p>
            </div>
            <div className="rounded-xl bg-amber-50 py-3 dark:bg-amber-900/20">
              <p className="text-2xl font-bold text-amber-600 dark:text-amber-300">{stats.vocab_due}</p>
              <p className="text-xs text-slate-500">takrorlash kerak</p>
            </div>
          </div>
          <Link href="/vocabulary" className="mt-3 block text-center text-sm text-brand-600 hover:underline dark:text-brand-400">
            Lug'at mashg'ulotiga o'tish →
          </Link>
        </Card>
      </main>
    </>
  );
}
