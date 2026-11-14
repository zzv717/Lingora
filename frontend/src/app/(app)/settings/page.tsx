"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { del, get, patch, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import type { Me, Profile } from "@/lib/types";
import { TopBar } from "@/components/nav";
import { Badge, Button, Card, Input, Modal, Spinner, useToast } from "@/components/ui";

export default function SettingsPage() {
  const { me, refreshMe } = useAuth();
  const { theme, setTheme } = useTheme();
  const router = useRouter();
  const { toast } = useToast();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [plan, setPlan] = useState<{ plan: string; max_books: number; ai_calls_per_day: number; ai_calls_today: number; ai_configured: boolean } | null>(null);
  const [fullName, setFullName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      const [p, pl] = await Promise.all([
        get<Profile>("/auth/me/profile"),
        get<typeof plan>("/me/plan"),
      ]);
      setProfile(p);
      setPlan(pl);
      const m = await get<Me>("/auth/me");
      setFullName(m.full_name);
    })().catch(() => toast("Sozlamalar yuklanmadi", "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const saveProfile = async () => {
    setSaving(true);
    try {
      await patch("/auth/me/profile", {
        full_name: fullName,
        daily_goal_minutes: profile?.daily_goal_minutes,
        vocab_pass_score: profile?.vocab_pass_score,
        vocabulary_gating: profile?.vocabulary_gating,
      });
      await refreshMe();
      toast("Sozlamalar saqlandi", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    } finally {
      setSaving(false);
    }
  };

  const changePassword = async () => {
    try {
      await post("/auth/change-password", { current_password: currentPassword, new_password: newPassword });
      setCurrentPassword("");
      setNewPassword("");
      toast("Parol yangilandi", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    }
  };

  const doDeleteAccount = async () => {
    try {
      await del("/auth/account");
      localStorage.clear();
      router.replace("/register");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Xatolik", "error");
    }
  };

  if (!profile) {
    return (
      <>
        <TopBar title="Sozlamalar" />
        <main className="flex justify-center py-20"><Spinner className="h-8 w-8 text-brand-500" /></main>
      </>
    );
  }

  return (
    <>
      <TopBar title="Sozlamalar" />
      <main className="mx-auto max-w-2xl space-y-6 px-4 py-6 lg:px-8">
        {/* Profile */}
        <Card>
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">Profil</h2>
          <div className="space-y-4">
            <Input label="Ism" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            <Input label="Email" value={me?.email || ""} disabled />
          </div>
        </Card>

        {/* Learning preferences */}
        <Card>
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">O'quv sozlamalari</h2>
          <div className="space-y-5">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Kunlik maqsad: {profile.daily_goal_minutes} daqiqa
              </label>
              <input type="range" min={5} max={120} step={5} value={profile.daily_goal_minutes}
                onChange={(e) => setProfile({ ...profile, daily_goal_minutes: +e.target.value })}
                className="w-full accent-brand-600" />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
                Lug'at testidan o'tish balli: {profile.vocab_pass_score}%
              </label>
              <input type="range" min={50} max={100} step={5} value={profile.vocab_pass_score}
                onChange={(e) => setProfile({ ...profile, vocab_pass_score: +e.target.value })}
                className="w-full accent-brand-600" />
            </div>
            <label className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
              <div>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">Lug'at darvozasi</p>
                <p className="text-xs text-slate-400">Keyingi dars faqat oldingi dars lug'at testi o'tilgach ochiladi</p>
              </div>
              <input type="checkbox" checked={profile.vocabulary_gating}
                onChange={(e) => setProfile({ ...profile, vocabulary_gating: e.target.checked })}
                className="h-5 w-5 accent-brand-600" />
            </label>
          </div>
        </Card>

        {/* Appearance */}
        <Card>
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">Ko'rinish</h2>
          <div className="flex gap-2">
            {[["light", "☀️ Yorug'"], ["dark", "🌙 Qorong'i"], ["system", "💻 Tizim"]].map(([val, label]) => (
              <button key={val} onClick={() => setTheme(val as typeof theme)}
                className={`flex-1 rounded-xl border px-3 py-2.5 text-sm font-medium transition ${
                  theme === val ? "border-brand-500 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                    : "border-slate-200 text-slate-600 dark:border-slate-700 dark:text-slate-300"}`}>
                {label}
              </button>
            ))}
          </div>
        </Card>

        {/* Plan & usage */}
        {plan && (
          <Card>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold text-slate-800 dark:text-slate-100">Reja va limitlar</h2>
              <Badge tone="brand">{plan.plan === "free" ? "Bepul" : plan.plan.toUpperCase()}</Badge>
            </div>
            <ul className="space-y-1.5 text-sm text-slate-600 dark:text-slate-300">
              <li>📚 Kitoblar: {plan.max_books} tagacha</li>
              <li>🤖 AI so'rovlari: {plan.ai_calls_per_day > 0 ? `kuniga ${plan.ai_calls_per_day}` : "kunlik so'rov limiti yo'q"} (bugun: {plan.ai_calls_today})</li>
              <li>{plan.ai_configured ? "✅ AI xizmati faol" : "⚠️ AI xizmati sozlanmagan (deterministik tahlil ishlaydi)"}</li>
            </ul>
            <p className="mt-3 text-xs text-slate-400">
              To'lovli rejalar kelajakda qo'shiladi — hozir hammasi bepul.
            </p>
          </Card>
        )}

        {/* Security */}
        <Card>
          <h2 className="mb-4 font-semibold text-slate-800 dark:text-slate-100">Xavfsizlik</h2>
          <div className="space-y-3">
            <Input label="Joriy parol" type="password" value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" />
            <Input label="Yangi parol" type="password" value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
            <Button variant="secondary" onClick={changePassword}
              disabled={!currentPassword || newPassword.length < 8}>
              Parolni yangilash
            </Button>
          </div>
        </Card>

        {/* Data & account */}
        <Card className="border-red-200 dark:border-red-900">
          <h2 className="mb-2 font-semibold text-red-600 dark:text-red-400">Hisobni o'chirish</h2>
          <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
            Barcha kitoblar, javoblar, lug'at va natijalar butunlay o'chiriladi. Bu amalni
            qaytarib bo'lmaydi.
          </p>
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>Hisobni o'chirish</Button>
        </Card>

        <div className="sticky bottom-20 lg:bottom-4">
          <Button className="w-full" size="lg" onClick={saveProfile} loading={saving}>
            Sozlamalarni saqlash
          </Button>
        </div>
      </main>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Hisobni o'chirish">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Haqiqatan ham hisobingizni butunlay o'chirib tashlamoqchimisiz? Barcha ma'lumotlaringiz
          (kitoblar, javoblar, natijalar) o'chadi va tiklanmaydi.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Bekor qilish</Button>
          <Button variant="danger" onClick={doDeleteAccount}>Ha, hammasini o'chirish</Button>
        </div>
      </Modal>
    </>
  );
}
