"use client";

import { useState } from "react";
import { apiJson } from "@/lib/api";
import type { Recommendation } from "@/lib/types";
import { DOC_TYPE_LABEL, REQUESTABLE_DOC_TYPES, waktu } from "@/lib/format";

/** Pilihan jenis dokumen yang diminta ke faskes (U4). */
export function DocTypePicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {REQUESTABLE_DOC_TYPES.map((t) => (
        <label key={t} className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={value.includes(t)}
                 onChange={(e) => onChange(e.target.checked ? [...value, t] : value.filter((x) => x !== t))} />
          {DOC_TYPE_LABEL[t] ?? t}
        </label>
      ))}
    </div>
  );
}

export function DecisionForm({ rec, missing = [], onSaved }: { rec: Recommendation; missing?: string[]; onSaved: (r: Recommendation) => void }) {
  const [decision, setDecision] = useState<"AGREE" | "DIFFER" | null>(null);
  const [reason, setReason] = useState("");
  const [docTypes, setDocTypes] = useState<string[]>(missing);
  const isPend = rec.recommendation === "PEND";
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (rec.insurer_decision) {
    const d = rec.insurer_decision;
    return (
      <div className="card">
        <h3 className="font-medium">Keputusan asuransi</h3>
        <p className="mt-1 text-sm">
          <b>{d.decision === "AGREE" ? (isPend ? "Setuju menunda, dokumen diminta ke rumah sakit" : "Setuju dengan rekomendasi") : "Berbeda dengan rekomendasi"}</b> · {d.decided_by} ·{" "}
          {waktu(d.decided_at)}
        </p>
        {d.reason && <p className="mt-1 text-sm text-slate-600">Alasan: {d.reason}</p>}
      </div>
    );
  }

  const submit = async () => {
    if (!decision) return;
    if (decision === "DIFFER" && !reason.trim()) {
      setError("Alasan wajib diisi bila keputusan berbeda dengan rekomendasi");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const r = await apiJson<Recommendation>(`/claims/${rec.claim_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason: reason.trim() || null, ...(decision === "AGREE" && isPend ? { doc_types: docTypes } : {}) }),
      });
      onSaved(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <h3 className="font-medium">Catat keputusan perusahaan</h3>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={decision === "AGREE" ? "btn-primary" : "btn-secondary"} onClick={() => setDecision("AGREE")}>
          {isPend ? "Setuju menunda & minta dokumen" : "Setuju dengan rekomendasi"}
        </button>
        <button className={decision === "DIFFER" ? "btn-primary" : "btn-secondary"} onClick={() => setDecision("DIFFER")}>
          Berbeda
        </button>
      </div>
      {decision === "AGREE" && isPend && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3">
          <p className="mb-2 text-sm text-amber-900">
            Klaim akan berstatus <b>menunggu dokumen susulan</b>. Rumah sakit dan peserta mendapat notifikasi; setelah dokumen
            lengkap klaim diproses ulang dan ditelaah dokter lagi.
          </p>
          <DocTypePicker value={docTypes} onChange={setDocTypes} />
          <p className="mt-2 text-xs text-amber-800">Kosongkan bila penundaan tidak membutuhkan dokumen; keputusan dicatat dan klaim selesai.</p>
        </div>
      )}
      {decision && (
        <div className="mt-3">
          <label className="text-sm text-slate-600" htmlFor="reason">
            {decision === "AGREE" && isPend ? "Pesan untuk rumah sakit (opsional)" : "Alasan"}{" "}
            {decision === "DIFFER" ? <span className="text-rose-600">(wajib)</span> : decision === "AGREE" && isPend ? "" : "(opsional)"}
          </label>
          <textarea
            id="reason"
            className="input mt-1 h-24"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={decision === "DIFFER" ? "Mengapa keputusan perusahaan berbeda?" : ""}
          />
          {error && <p className="mt-1 text-sm text-rose-700">{error}</p>}
          <button className="btn-primary mt-2" disabled={saving} onClick={submit}>
            {saving ? "Menyimpan…" : "Simpan keputusan"}
          </button>
        </div>
      )}
    </div>
  );
}
