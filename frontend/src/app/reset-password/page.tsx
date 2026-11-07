"use client";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { post } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";
import { Logo } from "@/components/nav";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== password2) {
      setError("Parollar mos kelmadi.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await post("/auth/reset-password", { token, new_password: password });
      setDone(true);
      setTimeout(() => router.replace("/login"), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xatolik");
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return <ErrorBox message="Havola noto'g'ri — token yo'q." />;
  }
  if (done) {
    return (
      <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
        Parol tiklandi! Kirish sahifasiga o'tyapmiz...
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <Input label="Yangi parol" type="password" required minLength={8} value={password}
        onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      <Input label="Parolni takrorlang" type="password" required value={password2}
        onChange={(e) => setPassword2(e.target.value)} autoComplete="new-password" />
      <ErrorBox message={error} />
      <Button type="submit" loading={loading} className="w-full">Parolni saqlash</Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-white to-violet-50 px-4 dark:from-slate-950 dark:via-slate-950 dark:to-slate-900">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center"><Logo /></div>
        <Card>
          <h1 className="mb-4 text-lg font-bold text-slate-900 dark:text-white">Yangi parol</h1>
          <Suspense fallback={null}>
            <ResetForm />
          </Suspense>
        </Card>
      </div>
    </main>
  );
}
