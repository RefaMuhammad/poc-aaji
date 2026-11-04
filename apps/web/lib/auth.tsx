"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { clearSession, getStoredUser, getToken } from "./api";
import type { User } from "./types";

const AuthContext = createContext<{ user: User | null; logout: () => void }>({ user: null, logout: () => {} });

export function useAuth() {
  return useContext(AuthContext);
}

export const INSURER_ROLES = ["insurer_staff", "insurer_manager"];

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const u = getStoredUser();
    if (!getToken() || !u) {
      router.replace("/login");
      return;
    }
    setUser(u);
    setReady(true);
  }, [router]);

  const logout = () => {
    clearSession();
    router.replace("/login");
  };

  if (!ready) return <div className="p-8 text-sm text-slate-500">Memuat…</div>;
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}
