"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Input } from "@/components/ui";
import { Logo } from "@/components/nav";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Kirish amalga oshmadi");
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
            Kitoblaringiz interaktiv o'quv muhitiga aylanadi
          </p>
        </div>
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <Input label="Email" type="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="siz@example.com"
              autoComplete="email" />
            <Input label="Parol" type="password" required value={password}
              onChange={(e) => setPassword(e.target.value)} placeholder="••••••••"
              autoComplete="current-password" />
            <ErrorBox message={error} />
            <Button type="submit" loading={loading} className="w-full" size="lg">
              Kirish
            </Button>
          </form>
          <div className="mt-4 flex items-center justify-between text-sm">
            <Link href="/forgot-password" className="text-brand-600 hover:underline dark:text-brand-400">
              Parolni unutdingizmi?
            </Link>
            <Link href="/register" className="font-semibold text-brand-600 hover:underline dark:text-brand-400">
              Ro'yxatdan o'tish
            </Link>
          </div>
        </Card>
      </div>
    </main>
  );
}
