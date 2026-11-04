"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { INSURER_ROLES, RequireAuth, useAuth } from "@/lib/auth";
import { homeFor } from "@/lib/format";

const ROLE_LABEL: Record<string, string> = {
  insurer_staff: "Staf klaim",
  insurer_manager: "Manajer klaim",
  doctor_gp: "Dokter umum",
  doctor_specialist: "Dokter spesialis",
  admin: "Admin",
};

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const path = usePathname();
  const isInsurer = !!user && INSURER_ROLES.includes(user.role);
  const isDoctor = user?.role === "doctor_gp" || user?.role === "doctor_specialist";
  const isAdmin = user?.role === "admin";
  const nav = (href: string, label: string) => (
    <Link
      href={href}
      className={`rounded px-2 py-1 text-sm ${path === href || (href !== "/klaim" && path.startsWith(href + "/")) ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}
    >
      {label}
    </Link>
  );
  return (
    <div>
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-4">
            <Link href={homeFor(user?.role)} className="font-semibold">MAB Indonesia</Link>
            <nav className="flex gap-1">
              {isDoctor && nav("/telaah", "Antrean telaah")}
              {isAdmin && nav("/admin", "Aturan & pengguna")}
              {nav("/klaim", "Daftar klaim")}
              {isInsurer && nav("/klaim/baru", "Unggah klaim")}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-600">
              {user?.full_name} <span className="text-slate-400">· {user ? ROLE_LABEL[user.role] ?? user.role : ""}</span>
            </span>
            <button className="btn-secondary" onClick={logout}>Keluar</button>
          </div>
        </div>
      </header>
      <main className={`mx-auto px-4 py-6 ${path.startsWith("/telaah/") ? "max-w-[96rem]" : "max-w-6xl"}`}>{children}</main>
    </div>
  );
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <Shell>{children}</Shell>
    </RequireAuth>
  );
}
