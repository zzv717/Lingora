"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Input } from "@/components/ui";
import { Logo } from "@/components/nav";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Parol kamida 8 belgidan iborat bo'lishi kerak.");
      return;
    }
    setLoading(true);
    try {
      await register(email, password, name);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ro'yxatdan o'tish amalga oshmadi");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-white to-violet-50 px-4 dark:from-slate-950 dark:via-slate-950 dark:to-slate-900">
      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3">
          <Logo />
          <p className="text-center text-sm text-slate-500 dark:text-slate-400">
            Bepul hisob yarating — birinchi kitobni 1 daqiqada yuklang
          </p>
        </div>
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <Input label="Ismingiz" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Ali Valiyev" autoComplete="name" />
            <Input label="Email" type="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="siz@example.com"
              autoComplete="email" />
            <Input label="Parol" type="password" required value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="Kamida 8 belgi"
              autoComplete="new-password" />
            <ErrorBox message={error} />
            <Button type="submit" loading={loading} className="w-full" size="lg">
              Ro'yxatdan o'tish
            </Button>
            <p className="text-center text-xs text-slate-400">
              Kitobni yuklashda siz muallif huquqi bo'yicha qayta ishlash huquqingiz
              borligini tasdiqlaysiz. Kitoblaringiz faqat sizga ko'rinadi.
            </p>
          </form>
          <div className="mt-4 text-center text-sm">
            <Link href="/login" className="font-semibold text-brand-600 hover:underline dark:text-brand-400">
              Hisobingiz bormi? Kirish
            </Link>
          </div>
        </Card>
      </div>
    </main>
  );
}
