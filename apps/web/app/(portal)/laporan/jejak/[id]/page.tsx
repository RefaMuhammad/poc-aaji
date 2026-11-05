"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiJson, downloadFile } from "@/lib/api";
import type { ClaimTrace } from "@/lib/types";
import { DOC_TYPE_LABEL, STATUS_LABEL, rupiah, waktu } from "@/lib/format";

const STAGE_STYLE: Record<string, string> = {
  "Penerimaan": "bg-slate-500",
  "Pemrosesan sistem": "bg-sky-600",
  "Telaah dokter": "bg-violet-600",
  "Keputusan asuransi": "bg-emerald-600",
  "Dokumen susulan": "bg-amber-500",
  "Banding": "bg-rose-600",
  "Akses & lainnya": "bg-slate-300",
};

export default function ClaimTracePage() {
  const { id } = useParams<{ id: string }>();
  const [t, setT] = useState<ClaimTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<string[]>(["Akses & lainnya"]);
  const [showLog, setShowLog] = useState(false);
  useEffect(() => {
    apiJson<ClaimTrace>(`/audit/claims/${id}/trace`).then(setT).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!t) return <p className="text-sm text-slate-500">Memuat…</p>;
  const c = t.claim;
  const steps = t.steps.filter((s) => !hidden.includes(s.stage));
  const toggle = (s: string) => setHidden((h) => (h.includes(s) ? h.filter((x) => x !== s) : [...h, s]));

  return (
    <div className="space-y-5">
      <div>
        <Link href="/laporan" className="text-sm text-sky-800 hover:underline">‹ Laporan & Audit</Link>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Jejak keputusan klaim {c.claim_number}</h1>
          <div className="flex gap-2">
            <Link href={`/klaim/${c.id}`} className="btn-secondary">Buka klaim</Link>
            <button className="btn-secondary"
                    onClick={() => downloadFile(`/audit/claims/${c.id}/trace/pdf`, `jejak_${c.claim_number}.pdf`).catch((e) => setError(e.message))}>
              Unduh PDF
            </button>
          </div>
        </div>
        <p className="text-sm text-slate-600">
          {c.insurer_name ?? "-"} · {c.hospital_name} · peserta {c.member_id} · tagihan {rupiah(c.billed_amount)} · status{" "}
          {STATUS_LABEL[c.status] ?? c.status}
        </p>
        <p className="text-xs text-slate-400">{t.label}</p>
      </div>

      <div className="card border-sky-200 bg-sky-50">
        <h2 className="mb-2 font-medium text-sky-900">Mata rantai keputusan</h2>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-sky-950">
          {t.chain.map((line, i) => <li key={i}>{line}</li>)}
        </ol>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <div className="card">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-medium">Linimasa ({steps.length} kejadian)</h2>
            <div className="flex flex-wrap gap-1">
              {t.stages.map((s) => (
                <button key={s} onClick={() => toggle(s)}
                        className={`flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${hidden.includes(s) ? "text-slate-400" : "text-slate-700"}`}>
                  <span className={`h-2 w-2 rounded-full ${STAGE_STYLE[s] ?? "bg-slate-400"} ${hidden.includes(s) ? "opacity-30" : ""}`} />{s}
                </button>
              ))}
            </div>
          </div>
          <ol className="relative space-y-3 border-l pl-4 text-sm">
            {steps.map((s, i) => (
              <li key={i}>
                <span className={`absolute -left-1.5 mt-1 h-3 w-3 rounded-full border-2 border-white ${STAGE_STYLE[s.stage] ?? "bg-slate-400"}`} />
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{s.title}</span>
                  <span className="whitespace-nowrap text-xs text-slate-500">{waktu(s.at)}</span>
                </div>
                <div className="text-xs text-slate-600">{s.stage}{s.actor ? ` · ${s.actor}` : ""}</div>
                {s.detail && <div className="mt-0.5 whitespace-pre-line text-xs text-slate-500">{s.detail}</div>}
              </li>
            ))}
          </ol>
        </div>
        <aside className="space-y-5">
          <div className="card">
            <h2 className="mb-2 font-medium">Dokumen sumber ({t.documents.length})</h2>
            <ul className="space-y-2 text-sm">
              {t.documents.map((d) => (
                <li key={d.id}>
                  <div className="truncate">{d.filename}</div>
                  <div className="text-xs text-slate-500">{DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type} · {waktu(d.created_at)}</div>
                  <div className="break-all font-mono text-[10px] text-slate-400" title="SHA-256">{d.sha256}</div>
                </li>
              ))}
            </ul>
          </div>
          <div className="card text-sm">
            <h2 className="mb-1 font-medium">Log audit klaim</h2>
            <p className="text-slate-600">{t.audit.length} entri tercatat untuk klaim ini, tidak dapat diubah.</p>
            <button className="mt-2 text-xs text-sky-800 hover:underline" onClick={() => setShowLog(!showLog)}>
              {showLog ? "Sembunyikan" : "Tampilkan"} entri mentah
            </button>
          </div>
        </aside>
      </div>

      {showLog && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr><th className="px-3 py-2">#</th><th className="px-3 py-2">Waktu</th><th className="px-3 py-2">Aksi</th>
                <th className="px-3 py-2">Pengguna</th><th className="px-3 py-2">Rincian</th></tr>
            </thead>
            <tbody>
              {t.audit.map((a) => (
                <tr key={a.id} className="border-t align-top">
                  <td className="px-3 py-1.5 font-mono text-slate-400">{a.id}</td>
                  <td className="whitespace-nowrap px-3 py-1.5">{waktu(a.occurred_at)}</td>
                  <td className="px-3 py-1.5">{a.label}<div className="font-mono text-slate-400">{a.action}</div></td>
                  <td className="px-3 py-1.5">{a.user_name ?? "-"}</td>
                  <td className="max-w-md px-3 py-1.5 font-mono text-slate-500">
                    {Object.keys(a.detail).length ? JSON.stringify(a.detail) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
