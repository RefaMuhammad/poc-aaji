"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { PortalClaimDetail, PortalClaimItem } from "@/lib/types";
import { DOC_TYPE_LABEL, rupiah, tanggal, waktu } from "@/lib/format";
import { DocumentRequestList, LateUploadForm } from "@/components/DocumentRequests";

const LABEL_NOTE = "Data rekaan untuk demonstrasi";

function StatusPill({ item }: { item: PortalClaimItem }) {
  const style =
    item.status === "PENDING_DOCUMENTS"
      ? "bg-amber-100 text-amber-900"
      : item.status === "COMPLETED"
        ? "bg-emerald-50 text-emerald-800"
        : "bg-sky-50 text-sky-800";
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style}`}>{item.status_label}</span>;
}

/** Daftar klaim untuk portal faskes / peserta. Klaim yang menunggu dokumen ditaruh paling atas. */
export function PortalClaimList({ base, title, intro, showMember }: { base: string; title: string; intro: string; showMember: boolean }) {
  const [items, setItems] = useState<PortalClaimItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    apiJson<PortalClaimItem[]>("/portal/claims").then(setItems).catch((e) => setError(e.message));
  }, []);
  const waiting = items?.filter((i) => i.open_request) ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        <p className="text-sm text-slate-600">{intro}</p>
        <p className="mt-1 text-xs text-slate-400">{LABEL_NOTE}</p>
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      {waiting.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {waiting.length} klaim menunggu dokumen susulan
          {showMember ? " dari rumah sakit Anda." : ". Rumah sakit sudah diminta mengirimkannya."}
        </div>
      )}
      {items === null ? (
        <p className="text-sm text-slate-500">Memuat…</p>
      ) : items.length === 0 ? (
        <p className="card text-sm text-slate-500">Belum ada klaim.</p>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2">Nomor klaim</th>
                {showMember ? <th className="px-3 py-2">Peserta</th> : <th className="px-3 py-2">Rumah sakit</th>}
                <th className="px-3 py-2">Asuransi</th>
                <th className="px-3 py-2">Rawat</th>
                <th className="px-3 py-2 text-right">Tagihan</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className={`border-t ${i.open_request ? "bg-amber-50/50" : ""}`}>
                  <td className="px-3 py-2">
                    <Link href={`${base}/${i.id}`} className="font-medium text-sky-800 hover:underline">{i.claim_number}</Link>
                  </td>
                  <td className="px-3 py-2">{showMember ? `${i.patient_name ?? "-"} · ${i.member_id}` : i.hospital_name}</td>
                  <td className="px-3 py-2">{i.insurer_name ?? "-"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{tanggal(i.admission_date)} – {tanggal(i.discharge_date)}</td>
                  <td className="px-3 py-2 text-right">{rupiah(i.billed_amount)}</td>
                  <td className="px-3 py-2">
                    <StatusPill item={i} />
                    {i.open_request && (
                      <div className="mt-0.5 text-xs text-amber-800">
                        Diminta: {i.open_request.outstanding.map((t) => DOC_TYPE_LABEL[t] ?? t).join(", ")} · batas {tanggal(i.open_request.due_at)}
                      </div>
                    )}
                    {i.outcome && <div className="mt-0.5 text-xs text-slate-600">{i.outcome}</div>}
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

/** Detail klaim untuk faskes / peserta: status awam, permintaan dokumen, linimasa, penjelasan keputusan. */
export function PortalClaimView({ id, base, canUpload }: { id: string; base: string; canUpload: boolean }) {
  const [c, setC] = useState<PortalClaimDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    apiJson<PortalClaimDetail>(`/portal/claims/${id}`).then(setC).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  if (error && !c) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!c) return <p className="text-sm text-slate-500">Memuat…</p>;
  const open = c.open_request;

  return (
    <div className="space-y-5">
      <div>
        <Link href={base} className="text-sm text-sky-800 hover:underline">‹ Daftar klaim</Link>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">Klaim {c.claim_number}</h1>
          <StatusPill item={c} />
        </div>
        <p className="text-xs text-slate-400">{LABEL_NOTE}</p>
      </div>

      <div className="card grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div><div className="text-xs text-slate-500">Peserta</div>{c.patient_name ?? "-"} · {c.member_id}</div>
        <div><div className="text-xs text-slate-500">Rumah sakit</div>{c.hospital_name}</div>
        <div><div className="text-xs text-slate-500">Asuransi</div>{c.insurer_name ?? "-"}</div>
        <div><div className="text-xs text-slate-500">Tanggal rawat</div>{tanggal(c.admission_date)} – {tanggal(c.discharge_date)}</div>
        <div><div className="text-xs text-slate-500">Nilai tagihan</div>{rupiah(c.billed_amount)}</div>
        {c.recommended_amount !== null && c.decision && (
          <div><div className="text-xs text-slate-500">Nilai disetujui</div><b>{rupiah(c.recommended_amount)}</b></div>
        )}
      </div>

      {notice && (
        <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{notice}</div>
      )}
      {open && (
        <div className="card border-amber-300 bg-amber-50">
          <h2 className="font-medium text-amber-900">
            {canUpload ? "Asuransi meminta dokumen susulan" : "Klaim menunggu dokumen dari rumah sakit"}
          </h2>
          <p className="mt-1 text-sm text-amber-900">{open.message}</p>
          <p className="mt-1 text-xs text-amber-800">
            Diminta {waktu(open.created_at)} · batas {tanggal(open.due_at)}{open.overdue ? " (sudah lewat)" : ""}
          </p>
          {canUpload ? (
            <div className="mt-3 rounded bg-white p-3">
              <LateUploadForm claimId={c.id} request={open} endpoint={`/portal/claims/${c.id}/documents`}
                              onDone={(m) => { setNotice(m); load(); }} />
            </div>
          ) : (
            <p className="mt-2 text-sm text-amber-900">Anda tidak perlu melakukan apa pun. Kami akan memberi kabar lewat email.</p>
          )}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-5">
          {c.explanation && (
            <div className="card">
              <h2 className="mb-2 font-medium">{c.decision ? "Penjelasan keputusan" : "Keterangan"}</h2>
              <div className="whitespace-pre-line text-sm text-slate-700">{c.explanation}</div>
              {c.reviewer && <p className="mt-2 text-xs text-slate-500">Ditelaah oleh {c.reviewer}</p>}
            </div>
          )}
          <div className="card">
            <h2 className="mb-3 font-medium">Perjalanan klaim</h2>
            <ol className="relative space-y-3 border-l pl-4 text-sm">
              {c.timeline.map((e, i) => (
                <li key={i}>
                  <span className="absolute -left-1.5 mt-1 h-3 w-3 rounded-full border-2 border-white bg-sky-600" />
                  <div className="font-medium">{e.title}</div>
                  <div className="text-xs text-slate-500">{waktu(e.at)}{e.detail ? ` · ${e.detail}` : ""}</div>
                </li>
              ))}
            </ol>
          </div>
        </div>
        <aside className="space-y-5">
          <div className="card">
            <h2 className="mb-2 font-medium">Dokumen ({c.documents.length})</h2>
            <ul className="space-y-1 text-sm">
              {c.documents.map((d) => (
                <li key={d.id}>
                  <div className="truncate">{d.filename}</div>
                  <div className="text-xs text-slate-500">{DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type} · {waktu(d.created_at)}</div>
                </li>
              ))}
            </ul>
          </div>
          {c.document_requests.length > 0 && (
            <div className="card">
              <h2 className="mb-2 font-medium">Riwayat permintaan dokumen</h2>
              <DocumentRequestList requests={c.document_requests} />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
