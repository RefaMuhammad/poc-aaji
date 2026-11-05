"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiJson, downloadFile } from "@/lib/api";
import { FRAUD_MANAGE_ROLES, useAuth } from "@/lib/auth";
import type { FraudEntity, FraudImportResult, FraudOverview, FraudRuleset, FraudSignal, Tenant } from "@/lib/types";
import {
  FRAUD_ENTITY_LABEL, FRAUD_LEVEL_STYLE, FRAUD_REVIEW_LABEL, FRAUD_REVIEW_STYLE, FRAUD_SOURCE_LABEL, JOB_STATUS_LABEL,
  desimal, rupiah, tanggal, waktu,
} from "@/lib/format";
import { FraudGraph } from "@/components/FraudGraph";

const SEVERITY_STYLE: Record<string, string> = {
  HIGH: "bg-rose-50 text-rose-800 border-rose-200",
  MEDIUM: "bg-amber-50 text-amber-900 border-amber-200",
  LOW: "bg-slate-50 text-slate-700 border-slate-200",
};
const SEVERITY_LABEL: Record<string, string> = { HIGH: "Tinggi", MEDIUM: "Sedang", LOW: "Rendah", INFO: "Info" };

function ReviewBadge({ status }: { status: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-xs ${FRAUD_REVIEW_STYLE[status] ?? ""}`}>{FRAUD_REVIEW_LABEL[status] ?? status}</span>;
}

function formatValue(v: number | null, unit: string) {
  if (v === null) return "-";
  return unit === "rupiah" ? rupiah(Math.round(v)) : `${desimal(v, 1)} ${unit}`;
}

function ImportHistory({ insurerId, onDone }: { insurerId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<FraudImportResult | null>(null);
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
      const res = await apiFetch("/fraud/records/import", { method: "POST", body: fd });
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
        <input type="file" accept=".csv,.xlsx" className="text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5"
               onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button type="submit" className="btn-primary" disabled={!file || busy}>{busy ? "Mengimpor…" : "Impor riwayat klaim"}</button>
        <button type="button" className="text-xs text-sky-800 hover:underline"
                onClick={() => downloadFile("/fraud/records/template.csv", "template_riwayat_klaim.csv")}>Unduh templat CSV</button>
      </div>
      <p className="text-xs text-slate-500">
        Riwayat klaim dari sistem inti (kolom nomor_klaim, id_peserta, nama_peserta, alamat_peserta, rekening_bank, rumah_sakit, dokter,
        rujukan_dari, icd10, tanggal_masuk, tanggal_keluar, total_tagihan, jumlah_pemeriksaan_lab). Klaim yang diproses platform otomatis
        ikut dianalisis. Setelah impor, analisis dijalankan ulang. Contoh data rekaan: <code>data/synthetic_output/fraud/riwayat_klaim.csv</code>.
      </p>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      {result && (
        <div className={`rounded px-3 py-2 text-sm ${result.status === "SUCCESS" ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-900"}`}>
          {JOB_STATUS_LABEL[result.status]}: {result.created} klaim baru, {result.updated} diperbarui
          {result.run ? `; analisis menemukan ${result.run.signal_count} sinyal.` : "."}
          {result.errors.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{result.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        </div>
      )}
    </form>
  );
}

function ReviewForm({ signal, onSaved }: { signal: FraudSignal; onSaved: (s: FraudSignal) => void }) {
  const [status, setStatus] = useState(signal.review?.status ?? "INVESTIGATING");
  const [notes, setNotes] = useState(signal.review?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      onSaved(await apiJson<FraudSignal>(`/fraud/signals/${signal.id}/review`, { method: "PUT", body: JSON.stringify({ status, notes }) }));
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form onSubmit={save} className="space-y-2 rounded border bg-slate-50 p-3">
      <div className="text-sm font-medium">Telaah investigator</div>
      <div className="flex flex-wrap gap-3 text-sm">
        {(["INVESTIGATING", "CONFIRMED", "DISMISSED"] as const).map((s) => (
          <label key={s} className="inline-flex items-center gap-1">
            <input type="radio" name="status" checked={status === s} onChange={() => setStatus(s)} /> {FRAUD_REVIEW_LABEL[s]}
          </label>
        ))}
      </div>
      <textarea className="input min-h-[60px]" placeholder={status === "DISMISSED" ? "Wajib: alasan sinyal ini wajar" : "Catatan (opsional)"}
                value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} />
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex items-center gap-3">
        <button type="submit" className="btn-primary">Simpan telaah</button>
        <span className="text-xs text-slate-500">Telaah hanya mencatat hasil investigasi. Klaim tidak ditolak atau diubah otomatis.</span>
      </div>
    </form>
  );
}

