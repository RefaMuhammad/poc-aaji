"use client";

import { useState } from "react";
import { apiJson } from "@/lib/api";
import type { Recommendation } from "@/lib/types";
import { waktu } from "@/lib/format";

export function DecisionForm({ rec, onSaved }: { rec: Recommendation; onSaved: (r: Recommendation) => void }) {
  const [decision, setDecision] = useState<"AGREE" | "DIFFER" | null>(null);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (rec.insurer_decision) {
    const d = rec.insurer_decision;
    return (
      <div className="card">
        <h3 className="font-medium">Keputusan asuransi</h3>
        <p className="mt-1 text-sm">
          <b>{d.decision === "AGREE" ? "Setuju dengan rekomendasi" : "Berbeda dengan rekomendasi"}</b> · {d.decided_by} ·{" "}
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
        body: JSON.stringify({ decision, reason: reason.trim() || null }),
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
          Setuju dengan rekomendasi
        </button>
        <button className={decision === "DIFFER" ? "btn-primary" : "btn-secondary"} onClick={() => setDecision("DIFFER")}>
          Berbeda
        </button>
      </div>
      {decision && (
        <div className="mt-3">
          <label className="text-sm text-slate-600" htmlFor="reason">
            Alasan {decision === "DIFFER" ? <span className="text-rose-600">(wajib)</span> : "(opsional)"}
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
