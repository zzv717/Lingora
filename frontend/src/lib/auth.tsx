"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, clearTokens, getAccessToken, post, storeTokens, ApiErr } from "./api";
import type { Me, Profile, TokenPair } from "./types";

interface AuthCtx {
  me: Me | null;
  profile: Profile | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    if (!getAccessToken()) {
      setMe(null);
      setProfile(null);
      return;
    }
    try {
      const [m, p] = await Promise.all([
        api<Me>("/auth/me"),
        api<Profile>("/auth/me/profile"),
      ]);
      setMe(m);
      setProfile(p);
    } catch {
      setMe(null);
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await refreshMe();
      setLoading(false);
    })();
  }, [refreshMe]);

  const login = useCallback(async (email: string, password: string) => {
    const t = await post<TokenPair>("/auth/login", { email, password });
    storeTokens(t);
    await refreshMe();
  }, [refreshMe]);

  const register = useCallback(async (email: string, password: string, fullName: string) => {
    const t = await post<TokenPair>("/auth/register", { email, password, full_name: fullName });
    storeTokens(t);
    await refreshMe();
  }, [refreshMe]);

  const logout = useCallback(async () => {
    try {
      const rt = localStorage.getItem("lingora.refresh");
      if (rt) await post("/auth/logout", { refresh_token: rt }).catch(() => null);
    } finally {
      clearTokens();
      setMe(null);
      setProfile(null);
    }
  }, []);

  return (
    <Ctx.Provider value={{ me, profile, loading, login, register, logout, refreshMe }}>
      {children}
    </Ctx.Provider>
  );
}

export const useAuth = () => useContext(Ctx);

export { ApiErr };
