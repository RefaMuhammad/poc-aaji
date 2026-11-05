"use client";

import { useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import type { DisputeInfo } from "@/lib/types";
import {
  DISPUTE_CATEGORIES,
  DISPUTE_OUTCOME_LABEL,
  DISPUTE_STATUS_LABEL,
  DOC_TYPE_LABEL,
  RECOMMENDATION_LABEL,
  REQUESTABLE_DOC_TYPES,
  ROLE_LABEL,
  rupiah,
  tanggal,
  waktu,
} from "@/lib/format";

const STATUS_STYLE: Record<string, string> = {
  IN_REVIEW: "bg-amber-50 text-amber-800",
  AWAITING_DECISION: "bg-sky-50 text-sky-800",
  RESOLVED: "bg-emerald-50 text-emerald-800",
  WITHDRAWN: "bg-slate-100 text-slate-600",
};

const recLabel = (r: string | null) => (r ? RECOMMENDATION_LABEL[r] ?? r : "-");
const filerLabel = (role: string) => (role === "member" ? "Peserta" : role === "facility_officer" ? "Faskes" : ROLE_LABEL[role] ?? role);

export function DisputeStatusPill({ status }: { status: string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status] ?? ""}`}>
      {DISPUTE_STATUS_LABEL[status] ?? status}
    </span>
  );
}

/** Riwayat banding satu klaim. `internal` menampilkan nama dokter dan rekomendasi (untuk asuransi). */
export function DisputeList({ disputes, internal = false }: { disputes: DisputeInfo[]; internal?: boolean }) {
  if (disputes.length === 0) return null;
  return (
    <ul className="space-y-3">
      {disputes.map((d) => (
        <li key={d.id} className="rounded border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">Banding {filerLabel(d.raised_by_role).toLowerCase()} · {d.category_label}</span>
            <DisputeStatusPill status={d.status} />
          </div>
          <p className="mt-1 whitespace-pre-line text-slate-700">{d.reason}</p>
          <p className="mt-1 text-xs text-slate-500">
            Diajukan {d.raised_by} · {waktu(d.created_at)}
            {d.document_ids.length > 0 ? ` · ${d.document_ids.length} dokumen pendukung` : ""}
            {(d.status === "IN_REVIEW" || d.status === "AWAITING_DECISION") && (
              <>
                {" "}· SLA{" "}
                <span className={d.overdue ? "font-medium text-rose-700" : ""}>{tanggal(d.due_at)}{d.overdue ? " (lewat)" : ""}</span>
              </>
            )}
          </p>
          {internal && (
            <p className="mt-1 text-xs text-slate-500">
              Keputusan yang dibanding: {recLabel(d.disputed_recommendation)} {rupiah(d.disputed_amount)}
              {d.original_reviewer ? ` · penelaah awal ${d.original_reviewer}` : ""}
            </p>
          )}
          {d.reviewed_at && (
            <p className="mt-1 text-xs text-slate-700">
              Telaah ulang{internal && d.reviewer ? ` ${d.reviewer}` : " dokter lain"} · {waktu(d.reviewed_at)}
              {internal && <> · rekomendasi baru {recLabel(d.new_recommendation)} {rupiah(d.new_amount)}</>}
              {d.review_outcome && <> · <b>{DISPUTE_OUTCOME_LABEL[d.review_outcome] ?? d.review_outcome}</b></>}
            </p>
          )}
          {d.review_notes && (internal || d.status === "RESOLVED") && (
            <p className="mt-1 text-xs italic text-slate-600">&ldquo;{d.review_notes}&rdquo;</p>
          )}
          {d.resolved_at && (
            <p className="mt-1 text-xs text-emerald-800">
              Diputus ulang{internal && d.resolved_by ? ` ${d.resolved_by}` : " asuransi"} · {waktu(d.resolved_at)}
              {d.outcome_label ? ` · keputusan awal ${d.outcome_label.toLowerCase()}` : ""}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

type Attachment = { file: File | null; docType: string };

/** Form banding untuk faskes / peserta. */
export function DisputeForm({ claimId, onDone }: { claimId: string; onDone: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState("CLINICAL");
  const [reason, setReason] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open)
    return <button className="btn-secondary" onClick={() => setOpen(true)}>Ajukan banding atas keputusan ini</button>;

  const setAt = (i: number, patch: Partial<Attachment>) =>
    setAttachments((a) => a.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const submit = async () => {
    setSaving(true);
    setError(null);
    const form = new FormData();
    form.append("category", category);
    form.append("reason", reason.trim());
    for (const a of attachments) {
      if (!a.file) continue;
      form.append("files", a.file);
      form.append("doc_types", a.docType);
    }
    try {
      await apiFetch(`/portal/claims/${claimId}/disputes`, { method: "POST", body: form });
      setOpen(false);
      onDone("Banding terkirim. Klaim akan ditelaah ulang oleh dokter yang berbeda dari penelaah awal.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <label className="block text-sm">
        <span className="font-medium">Yang dipersoalkan</span>
        <select className="input mt-1" value={category} onChange={(e) => setCategory(e.target.value)}>
          {DISPUTE_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </label>
      <label className="block text-sm">
        <span className="font-medium">Alasan banding</span>
        <textarea className="input mt-1 h-24" value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="Jelaskan mengapa keputusan perlu ditinjau ulang, misalnya temuan klinis yang belum dipertimbangkan." />
        <span className="text-xs text-slate-500">Minimal 10 karakter.</span>
      </label>
      <div className="space-y-2 text-sm">
        <span className="font-medium">Dokumen pendukung (opsional)</span>
        {attachments.map((a, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select className="input w-48" value={a.docType} onChange={(e) => setAt(i, { docType: e.target.value })}>
              {REQUESTABLE_DOC_TYPES.map((t) => <option key={t} value={t}>{DOC_TYPE_LABEL[t] ?? t}</option>)}
            </select>
            <input type="file" accept="application/pdf,image/jpeg,image/png" className="text-sm"
                   onChange={(e) => setAt(i, { file: e.target.files?.[0] ?? null })} />
            <button className="text-xs text-rose-700 hover:underline" onClick={() => setAttachments((x) => x.filter((_, j) => j !== i))}>
              Hapus
            </button>
          </div>
        ))}
        <button className="text-xs text-sky-800 hover:underline"
                onClick={() => setAttachments((x) => [...x, { file: null, docType: "resume_medis" }])}>
          + Tambah dokumen
        </button>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={saving || reason.trim().length < 10} onClick={submit}>
          {saving ? "Mengirim…" : "Kirim banding"}
        </button>
        <button className="btn-secondary" onClick={() => setOpen(false)}>Batal</button>
      </div>
    </div>
  );
}

/** Penarikan banding oleh pengaju, selama belum ditelaah ulang. */
export function WithdrawDisputeButton({ claimId, onDone }: { claimId: string; onDone: (message: string) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const go = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiJson(`/portal/claims/${claimId}/disputes/withdraw`, { method: "POST" });
      onDone("Banding ditarik. Keputusan awal kembali berlaku.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {confirm ? (
        <>
          <span>Tarik banding? Keputusan awal kembali berlaku.</span>
          <button className="btn-secondary" disabled={saving} onClick={go}>{saving ? "Menarik…" : "Ya, tarik"}</button>
          <button className="text-xs text-slate-600 hover:underline" onClick={() => setConfirm(false)}>Batal</button>
        </>
      ) : (
        <button className="text-xs text-rose-700 hover:underline" onClick={() => setConfirm(true)}>Tarik banding</button>
      )}
      {error && <span className="text-rose-700">{error}</span>}
    </div>
  );
}

/** Banner di ruang telaah dokter: konteks banding yang sedang ditelaah ulang. */
export function DisputeBanner({ dispute }: { dispute: DisputeInfo }) {
  return (
    <div className="card border-violet-300 bg-violet-50 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium text-violet-900">Telaah ulang banding · {dispute.category_label}</h2>
        <span className="text-xs text-violet-800">
          SLA {tanggal(dispute.due_at)}{dispute.overdue ? " (lewat)" : ""}
        </span>
      </div>
      <p className="mt-1 text-violet-900">
        Diajukan {filerLabel(dispute.raised_by_role).toLowerCase()} ({dispute.raised_by}) atas keputusan{" "}
        <b>{recLabel(dispute.disputed_recommendation)}</b> {rupiah(dispute.disputed_amount)}
        {dispute.original_reviewer ? `, ditandatangani ${dispute.original_reviewer}` : ""}.
      </p>
      <p className="mt-2 whitespace-pre-line rounded bg-white p-2 text-slate-800">{dispute.reason}</p>
      <p className="mt-2 text-xs text-violet-800">
        {dispute.document_ids.length > 0
          ? `${dispute.document_ids.length} dokumen pendukung baru ada di daftar dokumen. `
          : "Tidak ada dokumen baru. "}
        Anda ditugaskan karena berbeda dari penelaah awal. Tanda tangan Anda menentukan apakah keputusan awal
        dikuatkan, diubah, atau dibatalkan.
      </p>
    </div>
  );
}
