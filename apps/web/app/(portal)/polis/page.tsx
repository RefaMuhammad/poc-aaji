"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiJson, downloadFile } from "@/lib/api";
import { POLICY_MANAGE_ROLES, useAuth } from "@/lib/auth";
import type { BenefitPlan, Policy, PolicyImportResult, Tenant } from "@/lib/types";
import { JOB_STATUS_LABEL, POLICY_STATUS_LABEL, rupiah, tanggal } from "@/lib/format";
import { IntegrationLog } from "@/components/IntegrationLog";

const EMPTY_PLAN = { code: "", name: "", room_class: "Kelas 1", room_rate_limit: "", annual_limit: "", waiting_period_days: "30", excluded_icd10: "" };

function PlanForm({ insurerId, plan, onSaved, onCancel }: {
  insurerId: string;
  plan: BenefitPlan | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState(() =>
    plan
      ? {
          code: plan.code, name: plan.name, room_class: plan.room_class ?? "", room_rate_limit: String(plan.room_rate_limit ?? ""),
          annual_limit: String(plan.annual_limit ?? ""), waiting_period_days: String(plan.waiting_period_days),
          excluded_icd10: plan.excluded_icd10.join(", "),
        }
      : EMPTY_PLAN,
  );
  const [error, setError] = useState<string | null>(null);
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(/\./g, "")));
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await apiJson("/policies/plans", {
        method: "PUT",
        body: JSON.stringify({
          insurer_id: insurerId, code: form.code, name: form.name, room_class: form.room_class || null,
          room_rate_limit: num(form.room_rate_limit), annual_limit: num(form.annual_limit),
          waiting_period_days: Number(form.waiting_period_days || 0),
          excluded_icd10: form.excluded_icd10.split(/[,\s]+/).filter(Boolean),
        }),
      });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const field = (key: keyof typeof form, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <label className="block text-sm">
      <span className="text-slate-600">{label}</span>
      <input className="input mt-1" value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} {...extra} />
    </label>
  );
  return (
    <form onSubmit={save} className="space-y-2 rounded border bg-slate-50 p-3">
      <div className="grid gap-2 sm:grid-cols-4">
        {field("code", "Kode plan", { disabled: !!plan, placeholder: "SILVER" })}
        {field("name", "Nama plan", { placeholder: "Rawat Inap Silver" })}
        {field("room_class", "Hak kelas kamar")}
        {field("room_rate_limit", "Batas tarif kamar/hari (Rp)", { inputMode: "numeric" })}
        {field("annual_limit", "Limit tahunan (Rp)", { inputMode: "numeric" })}
        {field("waiting_period_days", "Masa tunggu (hari)", { inputMode: "numeric" })}
        <div className="sm:col-span-2">{field("excluded_icd10", "Pengecualian ICD-10 (awalan, pisahkan koma)", { placeholder: "O, Z30" })}</div>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn-primary">Simpan plan</button>
        <button type="button" className="btn-secondary" onClick={onCancel}>Batal</button>
      </div>
    </form>
  );
}

