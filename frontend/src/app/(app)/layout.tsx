"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Spinner } from "@/components/ui";
import { Sidebar, BottomNav } from "@/components/nav";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Spinner className="h-8 w-8 text-brand-500" />
      </main>
    );
  }
  if (!me) return null;

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="lg:pl-64">
        {children}
      </div>
      <div className="h-16 lg:hidden" />
      <BottomNav />
    </div>
  );
}
