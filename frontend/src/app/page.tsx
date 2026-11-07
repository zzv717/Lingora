"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "@/lib/api";
import { Logo } from "@/components/nav";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getAccessToken() ? "/dashboard" : "/login");
  }, [router]);
  return (
    <main className="flex min-h-screen items-center justify-center">
      <Logo />
    </main>
  );
}
