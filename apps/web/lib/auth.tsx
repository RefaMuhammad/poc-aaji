"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { clearSession, getStoredUser, getToken } from "./api";
import type { User } from "./types";

const AuthContext = createContext<{ user: User | null; logout: () => void }>({ user: null, logout: () => {} });

export function useAuth() {
  return useContext(AuthContext);
}

/** Peran yang mengunggah klaim dan mencatat keputusan asuransi (staf/manajer asuransi, operator TPA). */
export const INSURER_ROLES = ["insurer_staff", "insurer_manager", "tpa_operator"];
export const DOCTOR_ROLES = ["doctor_gp", "doctor_specialist"];
/** Cerminan matriks RBAC di API (apps/api/mab_api/rbac.py) untuk menampilkan menu; API tetap yang memutuskan. */
export const DASHBOARD_ROLES = [...INSURER_ROLES, "auditor", "admin"];
export const DETAIL_ROLES = [...INSURER_ROLES, ...DOCTOR_ROLES, "auditor", "admin"];
export const CLAIM_LIST_ROLES = [...DETAIL_ROLES, "facility_officer", "member"];

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
