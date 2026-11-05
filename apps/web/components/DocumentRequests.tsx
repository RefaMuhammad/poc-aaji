"use client";

import { useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import type { DocumentRequest } from "@/lib/types";
import { DOC_TYPE_LABEL, REQUEST_STATUS_LABEL, tanggal, waktu } from "@/lib/format";
import { DocTypePicker } from "@/components/DecisionForm";

const label = (t: string) => DOC_TYPE_LABEL[t] ?? t;

const STATUS_STYLE: Record<string, string> = {
  OPEN: "bg-amber-50 text-amber-800",
  FULFILLED: "bg-emerald-50 text-emerald-800",
  CANCELLED: "bg-slate-100 text-slate-600",
};

/** Riwayat permintaan dokumen susulan satu klaim. */
export function DocumentRequestList({ requests }: { requests: DocumentRequest[] }) {
  if (requests.length === 0) return null;
  return (
    <ul className="space-y-3">
      {requests.map((r) => (
        <li key={r.id} className="rounded border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{r.doc_types.map(label).join(", ")}</span>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[r.status] ?? ""}`}>
              {REQUEST_STATUS_LABEL[r.status] ?? r.status}
            </span>
          </div>
          <p className="mt-1 text-slate-700">{r.message}</p>
          <p className="mt-1 text-xs text-slate-500">
            Diminta {r.requested_by} · {waktu(r.created_at)} · batas{" "}
            <span className={r.overdue ? "font-medium text-rose-700" : ""}>{tanggal(r.due_at)}{r.overdue ? " (lewat)" : ""}</span>
          </p>
          {r.status === "OPEN" && r.outstanding.length > 0 && r.outstanding.length < r.doc_types.length && (
            <p className="mt-1 text-xs text-amber-800">Masih kurang: {r.outstanding.map(label).join(", ")}</p>
          )}
          {r.fulfilled_at && (
            <p className="mt-1 text-xs text-emerald-800">
              Dipenuhi {r.fulfilled_by} · {waktu(r.fulfilled_at)}
              {r.response_note ? ` · "${r.response_note}"` : ""}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Unggah dokumen susulan: satu pilihan file per jenis dokumen yang masih kurang. */
export function LateUploadForm({ claimId, request, endpoint, withNote = true, onDone }: {
  claimId: string;
  request: DocumentRequest;
  endpoint: string;
  withNote?: boolean;
  onDone: (message: string) => void;
}) {
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = request.outstanding.filter((t) => files[t]);

  const submit = async () => {
    if (chosen.length === 0) return;
    setSaving(true);
    setError(null);
    const form = new FormData();
    for (const t of chosen) {
      form.append("files", files[t] as File);
      form.append("doc_types", t);
    }
    if (withNote && note.trim()) form.append("note", note.trim());
    try {
      const res = await apiFetch(endpoint, { method: "POST", body: form });
      const body = (await res.json()) as { job_id: string | null };
      setFiles({});
      onDone(body.job_id ? "Dokumen lengkap. Klaim diproses ulang lalu ditelaah dokter." : "Dokumen tersimpan. Masih ada dokumen yang kurang.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3" data-claim={claimId}>
      {request.outstanding.map((t) => (
        <label key={t} className="block text-sm">
          <span className="font-medium">{label(t)}</span>
          <input
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            className="mt-1 block w-full text-sm"
            onChange={(e) => setFiles((f) => ({ ...f, [t]: e.target.files?.[0] ?? null }))}
          />
        </label>
      ))}
      {withNote && (
        <label className="block text-sm">
          <span className="text-slate-600">Catatan untuk asuransi (opsional)</span>
          <textarea className="input mt-1 h-16" value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      )}
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <button className="btn-primary" disabled={saving || chosen.length === 0} onClick={submit}>
        {saving ? "Mengunggah…" : `Kirim ${chosen.length || ""} dokumen`}
      </button>
    </div>
  );
}

/** Asuransi menunda klaim dan meminta dokumen ke faskes tanpa mencatat keputusan. */
export function RequestDocumentsForm({ claimId, missing, onDone }: { claimId: string; missing: string[]; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [docTypes, setDocTypes] = useState<string[]>(missing);
  const [message, setMessage] = useState("");
  const [days, setDays] = useState(7);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open)
    return (
      <button className="btn-secondary" onClick={() => setOpen(true)}>Tunda & minta dokumen ke rumah sakit</button>
    );

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await apiJson(`/claims/${claimId}/document-requests`, {
        method: "POST",
        body: JSON.stringify({ doc_types: docTypes, message: message.trim() || null, due_days: days }),
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card space-y-3">
      <h3 className="font-medium">Minta dokumen susulan</h3>
      <DocTypePicker value={docTypes} onChange={setDocTypes} />
      <textarea className="input h-16 text-sm" placeholder="Pesan untuk rumah sakit (opsional)" value={message}
                onChange={(e) => setMessage(e.target.value)} />
      <label className="flex items-center gap-2 text-sm">
        Batas waktu
        <input type="number" min={1} max={30} className="input w-20" value={days} onChange={(e) => setDays(Number(e.target.value) || 7)} />
        hari
      </label>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button className="btn-primary" disabled={saving || docTypes.length === 0} onClick={submit}>
          {saving ? "Mengirim…" : "Kirim permintaan"}
        </button>
        <button className="btn-secondary" onClick={() => setOpen(false)}>Batal</button>
      </div>
    </div>
  );
}
