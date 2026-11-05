"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useState } from "react";
import { apiJson, downloadFile } from "@/lib/api";
import type { AuditPage, ClaimListItem, ReportDetail, ReportList, ReportRow } from "@/lib/types";
import { ROLE_LABEL, rupiah, tanggal, waktu } from "@/lib/format";

const LABEL_NOTE = "Data rekaan untuk demonstrasi";
const PAGE = 50;

const GROUP_STYLE: Record<string, string> = {
  AUTH: "bg-slate-100 text-slate-700",
  ACCESS: "bg-slate-100 text-slate-700",
  SYSTEM: "bg-sky-50 text-sky-800",
  REVIEW: "bg-violet-50 text-violet-800",
  DECISION: "bg-emerald-50 text-emerald-800",
  DOCUMENTS: "bg-amber-50 text-amber-900",
  DISPUTE: "bg-rose-50 text-rose-800",
  FRAUD: "bg-orange-50 text-orange-800",
  REPORT: "bg-indigo-50 text-indigo-800",
  ADMIN: "bg-slate-100 text-slate-700",
  OTHER: "bg-slate-50 text-slate-600",
};

function reportValue(r: ReportRow): string {
  if (r.value === null || r.value === undefined) return "-";
  if (r.unit === "rupiah" && typeof r.value === "number") return rupiah(r.value);
  const v = typeof r.value === "number" ? r.value.toLocaleString("id-ID", { maximumFractionDigits: 2 }) : String(r.value);
  return r.unit && r.unit !== "rupiah" ? `${v} ${r.unit}` : v;
}

function TraceSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState<ClaimListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const all = await apiJson<ClaimListItem[]>("/claims?limit=500");
      const term = q.trim().toLowerCase();
      const found = all.filter((c) => c.claim_number.toLowerCase().includes(term));
      if (found.length === 1) router.push(`/laporan/jejak/${found[0].id}`);
      else setMatches(found);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <div className="card">
      <h2 className="font-medium">Telusuri keputusan klaim</h2>
      <p className="mt-1 text-sm text-slate-600">
        Jejak lengkap satu klaim: unggah dokumen, penilaian sistem dan versinya, penugasan dan tanda tangan dokter, keputusan
        asuransi, dokumen susulan, dan banding.
      </p>
      <form onSubmit={search} className="mt-3 flex flex-wrap gap-2">
        <input className="input w-64" placeholder="Nomor klaim, mis. SYN-GEA-06" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-primary" disabled={!q.trim()}>Telusuri</button>
      </form>
      {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
      {matches && (
        matches.length === 0 ? <p className="mt-2 text-sm text-slate-500">Klaim tidak ditemukan.</p> : (
          <ul className="mt-2 space-y-1 text-sm">
            {matches.slice(0, 10).map((c) => (
              <li key={c.id}>
                <Link href={`/laporan/jejak/${c.id}`} className="text-sky-800 hover:underline">{c.claim_number}</Link>
                <span className="text-slate-500"> · {c.insurer_name ?? "-"} · {c.hospital_name}</span>
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}

type Filters = { claim_number: string; user: string; action: string; group: string; date_from: string; date_to: string };
const EMPTY: Filters = { claim_number: "", user: "", action: "", group: "", date_from: "", date_to: "" };

function AuditLogView() {
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditPage | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const params = (f: Filters) => {
    const p = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => { if (v) p.set(k, v); });
    return p;
  };
  useEffect(() => {
    const p = params(filters);
    p.set("limit", String(PAGE));
    p.set("offset", String(offset));
    apiJson<AuditPage>(`/audit/logs?${p}`).then(setPage).catch((e) => setError(e.message));
  }, [filters, offset]);

  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const apply = (e: React.FormEvent) => { e.preventDefault(); setOffset(0); setFilters(draft); };

  return (
    <div className="space-y-3">
      <form onSubmit={apply} className="card grid gap-3 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <label className="block"><span className="text-xs text-slate-500">Nomor klaim</span>
          <input className="input mt-1" value={draft.claim_number} onChange={set("claim_number")} placeholder="SYN-…" /></label>
        <label className="block"><span className="text-xs text-slate-500">Pengguna (nama/email)</span>
          <input className="input mt-1" value={draft.user} onChange={set("user")} /></label>
        <label className="block"><span className="text-xs text-slate-500">Kelompok aksi</span>
          <select className="input mt-1" value={draft.group} onChange={set("group")}>
            <option value="">Semua</option>
            {Object.entries(page?.groups ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <label className="block"><span className="text-xs text-slate-500">Kode aksi</span>
          <input className="input mt-1" value={draft.action} onChange={set("action")} placeholder="mis. SIGNED" /></label>
        <label className="block"><span className="text-xs text-slate-500">Dari tanggal</span>
          <input type="date" className="input mt-1" value={draft.date_from} onChange={set("date_from")} /></label>
        <label className="block"><span className="text-xs text-slate-500">Sampai tanggal</span>
          <input type="date" className="input mt-1" value={draft.date_to} onChange={set("date_to")} /></label>
        <div className="flex flex-wrap gap-2 sm:col-span-3 lg:col-span-6">
          <button className="btn-primary">Terapkan</button>
          <button type="button" className="btn-secondary" onClick={() => { setDraft(EMPTY); setFilters(EMPTY); setOffset(0); }}>Reset</button>
          <button type="button" className="btn-secondary ml-auto"
                  onClick={() => downloadFile(`/audit/logs/xlsx?${params(filters)}`, "log_audit.xlsx").catch((e) => setError(e.message))}>
            Ekspor Excel
          </button>
        </div>
      </form>
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      {!page ? <p className="text-sm text-slate-500">Memuat…</p> : (
        <div className="card overflow-x-auto p-0">
          <div className="flex items-center justify-between border-b px-3 py-2 text-xs text-slate-500">
            <span>{page.total.toLocaleString("id-ID")} entri · log tidak dapat diubah atau dihapus</span>
            <span className="flex items-center gap-2">
              <button className="hover:underline disabled:opacity-40" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹ Sebelumnya</button>
              {page.total ? `${offset + 1}–${Math.min(offset + PAGE, page.total)}` : "0"}
              <button className="hover:underline disabled:opacity-40" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>Berikutnya ›</button>
            </span>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-3 py-2">Waktu</th><th className="px-3 py-2">Aksi</th><th className="px-3 py-2">Pengguna</th>
                <th className="px-3 py-2">Klaim</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {page.items.map((e) => (
                <Fragment key={e.id}>
                  <tr className="cursor-pointer border-t hover:bg-slate-50" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{waktu(e.occurred_at)}</td>
                    <td className="px-3 py-2">
                      <span className={`mr-2 rounded px-1.5 py-0.5 text-xs ${GROUP_STYLE[e.group] ?? ""}`}>{page.groups[e.group] ?? e.group}</span>
                      {e.label}
                      {e.document_name && <span className="text-slate-500"> · {e.document_name}</span>}
                    </td>
                    <td className="px-3 py-2">
                      {e.user_name ?? "-"}
                      {e.user_role && <span className="text-xs text-slate-500"> · {ROLE_LABEL[e.user_role] ?? e.user_role}</span>}
                    </td>
                    <td className="px-3 py-2">
                      {e.claim_id && e.claim_number ? (
                        <Link href={`/laporan/jejak/${e.claim_id}`} className="text-sky-800 hover:underline" onClick={(ev) => ev.stopPropagation()}>
                          {e.claim_number}
                        </Link>
                      ) : "-"}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">{e.status_code ?? ""}</td>
                  </tr>
                  {open === e.id && (
                    <tr className="bg-slate-50">
                      <td colSpan={5} className="px-3 py-2 text-xs text-slate-700">
                        <div className="font-mono">#{e.id} · {e.action}{e.method ? ` · ${e.method} ${e.path}` : ""}{e.ip_address ? ` · IP ${e.ip_address}` : ""}{e.user_email ? ` · ${e.user_email}` : ""}</div>
                        {Object.keys(e.detail).length > 0 && (
                          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2">{JSON.stringify(e.detail, null, 2)}</pre>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {page.items.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500">Tidak ada entri.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ReportBody({ report }: { report: ReportDetail }) {
  const d = report.data;
  return (
    <div className="space-y-4">
      <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        {d.label}. {d.template_note}
      </div>
      {d.sections.map((s) => (
        <section key={s.id} className="card">
          <h3 className="font-medium">{s.id}. {s.title}</h3>
          {s.basis && <p className="mt-0.5 text-xs text-slate-500">Dasar: {s.basis}</p>}
          <table className="mt-3 w-full text-sm">
            <tbody>
              {s.rows.map((r) => (
                <tr key={r.label} className="border-t">
                  <td className="py-1.5 pr-3 text-slate-600">{r.label}</td>
                  <td className="py-1.5 pr-3 text-right font-medium tabular-nums">{reportValue(r)}</td>
                  <td className="py-1.5 text-xs text-slate-500">{r.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.tables.map((t) => (
            <div key={t.title} className="mt-4">
              <h4 className="mb-1 text-sm text-slate-600">{t.title}</h4>
              {t.rows.length === 0 ? <p className="text-xs text-slate-400">(tidak ada)</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left text-xs text-slate-500">
                      <tr>{t.columns.map((c) => <th key={c} className="px-2 py-1">{c}</th>)}</tr>
                    </thead>
                    <tbody>
                      {t.rows.map((row, i) => (
                        <tr key={i} className="border-t">{row.map((v, j) => <td key={j} className="px-2 py-1">{v ?? "-"}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function ReportsView() {
  const [list, setList] = useState<ReportList | null>(null);
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [period, setPeriod] = useState(thisMonth());
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiJson<ReportList>("/reports").then((l) => {
      setList(l);
      setScope((s) => s || (l.insurers.length === 1 && !l.can_platform ? l.insurers[0].id : l.can_platform ? "" : l.insurers[0]?.id ?? ""));
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  const open = (id: string) => apiJson<ReportDetail>(`/reports/${id}`).then(setSelected).catch((e) => setError(e.message));

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiJson<ReportDetail>("/reports", { method: "POST", body: JSON.stringify({ period, insurer_id: scope || null }) });
      setSelected(r);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!list) return <p className="text-sm text-slate-500">{error ?? "Memuat…"}</p>;
  const fileBase = (r: ReportDetail) => `laporan_pojk36_${r.period}_r${r.revision}`;
  return (
    <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
      <aside className="space-y-4">
        <div className="card text-sm">
          <h2 className="font-medium">Laporan bulanan kepatuhan</h2>
          <p className="mt-1 text-slate-600">
            Dibuat otomatis tiap awal bulan untuk bulan sebelumnya. Jadwal berikutnya: <b>{tanggal(list.next_scheduled)}</b>.
          </p>
          <p className="mt-1 text-xs text-slate-500">Templat {list.template_version}</p>
          {list.can_generate && (
            <div className="mt-3 space-y-2 border-t pt-3">
              <div className="text-xs font-medium text-slate-600">Buat sekarang</div>
              <input type="month" className="input" value={period} onChange={(e) => setPeriod(e.target.value)} />
              <select className="input" value={scope} onChange={(e) => setScope(e.target.value)}>
                {list.can_platform && <option value="">Seluruh tenant</option>}
                {list.insurers.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
              </select>
              <button className="btn-primary w-full" disabled={busy || !period} onClick={generate}>
                {busy ? "Membuat…" : "Buat laporan"}
              </button>
              <p className="text-xs text-slate-500">Membuat ulang periode yang sama menaikkan nomor revisi.</p>
            </div>
          )}
        </div>
        <div className="card p-0">
          {list.items.length === 0 ? <p className="p-3 text-sm text-slate-500">Belum ada laporan.</p> : (
            <ul className="divide-y text-sm">
              {list.items.map((r) => (
                <li key={r.id}>
                  <button className={`w-full px-3 py-2 text-left hover:bg-slate-50 ${selected?.id === r.id ? "bg-sky-50" : ""}`} onClick={() => open(r.id)}>
                    <div className="font-medium">{r.period} · {r.insurer_name ?? "Seluruh tenant"}</div>
                    <div className="text-xs text-slate-500">
                      revisi {r.revision} · {r.trigger === "SCHEDULED" ? "otomatis" : `manual${r.generated_by ? `, ${r.generated_by}` : ""}`}
                      {r.partial ? " · sementara" : ""} · {waktu(r.generated_at)}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
      <div className="space-y-4">
        {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
        {!selected ? <p className="card text-sm text-slate-500">Pilih laporan di sebelah kiri.</p> : (
          <>
            <div className="card flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">{selected.data.title}</h2>
                <p className="text-sm text-slate-600">
                  {selected.insurer_name ?? "Seluruh tenant"} · periode {selected.period} · revisi {selected.revision}
                  {selected.partial && <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">periode berjalan</span>}
                </p>
              </div>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={() => downloadFile(`/reports/${selected.id}/pdf`, `${fileBase(selected)}.pdf`).catch((e) => setError(e.message))}>Unduh PDF</button>
                <button className="btn-secondary" onClick={() => downloadFile(`/reports/${selected.id}/xlsx`, `${fileBase(selected)}.xlsx`).catch((e) => setError(e.message))}>Unduh Excel</button>
              </div>
            </div>
            <ReportBody report={selected} />
          </>
        )}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const [tab, setTab] = useState<"reports" | "audit">("reports");
  const tabBtn = (k: typeof tab, label: string) => (
    <button className={`border-b-2 px-3 py-2 text-sm ${tab === k ? "border-sky-700 font-medium text-sky-900" : "border-transparent text-slate-600"}`}
            onClick={() => setTab(k)}>{label}</button>
  );
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Laporan & Audit</h1>
        <p className="text-sm text-slate-600">Laporan bulanan kepatuhan POJK 36/2025, log audit, dan jejak keputusan per klaim. Hanya-baca untuk auditor.</p>
        <p className="mt-1 text-xs text-slate-400">{LABEL_NOTE}</p>
      </div>
      <TraceSearch />
      <div className="flex gap-1 border-b">
        {tabBtn("reports", "Laporan bulanan")}
        {tabBtn("audit", "Log audit")}
      </div>
      {tab === "reports" ? <ReportsView /> : <AuditLogView />}
    </div>
  );
}