function ImportPolicies({ insurerId, onDone }: { insurerId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<PolicyImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("insurer_id", insurerId);
      const res = await apiFetch("/policies/import", { method: "POST", body: fd });
      setResult(await res.json());
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept=".csv,.xlsx"
          className="text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" className="btn-primary" disabled={!file || busy}>{busy ? "Mengimpor…" : "Impor polis"}</button>
        <button type="button" className="text-xs text-sky-800 hover:underline" onClick={() => downloadFile("/policies/template.csv", "template_polis.csv")}>
          Unduh templat CSV
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Kolom: nomor_polis, id_peserta, nama_peserta, kode_plan, tanggal_mulai, tanggal_akhir, status (ACTIVE/LAPSED/TERMINATED),
        limit_terpakai. Polis yang sudah ada (nomor polis + peserta sama) diperbarui. Sistem inti juga bisa mengirim lewat{" "}
        <code>PUT /integrations/v1/policies</code>.
      </p>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      {result && (
        <div className={`rounded px-3 py-2 text-sm ${result.status === "SUCCESS" ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-900"}`}>
          {JOB_STATUS_LABEL[result.status]}: {result.created} polis baru, {result.updated} diperbarui.
          {result.errors.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs">
              {result.errors.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      )}
    </form>
  );
}

export default function PolicyPage() {
  const { user } = useAuth();
  const canManage = !!user && POLICY_MANAGE_ROLES.includes(user.role);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [insurerId, setInsurerId] = useState<string | null>(null);
  const [plans, setPlans] = useState<BenefitPlan[] | null>(null);
  const [policies, setPolicies] = useState<Policy[] | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<BenefitPlan | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    apiJson<Tenant[]>("/tenants")
      .then((t) => {
        setTenants(t);
        setInsurerId((id) => id ?? t[0]?.insurer_id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  const load = useCallback(() => {
    if (!insurerId) return;
    const qs = `insurer_id=${encodeURIComponent(insurerId)}`;
    apiJson<BenefitPlan[]>(`/policies/plans?${qs}`).then(setPlans).catch((e) => setError(e.message));
    apiJson<Policy[]>(`/policies?${qs}${q ? `&q=${encodeURIComponent(q)}` : ""}`).then(setPolicies).catch((e) => setError(e.message));
  }, [insurerId, q]);
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const tenant = tenants.find((t) => t.insurer_id === insurerId) ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Polis &amp; benefit</h1>
          <p className="text-sm text-slate-500">
            Data polis dari sistem inti asuransi dipakai aturan benefit: polis aktif, masa tunggu, pengecualian diagnosis, sisa limit,
            dan hak kelas kamar. Bila tenant belum punya data polis, aturan benefit tidak dijalankan. Data rekaan untuk demonstrasi.
          </p>
        </div>
        {tenants.length > 1 && (
          <select className="input w-auto" value={insurerId ?? ""} onChange={(e) => setInsurerId(e.target.value)}>
            {tenants.map((t) => <option key={t.insurer_id} value={t.insurer_id}>{t.display_name ?? t.name}</option>)}
          </select>
        )}
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      {insurerId && (
        <>
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Plan benefit</h2>
              {canManage && editing === null && <button className="btn-secondary py-1 text-xs" onClick={() => setEditing("new")}>+ Plan baru</button>}
            </div>
            {editing !== null && (
              <PlanForm
                key={editing === "new" ? "new" : editing.id}
                insurerId={insurerId}
                plan={editing === "new" ? null : editing}
                onSaved={() => { setEditing(null); load(); }}
                onCancel={() => setEditing(null)}
              />
            )}
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr>
                  <th className="py-1 pr-2">Plan</th><th className="py-1 pr-2">Hak kamar</th><th className="py-1 pr-2">Limit tahunan</th>
                  <th className="py-1 pr-2">Masa tunggu</th><th className="py-1 pr-2">Pengecualian</th><th className="py-1 pr-2">Polis</th><th />
                </tr>
              </thead>
              <tbody>
                {plans?.length === 0 && <tr><td colSpan={7} className="py-2 text-slate-500">Belum ada plan. Buat plan dulu sebelum mengimpor polis.</td></tr>}
                {plans?.map((p) => (
                  <tr key={p.id} className="border-t">
                    <td className="py-1.5 pr-2">{p.name} <span className="font-mono text-xs text-slate-400">{p.code}</span></td>
                    <td className="py-1.5 pr-2">{p.room_class ?? "-"} · {rupiah(p.room_rate_limit)}/hari</td>
                    <td className="py-1.5 pr-2">{rupiah(p.annual_limit)}</td>
                    <td className="py-1.5 pr-2">{p.waiting_period_days} hari</td>
                    <td className="py-1.5 pr-2 font-mono text-xs">{p.excluded_icd10.join(", ") || "-"}</td>
                    <td className="py-1.5 pr-2">{p.policy_count}</td>
                    <td className="py-1.5 text-right">
                      {canManage && <button className="text-xs text-sky-800 hover:underline" onClick={() => setEditing(p)}>Ubah</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {canManage && (
            <div className="card space-y-2">
              <h2 className="font-semibold">Impor polis (CSV / XLSX)</h2>
              <ImportPolicies insurerId={insurerId} onDone={() => { load(); setTick((n) => n + 1); }} />
            </div>
          )}

          <div className="card space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold">Polis peserta {policies ? `(${policies.length}${policies.length === 200 ? "+" : ""})` : ""}</h2>
              <input className="input w-64" placeholder="Cari nomor polis, id atau nama peserta" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500">
                  <tr>
                    <th className="py-1 pr-2">Nomor polis</th><th className="py-1 pr-2">Peserta</th><th className="py-1 pr-2">Plan</th>
                    <th className="py-1 pr-2">Masa berlaku</th><th className="py-1 pr-2">Status</th><th className="py-1 pr-2">Sisa limit</th><th className="py-1">Sumber</th>
                  </tr>
                </thead>
                <tbody>
                  {policies?.length === 0 && <tr><td colSpan={7} className="py-2 text-slate-500">Belum ada polis.</td></tr>}
                  {policies?.map((p) => (
                    <tr key={p.id} className="border-t">
                      <td className="py-1.5 pr-2 font-mono text-xs">{p.policy_number}</td>
                      <td className="py-1.5 pr-2">{p.member_name ?? "-"} <span className="text-xs text-slate-400">{p.member_id}</span></td>
                      <td className="py-1.5 pr-2">{p.plan_code}</td>
                      <td className="py-1.5 pr-2 text-xs">{tanggal(p.start_date)} – {tanggal(p.end_date)}</td>
                      <td className="py-1.5 pr-2">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${p.status === "ACTIVE" ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
                          {POLICY_STATUS_LABEL[p.status] ?? p.status}
                        </span>
                      </td>
                      <td className="py-1.5 pr-2">{rupiah(p.limit_remaining)}</td>
                      <td className="py-1.5 text-xs">{p.source === "API" ? "API" : "Impor"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {tenant && <IntegrationLog key={`${tenant.insurer_id}-${tick}`} tenant={tenant} canResend={user?.role === "admin"} />}
        </>
      )}
    </div>
  );
}
