"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { apiJson, saveSession } from "@/lib/api";
import { homeFor } from "@/lib/format";
import type { User } from "@/lib/types";

interface DemoAccount {
  email: string;
  label: string;
  full_name: string;
  role: string;
}

const DOCTOR = ["doctor_gp", "doctor_specialist"];

/** Halaman tujuan setelah ganti peran: tetap di klaim yang sama bila perannya bisa membukanya. */
function targetPath(path: string, role: string): string {
  const m = /^\/(klaim|telaah)\/([^/]+)$/.exec(path);
  if (m && m[2] !== "baru") {
    if (DOCTOR.includes(role)) return `/telaah/${m[2]}`;
    if (role !== "admin" || m[1] === "klaim") return `/klaim/${m[2]}`;
  }
  return homeFor(role);
}

/** Pemilih "Ganti peran (demo)": pindah akun demo tanpa logout. Tidak tampil bila mode demo mati. */
export default function DemoSwitcher({ user }: { user: User }) {
  const path = usePathname();
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJson<DemoAccount[]>("/auth/demo-accounts").then(setAccounts).catch(() => setAccounts([]));
  }, []);

  if (accounts.length === 0) return null;

  const change = async (email: string) => {
    if (email === user.email) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiJson<{ access_token: string; user: User }>("/auth/demo-switch", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      saveSession(r.access_token, r.user);
      // muat ulang penuh supaya semua halaman membaca sesi baru
      window.location.href = targetPath(path, r.user.role);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal ganti peran");
      setBusy(false);
    }
  };

  return (
    <label className="flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
      <span className="font-medium">Ganti peran (demo)</span>
      <select
        className="rounded border border-amber-300 bg-white px-1 py-0.5 text-xs"
        value={user.email}
        disabled={busy}
        onChange={(e) => change(e.target.value)}
        title={error ?? "Pindah ke akun demo lain tanpa logout"}
      >
        {accounts.map((a) => (
          <option key={a.email} value={a.email}>{a.label}</option>
        ))}
      </select>
      {error && <span className="text-red-700">{error}</span>}
    </label>
  );
}
