"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { TpaTenantSummary } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/format";
import type { ClaimStatus } from "@/lib/types";

/** TPA bekerja untuk beberapa asuransi sekaligus: satu kartu per asuransi yang dilayani. */
export default function TpaPage() {
  const [rows, setRows] = useState<TpaTenantSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    apiJson<TpaTenantSummary[]>("/tpa/summary").then(setRows).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Ringkasan TPA</h1>
        <p className="text-sm text-slate-600">
          Antrean klaim per asuransi yang Anda layani. Klaim baru diunggah atas nama salah satu asuransi.
        </p>
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      {rows === null ? (
        <p className="text-sm text-slate-500">Memuat…</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((r) => (
            <div key={r.insurer_id} className="card space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="font-medium">{r.insurer_name}</h2>
                <span className="text-sm text-slate-500">{r.total} klaim</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-sm">
                <div className="rounded bg-sky-50 p-2">
                  <div className="text-lg font-semibold text-sky-900">{r.awaiting_decision}</div>
                  <div className="text-xs text-sky-800">Menunggu keputusan</div>
                </div>
                <div className="rounded bg-amber-50 p-2">
                  <div className="text-lg font-semibold text-amber-900">{r.pending_documents}</div>
                  <div className="text-xs text-amber-800">Menunggu dokumen</div>
                </div>
                <div className={`rounded p-2 ${r.overdue_requests ? "bg-rose-50" : "bg-slate-50"}`}>
                  <div className={`text-lg font-semibold ${r.overdue_requests ? "text-rose-800" : "text-slate-700"}`}>{r.overdue_requests}</div>
                  <div className="text-xs text-slate-600">Dokumen lewat batas</div>
                </div>
              </div>
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
                {Object.entries(r.by_status).map(([s, n]) => (
                  <li key={s}>{STATUS_LABEL[s as ClaimStatus] ?? s}: <b>{n}</b></li>
                ))}
              </ul>
              <div className="flex gap-2">
                <Link className="btn-secondary" href={`/klaim?insurer_id=${r.insurer_id}`}>Lihat klaim</Link>
                <Link className="btn-secondary" href={`/klaim/baru?insurer_id=${r.insurer_id}`}>Unggah klaim</Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
