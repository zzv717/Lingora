"use client";
import { useState } from "react";
import Link from "next/link";
import { post } from "@/lib/api";
import { Button, Card, Input } from "@/components/ui";
import { Logo } from "@/components/nav";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<{ delivered: boolean; reset_link: string | null; message_uz: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      setResult(await post("/auth/forgot-password", { email }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Xatolik");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-white to-violet-50 px-4 dark:from-slate-950 dark:via-slate-950 dark:to-slate-900">
      <div className="w-full max-w-md">
        <div className="mb-8 flex justify-center"><Logo /></div>
        <Card>
          <h1 className="mb-1 text-lg font-bold text-slate-900 dark:text-white">Parolni tiklash</h1>
          <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
            Emailingizni kiriting — tiklash havolasini yuboramiz.
          </p>
          {!result ? (
            <form onSubmit={submit} className="space-y-4">
              <Input label="Email" type="email" required value={email}
                onChange={(e) => setEmail(e.target.value)} placeholder="siz@example.com" />
              {error && <p className="text-sm text-red-500">{error}</p>}
              <Button type="submit" loading={loading} className="w-full">Havola yuborish</Button>
            </form>
          ) : (
            <div className="space-y-3">
              <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                {result.message_uz}
              </div>
              {result.reset_link && (
                <a href={result.reset_link}
                  className="block break-all rounded-xl bg-slate-100 px-4 py-3 text-sm text-brand-600 hover:underline dark:bg-slate-800 dark:text-brand-400">
                  {result.reset_link}
                </a>
              )}
            </div>
          )}
          <div className="mt-4 text-center text-sm">
            <Link href="/login" className="font-semibold text-brand-600 hover:underline dark:text-brand-400">
              Kirish sahifasiga qaytish
            </Link>
          </div>
        </Card>
      </div>
    </main>
  );
}
