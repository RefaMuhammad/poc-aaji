"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiJson, downloadFile } from "@/lib/api";
import { FRAUD_VIEW_ROLES, INSURER_ROLES, useAuth } from "@/lib/auth";
import type { ClaimDetail, ClaimStatus, Recommendation } from "@/lib/types";
import { DOC_TYPE_LABEL, IN_PROGRESS, POLICY_STATUS_LABEL, SOURCE_LABEL, rupiah, tanggal, waktu } from "@/lib/format";
import { StatusBadge } from "@/components/Badges";
import { RecommendationView } from "@/components/RecommendationView";
import { DecisionForm } from "@/components/DecisionForm";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { FraudClaimCard } from "@/components/FraudClaimCard";
import { DocumentRequestList, LateUploadForm, RequestDocumentsForm } from "@/components/DocumentRequests";

const STEPS: { status: ClaimStatus[]; label: string }[] = [
  { status: ["RECEIVED", "QUEUED"], label: "Diterima & antre" },
  { status: ["PROCESSING"], label: "Membaca dokumen & menilai" },
  { status: ["AWAITING_DOCTOR", "AWAITING_DECISION", "PENDING_DOCUMENTS", "COMPLETED"], label: "Rekomendasi siap" },
];

function Progress({ status }: { status: ClaimStatus }) {
  const current = STEPS.findIndex((s) => s.status.includes(status));
  return (
    <ol className="flex flex-wrap gap-2 text-xs">
      {STEPS.map((s, i) => (
        <li
          key={s.label}
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 ${
            i < current ? "bg-emerald-50 text-emerald-800" : i === current ? "bg-sky-100 font-medium text-sky-900" : "bg-slate-100 text-slate-400"
          }`}
        >
          {i < current ? "✓" : i === current && IN_PROGRESS.includes(status) ? <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" /> : <span>{i + 1}.</span>}
          <span>{s.label}</span>
        </li>
      ))}
    </ol>
  );
}

export default function ClaimDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const isInsurer = !!user && INSURER_ROLES.includes(user.role);
  const statusOnly = user?.role === "facility_officer" || user?.role === "member";
  const [claim, setClaim] = useState<ClaimDetail | null>(null);
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);

  const load = useCallback(async () => {
    try {
      const c = await apiJson<ClaimDetail>(`/claims/${id}`);
      setClaim(c);
      setRec(c.recommendation_available ? await apiJson<Recommendation>(`/claims/${id}/recommendation`) : null);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  // Selama diproses, cek status ringan tiap 2 detik lalu muat ulang saat berubah.
  const status = claim?.status;
  useEffect(() => {
    if (!status || !IN_PROGRESS.includes(status)) return;
    const t = setInterval(async () => {
      try {
        const s = await apiJson<{ status: ClaimStatus }>(`/claims/${id}/status`);
        if (s.status !== status) load();
      } catch {
        /* coba lagi di putaran berikutnya */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [id, status, load]);

  if (error && !claim) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!claim) return <div className="text-sm text-slate-500">Memuat…</div>;
  const openRequest = claim.document_requests?.find((r) => r.status === "OPEN") ?? null;

  return (
    <div className="space-y-5">
      <div>
        <Link href="/klaim" className="text-sm text-sky-800 hover:underline">‹ Daftar klaim</Link>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-lg font-semibold">
            Klaim {claim.claim_number}
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600" title="Kanal masuk klaim">
              via {SOURCE_LABEL[claim.source] ?? claim.source}
            </span>
          </h1>
          <div className="flex items-center gap-2">
            <StatusBadge status={claim.status} />
            {(user?.role === "doctor_gp" || user?.role === "doctor_specialist") && (
              <Link href={`/telaah/${id}`} className="btn-secondary">Buka ruang kerja dokter</Link>
            )}
            {rec && (
              <button
                className="btn-secondary"
                onClick={() => downloadFile(`/claims/${id}/recommendation.pdf`, `rekomendasi_${claim.claim_number}.pdf`).catch((e) => setError(e.message))}
              >
                Unduh PDF
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="card grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div><div className="text-slate-500">Peserta</div>{claim.patient_name ?? "-"} · {claim.member_id}</div>
        <div><div className="text-slate-500">Polis</div>{claim.policy_number}</div>
        <div><div className="text-slate-500">Rumah sakit</div>{claim.hospital_name}</div>
        <div><div className="text-slate-500">Rawat inap</div>{tanggal(claim.admission_date)} – {tanggal(claim.discharge_date)}</div>
        <div><div className="text-slate-500">Nilai tagihan</div>{rupiah(claim.billed_amount)}</div>
        <div><div className="text-slate-500">Diagnosis utama</div>{claim.primary_icd10 ?? "-"}</div>
      </div>

      {claim.policy && (
        <div className="card text-sm">
          <h2 className="mb-2 font-medium">Polis dan benefit</h2>
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-4">
            <div>
              <div className="text-slate-500">Plan</div>
              {claim.policy.plan_name} <span className="text-xs text-slate-400">({claim.policy.plan_code})</span>
            </div>
            <div>
              <div className="text-slate-500">Masa berlaku</div>
              {tanggal(claim.policy.start_date)} – {tanggal(claim.policy.end_date)} · {POLICY_STATUS_LABEL[claim.policy.status] ?? claim.policy.status}
            </div>
            <div>
              <div className="text-slate-500">Hak kamar</div>
              {claim.policy.room_class ?? "-"} · maks. {rupiah(claim.policy.room_rate_limit)}/hari
            </div>
            <div>
              <div className="text-slate-500">Sisa limit tahunan</div>
              {rupiah(claim.policy.limit_remaining)} <span className="text-xs text-slate-400">dari {rupiah(claim.policy.annual_limit)}</span>
            </div>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Masa tunggu {claim.policy.waiting_period_days} hari
            {claim.policy.excluded_icd10.length > 0 ? ` · pengecualian ${claim.policy.excluded_icd10.join(", ")}` : ""}. Data polis rekaan dari sistem inti asuransi.
          </p>
        </div>
      )}

      {user && FRAUD_VIEW_ROLES.includes(user.role) && <FraudClaimCard claimId={claim.id} />}

      <Progress status={claim.status} />
      {claim.status === "FAILED" && (
        <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Klaim gagal diproses{claim.processing_error ? `: ${claim.processing_error}` : ""}. Periksa dokumen lalu hubungi tim MAB.
        </div>
      )}
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      <div className="grid gap-5 lg:grid-cols-[18rem_1fr]">
        <aside className="space-y-3">
          <div className="card">
            <h2 className="mb-2 font-medium">Dokumen ({claim.documents.length})</h2>
            <ul className="space-y-1.5 text-sm">
              {claim.documents.map((d) => (
                <li key={d.id}>
                  <button
                    className="w-full text-left hover:text-sky-800 disabled:cursor-default disabled:hover:text-inherit"
                    disabled={statusOnly}
                    onClick={() => setViewer({ documentId: d.id, page: 1 })}
                  >
                    <div className="truncate">{d.filename}</div>
                    <div className="text-xs text-slate-500">
                      {DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type}
                      {d.page_count ? ` · ${d.page_count} hal.` : ""}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            {claim.missing_documents.length > 0 && (
              <div className="mt-3 rounded bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
                Belum ada: {claim.missing_documents.map((m) => DOC_TYPE_LABEL[m] ?? m).join(", ")}
              </div>
            )}
          </div>
          <div className="text-xs text-slate-400">Diperbarui {waktu(claim.updated_at)}</div>
        </aside>

        <div className="space-y-5">
          {statusOnly ? (
            <div className="card text-sm text-slate-600">
              Status, linimasa, dan penjelasan keputusan klaim ini ada di{" "}
              <Link className="text-sky-800 hover:underline" href={`/${user?.role === "member" ? "peserta" : "faskes"}/${id}`}>
                portal {user?.role === "member" ? "peserta" : "faskes"}
              </Link>.
            </div>
          ) : rec ? (
            <>
              {openRequest && (
                <div className="card border-amber-200 bg-amber-50">
                  <h3 className="font-medium text-amber-900">Menunggu dokumen susulan dari rumah sakit</h3>
                  <p className="mt-1 text-sm text-amber-900">
                    Klaim tidak bisa diputuskan sampai dokumen diterima. Setelah lengkap, klaim diproses ulang dan ditelaah dokter lagi.
                  </p>
                  {isInsurer && (
                    <details className="mt-3 text-sm">
                      <summary className="cursor-pointer text-sky-800">Dokumen sudah ada di asuransi? Unggah di sini</summary>
                      <div className="mt-2">
                        <LateUploadForm claimId={id} request={openRequest} endpoint={`/claims/${id}/documents`} withNote={false} onDone={() => load()} />
                      </div>
                    </details>
                  )}
                  {isInsurer && !rec.insurer_decision && (
                    <button className="btn-secondary mt-3" onClick={() => apiJson(`/claims/${id}/document-requests/cancel`, { method: "POST" }).then(load).catch((e) => setError(e.message))}>
                      Batalkan permintaan
                    </button>
                  )}
                </div>
              )}
              {claim.document_requests.length > 0 && (
                <div className="card">
                  <h3 className="mb-2 font-medium">Permintaan dokumen susulan</h3>
                  <DocumentRequestList requests={claim.document_requests} />
                </div>
              )}
              <RecommendationView rec={rec} documents={claim.documents} />
              {isInsurer && !(openRequest && !rec.insurer_decision) && (
                <DecisionForm rec={rec} missing={claim.missing_documents} onSaved={(r) => { setRec(r); load(); }} />
              )}
              {isInsurer && claim.status === "AWAITING_DECISION" && !rec.insurer_decision && rec.recommendation !== "PEND" && (
                <RequestDocumentsForm claimId={id} missing={claim.missing_documents} onDone={load} />
              )}
            </>
          ) : claim.awaiting_doctor ? (
            <div className="card border-violet-200 bg-violet-50 text-sm text-violet-900">
              Klaim ini perlu telaah dokter. Rekomendasi akan tampil setelah dokter menelaah dan menandatanganinya.
            </div>
          ) : IN_PROGRESS.includes(claim.status) ? (
            <div className="card text-sm text-slate-600">Dokumen sedang dibaca dan dinilai. Halaman ini diperbarui otomatis.</div>
          ) : claim.status !== "FAILED" ? (
            <div className="card text-sm text-slate-600">Rekomendasi belum tersedia.</div>
          ) : null}
        </div>
      </div>

      {viewer && <DocumentViewer target={viewer} documents={claim.documents} onClose={() => setViewer(null)} />}
    </div>
  );
}
