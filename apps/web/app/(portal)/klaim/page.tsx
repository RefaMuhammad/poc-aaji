"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiJson, downloadFile } from "@/lib/api";
import { INSURER_ROLES, useAuth } from "@/lib/auth";
import type { ClaimListItem, ClaimStatus, Tenant, Triage } from "@/lib/types";
import { IN_PROGRESS, RECOMMENDATION_LABEL, STATUS_LABEL, rupiah, tanggal } from "@/lib/format";
import { StatusBadge, TriageBadge } from "@/components/Badges";

const TRIAGE_OPTIONS: { value: "" | Triage; label: string }[] = [
  { value: "", label: "Semua triase" },
  { value: "GREEN", label: "Hijau" },
  { value: "YELLOW", label: "Kuning" },
  { value: "RED", label: "Merah" },
];

const DECISION_LABEL: Record<string, string> = { AGREE: "Setuju", DIFFER: "Berbeda" };

function isBulkCandidate(c: ClaimListItem) {
  return c.triage_status === "GREEN" && c.recommendation === "PAY_FULL" && !c.decision;
}

export default function ClaimListPage() {
  const { user } = useAuth();
  const isInsurer = !!user && INSURER_ROLES.includes(user.role);
  const canExport = isInsurer || user?.role === "auditor";
  const statusOnly = user?.role === "facility_officer" || user?.role === "member";
  const [claims, setClaims] = useState<ClaimListItem[] | null>(null);
  const [status, setStatus] = useState<"" | ClaimStatus>("");
  const [triage, setTriage] = useState<"" | Triage>("");
  // U4: operator TPA menyaring per asuransi yang dilayani (?insurer_id= dari Ringkasan TPA)
  const isTpa = user?.role === "tpa_operator";
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [insurerId, setInsurerId] = useState<string>(() =>
    typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("insurer_id") ?? "");
  useEffect(() => {
    if (isTpa) apiJson<Tenant[]>("/tenants").then(setTenants).catch(() => setTenants([]));
  }, [isTpa]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: "500" });
    if (status) params.set("status", status);
    if (triage) params.set("triage", triage);
    if (insurerId) params.set("insurer_id", insurerId);
    try {
      setClaims(await apiJson<ClaimListItem[]>(`/claims?${params}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [status, triage, insurerId]);

  useEffect(() => {
    load();
  }, [load]);

  // Muat ulang berkala selama ada klaim yang sedang diproses.
  const anyBusy = !!claims?.some((c) => IN_PROGRESS.includes(c.status));
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [anyBusy, load]);

  const candidates = useMemo(() => (claims ?? []).filter(isBulkCandidate), [claims]);
  const multiTenant = useMemo(() => new Set((claims ?? []).map((c) => c.insurer_id)).size > 1, [claims]);
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const bulkAgree = async () => {
    if (selected.size === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      const r = await apiJson<{ agreed: string[]; skipped: { claim_id: string; reason: string }[] }>("/claims/decisions/bulk-agree", {
        method: "POST",
        body: JSON.stringify({ claim_ids: Array.from(selected) }),
      });
      setMessage(`${r.agreed.length} klaim disetujui.` + (r.skipped.length ? ` ${r.skipped.length} dilewati.` : ""));
      setSelected(new Set());
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Daftar klaim</h1>
          {statusOnly && (
            <p className="text-sm text-slate-500">
              {user?.role === "member" ? "Klaim atas nomor peserta Anda." : `Klaim dari ${user?.facility_name ?? "rumah sakit Anda"}.`}{" "}
              Untuk sementara hanya status; rincian dan unggah dokumen susulan hadir di portal {user?.role === "member" ? "peserta" : "faskes"} (U4).
            </p>
          )}
          {user?.role === "auditor" && <p className="text-sm text-slate-500">Akses hanya-baca.</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {canExport && (
            <button className="btn-secondary" onClick={() => downloadFile("/claims/export.csv", "ekspor_klaim.csv").catch((e) => setError(e.message))}>
              Ekspor CSV
            </button>
          )}
          {isInsurer && <Link href="/klaim/baru" className="btn-primary">Unggah klaim</Link>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {isTpa && tenants.length > 0 && (
          <select className="input w-auto" value={insurerId} onChange={(e) => setInsurerId(e.target.value)}>
            <option value="">Semua asuransi</option>
            {tenants.map((t) => (
              <option key={t.insurer_id} value={t.insurer_id}>{t.display_name ?? t.name}</option>
            ))}
          </select>
        )}
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value as "" | ClaimStatus)}>
          <option value="">Semua status</option>
          {(Object.keys(STATUS_LABEL) as ClaimStatus[]).map((s) => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>
        {!statusOnly && (
          <select className="input w-auto" value={triage} onChange={(e) => setTriage(e.target.value as "" | Triage)}>
            {TRIAGE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        )}
        {isInsurer && candidates.length > 0 && (
          <div className="ml-auto flex items-center gap-2 text-sm">
            <button
              className="btn-secondary"
              onClick={() => setSelected(selected.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.id)))}
            >
              {selected.size === candidates.length ? "Batal pilih" : `Pilih semua hijau (${candidates.length})`}
            </button>
            <button className="btn-primary" disabled={busy || selected.size === 0} onClick={bulkAgree}>
              Setujui {selected.size || ""} klaim hijau
            </button>
          </div>
        )}
      </div>

      {message && <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div>}
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              {isInsurer && <th className="w-8 px-3 py-2" />}
              <th className="px-3 py-2">Nomor klaim</th>
              <th className="px-3 py-2">Rumah sakit</th>
              <th className="px-3 py-2">Rawat</th>
              <th className="px-3 py-2 text-right">Tagihan</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Triase</th>
              <th className="px-3 py-2">Rekomendasi</th>
              <th className="px-3 py-2">Keputusan</th>
            </tr>
          </thead>
          <tbody>
            {claims === null && (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-500">Memuat…</td></tr>
            )}
            {claims?.length === 0 && (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-500">Belum ada klaim.</td></tr>
            )}
            {claims?.map((c) => (
              <tr key={c.id} className="border-b last:border-0 hover:bg-slate-50">
                {isInsurer && (
                  <td className="px-3 py-2">
                    {isBulkCandidate(c) && (
                      <input type="checkbox" aria-label={`Pilih ${c.claim_number}`} checked={selected.has(c.id)} onChange={() => toggle(c.id)} />
                    )}
                  </td>
                )}
                <td className="px-3 py-2">
                  <Link href={`/klaim/${c.id}`} className="font-medium text-sky-800 hover:underline">{c.claim_number}</Link>
                  {c.patient_name && <div className="text-xs text-slate-500">{c.patient_name}</div>}
                </td>
                <td className="px-3 py-2">
                  {c.hospital_name}
                  {multiTenant && c.insurer_name && <div className="text-xs text-slate-500">{c.insurer_name}</div>}
                </td>
                <td className="whitespace-nowrap px-3 py-2">{tanggal(c.admission_date)} – {tanggal(c.discharge_date)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{rupiah(c.billed_amount)}</td>
                <td className="px-3 py-2"><StatusBadge status={c.status} /></td>
                <td className="px-3 py-2"><TriageBadge triage={c.triage_status} score={c.risk_score} /></td>
                <td className="px-3 py-2">{c.recommendation ? RECOMMENDATION_LABEL[c.recommendation] ?? c.recommendation : <span className="text-slate-400">—</span>}</td>
                <td className="px-3 py-2">{c.decision ? DECISION_LABEL[c.decision] ?? c.decision : <span className="text-slate-400">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