function SignalDetail({ id, canManage, onChanged }: { id: string; canManage: boolean; onChanged: () => void }) {
  const [s, setS] = useState<FraudSignal | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setS(null);
    apiJson<FraudSignal>(`/fraud/signals/${id}`).then(setS).catch((e) => setError(e.message));
  }, [id]);
  if (error) return <p className="text-sm text-rose-700">{error}</p>;
  if (!s) return <p className="text-sm text-slate-500">Memuat bukti…</p>;
  const ev = s.evidence;
  const links = ev.claim_links ?? {};
  const cmp = ev.comparison?.[0];
  const maxIndex = Math.max(...(ev.peer_distribution ?? []).map((d) => d.index ?? 0), 1);
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded border px-1.5 py-0.5 ${SEVERITY_STYLE[s.severity] ?? ""}`}>{SEVERITY_LABEL[s.severity]}</span>
          <span className="font-mono text-slate-500">{s.rule_id}</span>
          <span className="text-slate-500">bobot {s.weight}</span>
          <ReviewBadge status={s.review?.status ?? "OPEN"} />
        </div>
        <h3 className="mt-1 font-semibold">{s.rule_name ?? s.reason_label}</h3>
        <p className="text-sm text-slate-500">{FRAUD_ENTITY_LABEL[s.entity_type]}: {s.entity_label}</p>
        <p className="mt-2 text-sm">{s.message}</p>
        {s.review && (
          <p className="mt-1 text-xs text-slate-500">
            {FRAUD_REVIEW_LABEL[s.review.status]} oleh {s.review.reviewed_by_name ?? "investigator"}, {waktu(s.review.reviewed_at)}
            {s.review.notes ? `: ${s.review.notes}` : ""}
          </p>
        )}
      </div>

      {cmp && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Angka pembanding</h4>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1 pr-2">Ukuran</th><th className="py-1 pr-2">Entitas ini</th><th className="py-1 pr-2">Rata-rata {cmp.peer_group}</th><th className="py-1 pr-2">Indeks</th><th className="py-1">z-score</th></tr>
            </thead>
            <tbody>
              <tr className="border-t">
                <td className="py-1.5 pr-2">{cmp.label}</td>
                <td className="py-1.5 pr-2 font-medium">{formatValue(cmp.value, cmp.unit)}</td>
                <td className="py-1.5 pr-2">{formatValue(cmp.peer, cmp.unit)}</td>
                <td className="py-1.5 pr-2">{desimal(cmp.index, 2)}</td>
                <td className="py-1.5">{desimal(cmp.z, 1)}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-500">
            Indeks = rata-rata nilai klaim dibagi median diagnosis yang sama (1,0 = sama dengan kebanyakan). z-score = jarak dari rata-rata
            sejawat dalam satuan simpangan baku.
          </p>
        </div>
      )}

      {ev.peer_distribution && ev.peer_distribution.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Sebaran indeks sejawat</h4>
          <div className="space-y-0.5">
            {ev.peer_distribution.map((d) => (
              <div key={d.name} className="flex items-center gap-2 text-xs">
                <span className={`w-48 truncate ${d.is_subject ? "font-semibold text-rose-800" : "text-slate-600"}`} title={d.name}>{d.name}</span>
                <div className="h-2.5 flex-1 rounded bg-slate-100">
                  <div className={`h-2.5 rounded ${d.is_subject ? "bg-rose-500" : "bg-slate-400"}`} style={{ width: `${((d.index ?? 0) / maxIndex) * 100}%` }} />
                </div>
                <span className="w-24 text-right tabular-nums">{desimal(d.index, 2)} · {d.claims} klaim</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {ev.relations && ev.relations.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Relasi</h4>
          <ul className="list-disc space-y-0.5 pl-5 text-sm">
            {ev.relations.slice(0, 20).map((r, i) => <li key={i}>{r.from} <span className="text-slate-500">→ {r.label} →</span> {r.to}</li>)}
          </ul>
        </div>
      )}

      {ev.graph && (
        <div>
          <h4 className="mb-1 text-sm font-medium">Graf relasi</h4>
          <FraudGraph nodes={ev.graph.nodes} edges={ev.graph.edges} />
        </div>
      )}

      {ev.claims && ev.claims.length > 0 && (
        <div>
          <h4 className="mb-1 text-sm font-medium">
            Klaim terkait ({s.claim_count}{ev.claims.length < s.claim_count ? `, ditampilkan ${ev.claims.length}` : ""})
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="py-1 pr-2">Nomor</th><th className="py-1 pr-2">Peserta</th><th className="py-1 pr-2">RS / dokter</th><th className="py-1 pr-2">Rawat</th><th className="py-1 pr-2">ICD</th><th className="py-1 pr-2 text-right">Tagihan</th><th className="py-1 text-right">Lab</th></tr>
              </thead>
              <tbody>
                {ev.claims.map((c) => (
                  <tr key={c.claim_number} className="border-t align-top">
                    <td className="py-1 pr-2 font-mono">
                      {links[c.claim_number] ? <Link className="text-sky-800 hover:underline" href={`/klaim/${links[c.claim_number]}`}>{c.claim_number}</Link> : c.claim_number}
                    </td>
                    <td className="py-1 pr-2">{c.member_id}</td>
                    <td className="py-1 pr-2">{c.hospital}{c.doctor ? <div className="text-slate-500">{c.doctor}</div> : null}{c.referral_from ? <div className="text-slate-500">rujukan dari {c.referral_from}</div> : null}</td>
                    <td className="py-1 pr-2 whitespace-nowrap">{tanggal(c.admission_date)} – {tanggal(c.discharge_date)} ({c.los_days} hr)</td>
                    <td className="py-1 pr-2">{c.icd10 ?? "-"}</td>
                    <td className="py-1 pr-2 text-right tabular-nums">{rupiah(c.billed_amount)}</td>
                    <td className="py-1 text-right tabular-nums">{c.lab_panels ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {canManage && <ReviewForm key={s.id} signal={s} onSaved={(n) => { setS(n); onChanged(); }} />}
    </div>
  );
}

export default function FraudMonitorPage() {
  const { user } = useAuth();
  const canManage = !!user && FRAUD_MANAGE_ROLES.includes(user.role);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [insurerId, setInsurerId] = useState<string | null>(null);
  const [overview, setOverview] = useState<FraudOverview | null>(null);
  const [signals, setSignals] = useState<FraudSignal[] | null>(null);
  const [rules, setRules] = useState<FraudRuleset | null>(null);
  const [entity, setEntity] = useState<FraudEntity | null>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiJson<Tenant[]>("/tenants")
      .then((t) => { setTenants(t); setInsurerId((id) => id ?? t[0]?.insurer_id ?? null); })
      .catch((e) => setError(e.message));
    apiJson<FraudRuleset>("/fraud/ruleset").then(setRules).catch(() => setRules(null));
  }, []);

  const load = useCallback(() => {
    if (!insurerId) return;
    setError(null);
    const qs = new URLSearchParams({ insurer_id: insurerId });
    if (typeFilter) qs.set("entity_type", typeFilter);
    if (statusFilter) qs.set("review_status", statusFilter);
    apiJson<FraudOverview>(`/fraud/overview?insurer_id=${encodeURIComponent(insurerId)}`).then(setOverview).catch((e) => setError(e.message));
    apiJson<FraudSignal[]>(`/fraud/signals?${qs}`).then(setSignals).catch((e) => setError(e.message));
  }, [insurerId, typeFilter, statusFilter]);
  useEffect(load, [load]);

  const runNow = async () => {
    if (!insurerId) return;
    setBusy(true);
    try {
      await apiJson(`/fraud/runs?insurer_id=${encodeURIComponent(insurerId)}`, { method: "POST" });
      setSelected(null);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const visible = (signals ?? []).filter((s) => !entity || (s.entity_type === entity.entity_type && s.entity_key === entity.entity_key));
  const providers = (overview?.entities ?? []).filter((e) => e.entity_type === "HOSPITAL" || e.entity_type === "DOCTOR");
  const others = (overview?.entities ?? []).filter((e) => e.entity_type !== "HOSPITAL" && e.entity_type !== "DOCTOR");

  const entityTable = (rows: FraudEntity[], empty: string) => (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-slate-500">
        <tr><th className="py-1 pr-2">Entitas</th><th className="py-1 pr-2">Skor fraud</th><th className="py-1 pr-2">Aturan</th><th className="py-1">Telaah</th></tr>
      </thead>
      <tbody>
        {rows.length === 0 && <tr><td colSpan={4} className="py-2 text-slate-500">{empty}</td></tr>}
        {rows.map((e) => {
          const active = entity?.entity_type === e.entity_type && entity.entity_key === e.entity_key;
          return (
            <tr key={`${e.entity_type}-${e.entity_key}`} className={`cursor-pointer border-t align-top hover:bg-slate-50 ${active ? "bg-sky-50" : ""}`}
                onClick={() => { setEntity(active ? null : e); setSelected(null); }}>
              <td className="py-1.5 pr-2">
                <div className="text-xs text-slate-500">{FRAUD_ENTITY_LABEL[e.entity_type]}</div>
                <div className="break-words">{e.entity_label}</div>
              </td>
              <td className="py-1.5 pr-2">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-16 rounded bg-slate-100"><div className="h-2 rounded bg-rose-500" style={{ width: `${e.score}%` }} /></div>
                  <span className="tabular-nums">{e.score}</span>
                  {e.level && <span className={`rounded px-1.5 py-0.5 text-xs ${FRAUD_LEVEL_STYLE[e.level] ?? ""}`}>{e.level}</span>}
                </div>
                <div className="text-xs text-slate-500">{e.claims} klaim</div>
              </td>
              <td className="py-1.5 pr-2 font-mono text-xs">{e.rule_ids.join(", ")}</td>
              <td className="py-1.5"><div className="flex flex-wrap gap-1">{e.review_statuses.map((st, i) => <ReviewBadge key={i} status={st} />)}</div></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Fraud Monitor</h1>
          <p className="max-w-3xl text-sm text-slate-500">
            Pola mencurigakan di banyak klaim: RS dan dokter yang menyimpang dari sejawat, serta relasi peserta, RS, rekening, dan alamat.
            Skor fraud terpisah dari skor risiko klinis. Setiap sinyal adalah bahan telaah investigator dan tidak pernah menolak klaim.
            Data rekaan untuk demonstrasi.
          </p>
        </div>
        {tenants.length > 1 && (
          <select className="input w-auto" value={insurerId ?? ""} onChange={(e) => { setInsurerId(e.target.value); setEntity(null); setSelected(null); }}>
            {tenants.map((t) => <option key={t.insurer_id} value={t.insurer_id}>{t.display_name ?? t.name}</option>)}
          </select>
        )}
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      {overview && (
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="card">
            <div className="text-xs text-slate-500">Klaim dianalisis</div>
            <div className="text-2xl font-semibold tabular-nums">{overview.record_count.toLocaleString("id-ID")}</div>
            <div className="text-xs text-slate-500">
              {Object.entries(overview.record_sources).map(([k, v]) => `${v.toLocaleString("id-ID")} ${FRAUD_SOURCE_LABEL[k] ?? k}`).join(" · ") || "belum ada data"}
            </div>
          </div>
          <div className="card">
            <div className="text-xs text-slate-500">Sinyal perlu ditelaah</div>
            <div className="text-2xl font-semibold tabular-nums">{overview.signals_open}</div>
            <div className="text-xs text-slate-500">
              {Object.entries(overview.signals_by_status).map(([k, v]) => `${v} ${FRAUD_REVIEW_LABEL[k]?.toLowerCase() ?? k}`).join(" · ") || "-"}
            </div>
          </div>
          <div className="card">
            <div className="text-xs text-slate-500">Provider berisiko</div>
            <div className="text-2xl font-semibold tabular-nums">{providers.length}</div>
            <div className="text-xs text-slate-500">RS atau dokter dengan sinyal</div>
          </div>
          <div className="card space-y-1">
            <div className="text-xs text-slate-500">Analisis terakhir</div>
            <div className="text-sm">{overview.last_run ? waktu(overview.last_run.created_at) : "Belum pernah"}</div>
            <div className="font-mono text-xs text-slate-500">{overview.ruleset_version}</div>
            {overview.stale && <div className="text-xs text-amber-800">Ada data baru sejak analisis terakhir.</div>}
            {canManage && (
              <button className="btn-secondary py-1 text-xs" onClick={runNow} disabled={busy || overview.record_count === 0}>
                {busy ? "Menganalisis…" : "Jalankan analisis"}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          <div className="card space-y-2">
            <h2 className="font-semibold">Provider berisiko</h2>
            {entityTable(providers, "Tidak ada RS atau dokter yang menyimpang dari sejawat.")}
          </div>
          <div className="card space-y-2">
            <h2 className="font-semibold">Peserta, rekening, alamat, rujukan</h2>
            {entityTable(others, "Tidak ada relasi mencurigakan.")}
          </div>
        </div>

        <div className="space-y-4 lg:col-span-3">
          <div className="card space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="font-semibold">Sinyal{entity ? `: ${entity.entity_label}` : ""}</h2>
              <div className="flex flex-wrap gap-2">
                {entity && <button className="text-xs text-sky-800 hover:underline" onClick={() => setEntity(null)}>Tampilkan semua</button>}
                <select className="input w-auto py-1 text-xs" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  <option value="">Semua entitas</option>
                  {Object.entries(FRAUD_ENTITY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <select className="input w-auto py-1 text-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                  <option value="">Semua status</option>
                  {Object.entries(FRAUD_REVIEW_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
            </div>
            {signals && visible.length === 0 && (
              <p className="text-sm text-slate-500">
                {overview?.last_run ? "Tidak ada sinyal untuk filter ini." : "Belum ada analisis. Impor riwayat klaim lalu jalankan analisis."}
              </p>
            )}
            <ul className="space-y-2">
              {visible.map((s) => (
                <li key={s.id}>
                  <button type="button" onClick={() => setSelected(selected === s.id ? null : s.id)}
                          className={`w-full rounded border px-3 py-2 text-left hover:bg-slate-50 ${selected === s.id ? "border-sky-400 bg-sky-50" : ""}`}>
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={`rounded border px-1.5 py-0.5 ${SEVERITY_STYLE[s.severity] ?? ""}`}>{SEVERITY_LABEL[s.severity]}</span>
                      <span className="font-mono text-slate-500">{s.rule_id}</span>
                      <span className="text-slate-600">{s.reason_label}</span>
                      <span className="text-slate-400">· {FRAUD_ENTITY_LABEL[s.entity_type]} · {s.claim_count} klaim · bobot {s.weight}</span>
                      <span className="ml-auto"><ReviewBadge status={s.review?.status ?? "OPEN"} /></span>
                    </div>
                    <p className="mt-1 text-sm">{s.message}</p>
                  </button>
                  {selected === s.id && (
                    <div className="mt-2 rounded border p-3">
                      <SignalDetail id={s.id} canManage={canManage} onChanged={load} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {canManage && insurerId && (
        <div className="card space-y-2">
          <h2 className="font-semibold">Data riwayat klaim</h2>
          <ImportHistory insurerId={insurerId} onDone={load} />
        </div>
      )}

      {rules && (
        <details className="card">
          <summary className="cursor-pointer font-semibold">Aturan fraud {rules.version}</summary>
          <p className="mt-2 text-xs text-slate-500">
            File <code>rules/aturan_fraud_demo.yaml</code>, terpisah dari aturan klinis. Skor fraud entitas = jumlah bobot sinyalnya (maks. 100).
          </p>
          <table className="mt-2 w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1 pr-2">Id</th><th className="py-1 pr-2">Aturan</th><th className="py-1 pr-2">Entitas</th><th className="py-1 pr-2">Kondisi</th><th className="py-1 text-right">Bobot</th></tr>
            </thead>
            <tbody>
              {rules.rules.map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="py-1.5 pr-2 font-mono text-xs">{r.id}</td>
                  <td className="py-1.5 pr-2">{r.name}</td>
                  <td className="py-1.5 pr-2 text-xs">{FRAUD_ENTITY_LABEL[r.entity_type]}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs">{r.condition}</td>
                  <td className="py-1.5 text-right tabular-nums">{r.weight}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
