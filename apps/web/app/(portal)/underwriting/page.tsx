"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import { useAuth, DOCTOR_ROLES } from "@/lib/auth";
import { rupiah, waktu } from "@/lib/format";
import { UW_REC_LABEL, UW_REC_STYLE, UW_STATUS_LABEL, type UwList, type UwStatus, type UwSummary } from "@/lib/underwriting";

const TABS: { key: string; label: string; statuses: UwStatus[] | null }[] = [
  { key: "all", label: "Semua", statuses: null },
  { key: "doctor", label: "Menunggu dokter", statuses: ["AWAITING_DOCTOR"] },
  { key: "underwriter", label: "Menunggu underwriter", statuses: ["AWAITING_UNDERWRITER"] },
  { key: "decided", label: "Diputuskan", statuses: ["DECIDED"] },
  { key: "processing", label: "Diproses / gagal", statuses: ["QUEUED", "PROCESSING", "FAILED"] },
];

function SubmitForm({ onDone }: { onDone: (id: string) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      files.forEach((f) => body.append("files", f));
      const res = await apiFetch("/underwriting/applications", { method: "POST", body });
      const app = (await res.json()) as UwSummary;
      setFiles([]);
      onDone(app.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="card space-y-2">
      <h2 className="font-medium">Ajukan calon peserta</h2>
      <p className="text-sm text-slate-600">
        Unggah SPAJ, kuesioner kesehatan, hasil MCU, hasil laboratorium, dan surat keterangan dokter (bila ada) dalam
        satu pengajuan. PDF, JPG, atau PNG. Sistem membaca dokumen, menerapkan aturan underwriting, lalu menyusun draf
        rekomendasi.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png" aria-label="Dokumen pengajuan"
               onChange={(e) => setFiles(Array.from(e.target.files ?? []))} className="text-sm" />
        <button className="btn-primary" disabled={busy || files.length === 0}>{busy ? "Mengunggah…" : `Ajukan (${files.length} dokumen)`}</button>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}
    </form>
  );
}

function RecBadge({ a }: { a: UwSummary }) {
  if (!a.recommendation) return <span className="text-slate-400">-</span>;
  return (
    <div>
      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${UW_REC_STYLE[a.recommendation]}`}>{UW_REC_LABEL[a.recommendation]}</span>
      <div className="mt-0.5 text-xs text-slate-500">
        {a.decision ? "keputusan final" : a.terms_source === "doctor" ? `ditandatangani ${a.signed_by}` : "draf sistem"}
      </div>
    </div>
  );
}

export default function UnderwritingQueuePage() {
  const { user } = useAuth();
  const router = useRouter();
  const isDoctor = DOCTOR_ROLES.includes(user?.role ?? "");
  const [tab, setTab] = useState(isDoctor ? "doctor" : "all");
  const [q, setQ] = useState("");
  const [data, setData] = useState<UwList | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiJson<UwList>("/underwriting/applications").then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  // muat ulang selama ada pengajuan yang sedang diproses
  useEffect(() => {
    if (!data?.items.some((a) => a.status === "QUEUED" || a.status === "PROCESSING")) return;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [data, load]);

  const statuses = TABS.find((t) => t.key === tab)?.statuses;
  const needle = q.trim().toLowerCase();
  const items = (data?.items ?? []).filter((a) => (!statuses || statuses.includes(a.status)) &&
    (!needle || [a.application_number, a.spaj_number, a.applicant_name].join(" ").toLowerCase().includes(needle)));
  const count = (s: UwStatus[] | null) => (s ? s.reduce((n, x) => n + (data?.counts[x] ?? 0), 0) : data?.items.length ?? 0);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Underwriting medis</h1>
        <p className="text-sm text-slate-600">
          Rekomendasi selain terima standar (bersyarat, tunda, tolak) wajib ditelaah dan ditandatangani dokter sebelum
          underwriter memutuskan. {data && <>Aturan <span className="font-mono text-xs">{data.rules_version}</span>.</>}
        </p>
        <p className="text-xs text-slate-400">Data rekaan untuk demonstrasi</p>
      </div>
      {data?.can_submit && <SubmitForm onDone={(id) => router.push(`/underwriting/${id}`)} />}
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
                    className={`rounded border px-2.5 py-1 text-sm ${tab === t.key ? "border-sky-700 bg-sky-50 text-sky-900" : "text-slate-600"}`}>
              {t.label} <span className="text-xs text-slate-400">{count(t.statuses)}</span>
            </button>
          ))}
        </div>
        <input className="input max-w-xs" placeholder="Cari nama, no. pengajuan, SPAJ" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2">Pengajuan</th><th className="px-3 py-2">Calon peserta</th><th className="px-3 py-2">Produk</th>
              <th className="px-3 py-2">Rekomendasi</th><th className="px-3 py-2">Kelas · loading</th><th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Diperbarui</th>
            </tr>
          </thead>
          <tbody>
            {!data && <tr><td colSpan={7} className="px-3 py-4 text-slate-500">Memuat…</td></tr>}
            {data && items.length === 0 && <tr><td colSpan={7} className="px-3 py-4 text-slate-500">Tidak ada pengajuan.</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="cursor-pointer border-t align-top hover:bg-slate-50" onClick={() => router.push(`/underwriting/${a.id}`)}>
                <td className="px-3 py-2">
                  <Link href={`/underwriting/${a.id}`} className="font-medium text-sky-800 hover:underline">{a.application_number}</Link>
                  <div className="text-xs text-slate-500">{a.spaj_number ?? "SPAJ belum terbaca"}</div>
                </td>
                <td className="px-3 py-2">{a.applicant_name ?? "-"}<div className="text-xs text-slate-500">{a.insurer_name}</div></td>
                <td className="px-3 py-2">{a.product_name ?? "-"}<div className="text-xs text-slate-500">UP {rupiah(a.sum_assured)}</div></td>
                <td className="px-3 py-2"><RecBadge a={a} /></td>
                <td className="px-3 py-2">{data?.labels.classes.find((c) => c.code === a.risk_class)?.name ?? a.risk_class ?? "-"}{a.loading_pct ? ` · +${a.loading_pct}%` : ""}</td>
                <td className="px-3 py-2">{UW_STATUS_LABEL[a.status]}</td>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{waktu(a.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
