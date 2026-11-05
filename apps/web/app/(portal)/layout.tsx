"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { DASHBOARD_ROLES, DETAIL_ROLES, DOCTOR_ROLES, FRAUD_VIEW_ROLES, INSURER_ROLES, POLICY_VIEW_ROLES, RequireAuth, useAuth } from "@/lib/auth";
import { ROLE_LABEL, homeFor } from "@/lib/format";
import type { Branding } from "@/lib/types";
import DemoSwitcher from "@/components/DemoSwitcher";

/** Logo dan nama tenant (asuransi) pengguna; kosong untuk pengguna platform MAB. */
function TenantBrand({ brand }: { brand: Branding | null }) {
  if (!brand) return null;
  return (
    <span className="flex items-center gap-2 border-l pl-3 text-sm text-slate-700">
      {brand.logo_data_url && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={brand.logo_data_url} alt="" className="h-7 w-7 rounded object-contain" />
      )}
      <span className="font-medium" style={brand.primary_color ? { color: brand.primary_color } : undefined}>
        {brand.display_name ?? brand.name}
      </span>
    </span>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const path = usePathname();
  const role = user?.role ?? "";
  const isInsurer = INSURER_ROLES.includes(role);
  const isDoctor = DOCTOR_ROLES.includes(role);
  const isAdmin = role === "admin";
  const [brand, setBrand] = useState<Branding | null>(null);
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    if (!user) return;
    const refresh = () => apiJson<{ unread: number }>("/notifications/unread-count").then((r) => setUnread(r.unread)).catch(() => null);
    refresh();
    const t = setInterval(refresh, 30000);
    window.addEventListener("mab:inbox", refresh);
    return () => { clearInterval(t); window.removeEventListener("mab:inbox", refresh); };
  }, [user, path]);
  useEffect(() => {
    if (user?.insurer_id) apiJson<Branding | null>("/tenants/current").then(setBrand).catch(() => setBrand(null));
  }, [user?.insurer_id]);
  const nav = (href: string, label: string) => (
    <Link
      href={href}
      className={`rounded px-2 py-1 text-sm ${path === href || (!["/klaim", "/admin"].includes(href) && path.startsWith(href + "/")) ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}
    >
      {label}
    </Link>
  );
  return (
    <div>
      <header className="border-b border-t-4 bg-white" style={{ borderTopColor: brand?.primary_color ?? "#334155" }}>
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-4">
            <Link href={homeFor(user?.role)} className="font-semibold">MAB Indonesia</Link>
            <TenantBrand brand={brand} />
            <nav className="flex flex-wrap gap-1">
              {isDoctor && nav("/telaah", "Antrean telaah")}
              {isAdmin && nav("/admin", "Aturan & pengguna")}
              {isAdmin && nav("/admin/tenant", "Tenant & API key")}
              {role === "facility_officer" && nav("/faskes", "Klaim rumah sakit")}
              {role === "member" && nav("/peserta", "Klaim saya")}
              {role === "tpa_operator" && nav("/tpa", "Ringkasan TPA")}
              {DETAIL_ROLES.includes(role) && nav("/klaim", "Daftar klaim")}
              {isInsurer && nav("/klaim/baru", "Unggah klaim")}
              {POLICY_VIEW_ROLES.includes(role) && nav("/polis", "Polis")}
              {DASHBOARD_ROLES.includes(role) && nav("/dashboard", "Dashboard")}
              {FRAUD_VIEW_ROLES.includes(role) && nav("/fraud", "Fraud Monitor")}
              {role === "underwriter" && nav("/underwriting", "Underwriting")}
              <Link
                href="/kotak-masuk"
                className={`rounded px-2 py-1 text-sm ${path === "/kotak-masuk" ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}
              >
                Kotak masuk
                {unread > 0 && <span className="ml-1 rounded-full bg-sky-600 px-1.5 py-0.5 text-xs font-medium text-white">{unread}</span>}
              </Link>
            </nav>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            {user && <DemoSwitcher user={user} />}
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
