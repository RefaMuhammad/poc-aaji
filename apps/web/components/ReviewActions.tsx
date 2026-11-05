"use client";

import { useMemo, useState } from "react";
import { apiFetch, apiJson } from "@/lib/api";
import type { FinalRecommendation, Workspace } from "@/lib/types";
import { RECOMMENDATION_LABEL, REASON_LABEL, rupiah } from "@/lib/format";

const FINAL_CODES: FinalRecommendation[] = ["PAY_FULL", "PAY_PARTIAL", "PEND", "NOT_COVERED"];

interface SignBody {
  recommendation: FinalRecommendation;
  recommended_amount: number | null;
  kept_adjustments: number[] | null;
  reason_code: string | null;
  notes: string | null;
  explanation_text: string | null;
}

export function PinDialog({ summary, onCancel, onConfirm }: { summary: string; onCancel: () => void; onConfirm: (pin: string) => Promise<void> }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onConfirm(pin);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4" onClick={onCancel}>
      <form className="card w-full max-w-sm space-y-3" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3 className="font-semibold">Tanda tangani rekomendasi</h3>
        <p className="text-sm text-slate-600">{summary}</p>
        <p className="text-xs text-slate-500">Dengan memasukkan PIN, Anda menyatakan telah menelaah kasus ini. Waktu tanda tangan dicatat.</p>
        <input
          type="password"
          inputMode="numeric"
          autoComplete="off"
          autoFocus
          className="input text-center text-lg tracking-[0.4em]"
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 12))}
          placeholder="PIN"
          aria-label="PIN tanda tangan"
        />
        {error && <p className="text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-secondary" onClick={onCancel}>Batal</button>
          <button type="submit" className="btn-primary" disabled={busy || pin.length < 4}>{busy ? "Menandatangani…" : "Tanda tangan"}</button>
        </div>
      </form>
    </div>
  );
}

export function ReviewActions({ ws, isGp, onDone }: { ws: Workspace; isGp: boolean; onDone: (kind: "signed" | "escalated" | "released") => void }) {
  const draft = ws.draft!;
  const suggestion = ws.suggestion!;
  const adjustments = draft.line_adjustments;
  const claimId = ws.claim.id;

  const [mode, setMode] = useState<"none" | "modify" | "escalate">("none");
  const [code, setCode] = useState<FinalRecommendation>(suggestion.recommendation);
  const [kept, setKept] = useState<number[]>(adjustments.map((_, i) => i));
  const [amountText, setAmountText] = useState<string>("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [explanation, setExplanation] = useState("");
  const [escNotes, setEscNotes] = useState("");
  const [pending, setPending] = useState<SignBody | null>(null);
  const [error, setError] = useState<string | null>(null);

  const autoAmount = useMemo(
    () => Math.max(draft.billed_amount - kept.reduce((s, i) => s + (adjustments[i]?.amount ?? 0), 0), 0),
    [kept, adjustments, draft.billed_amount],
  );
  const amount: number | null =
    code === "PAY_FULL" ? draft.billed_amount : code === "NOT_COVERED" ? 0 : code === "PEND" ? null : amountText ? Number(amountText.replace(/\D/g, "")) : autoAmount;
  const changed =
    code !== suggestion.recommendation ||
    amount !== suggestion.recommended_amount ||
    (code === "PAY_PARTIAL" && kept.length !== adjustments.length);
  // U5: membatalkan keputusan yang dibanding cukup dengan pertimbangan di catatan, tanpa kode alasan
  const overturn = !!ws.dispute && code === "PAY_FULL";

  const sign = async (pin: string) => {
    const r = await apiFetch(`/review/${claimId}/sign`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...pending, pin }),
    });
    await r.json();
    setPending(null);
    onDone("signed");
  };

  const approveDraft = () =>
    setPending({
      recommendation: suggestion.recommendation,
      recommended_amount: suggestion.recommended_amount,
      kept_adjustments: null,
      reason_code: null,
      notes: null,
      explanation_text: null,
    });

  const submitModify = () => {
    setError(null);
    if (changed && !reason) {
      if (!overturn) return setError("Pilih kode alasan perubahan");
      if (!notes.trim()) return setError("Tuliskan pertimbangan telaah ulang di catatan dokter");
    }
    if (code === "PAY_PARTIAL" && (amount === null || amount >= draft.billed_amount)) return setError("Nilai bayar sebagian harus lebih kecil dari tagihan");
    setPending({
      recommendation: code,
      recommended_amount: code === "PAY_PARTIAL" ? amount : null,
      kept_adjustments: code === "PAY_PARTIAL" ? kept : null,
      reason_code: reason || null,
      notes: notes || null,
      explanation_text: explanation || null,
    });
  };

  const escalate = async () => {
    setError(null);
    try {
      await apiJson(`/review/${claimId}/escalate`, { method: "POST", body: JSON.stringify({ notes: escNotes }) });
      onDone("escalated");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const release = async () => {
    setError(null);
    try {
      await apiFetch(`/review/${claimId}/release`, { method: "POST" });
      onDone("released");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card space-y-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-500">Usulan dari draf AI</div>
        <div className="mt-1 font-medium">
          {RECOMMENDATION_LABEL[suggestion.recommendation]}
          {suggestion.recommended_amount !== null && <span className="font-normal text-slate-600"> · {rupiah(suggestion.recommended_amount)}</span>}
        </div>
        <p className="mt-1 text-xs text-slate-500">AI tidak pernah menolak klaim. Rekomendasi final adalah keputusan Anda.</p>
      </div>

      {mode === "none" && (
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" onClick={approveDraft}>Setujui draf & tanda tangan</button>
          <button className="btn-secondary" onClick={() => setMode("modify")}>Ubah rekomendasi</button>
          {isGp && <button className="btn-secondary" onClick={() => setMode("escalate")}>Eskalasi ke spesialis</button>}
          <button className="btn-secondary text-slate-500" onClick={release}>Lepas kasus</button>
        </div>
      )}

      {mode === "modify" && (
        <div className="space-y-3">
          <fieldset>
            <legend className="text-sm text-slate-600">Rekomendasi final</legend>
            <div className="mt-1 grid grid-cols-2 gap-2">
              {FINAL_CODES.map((c) => (
                <label key={c} className={`flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-sm ${code === c ? "border-sky-600 bg-sky-50" : "border-slate-200"}`}>
                  <input type="radio" name="rec" checked={code === c} onChange={() => setCode(c)} />
                  {RECOMMENDATION_LABEL[c]}
                </label>
              ))}
            </div>
          </fieldset>

          {code === "PAY_PARTIAL" && (
            <div className="space-y-2">
              {adjustments.length > 0 && (
                <div>
                  <div className="text-sm text-slate-600">Koreksi item yang dipertahankan</div>
                  <ul className="mt-1 space-y-1">
                    {adjustments.map((a, i) => (
                      <li key={i}>
                        <label className="flex items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={kept.includes(i)}
                            onChange={() => setKept((k) => (k.includes(i) ? k.filter((x) => x !== i) : [...k, i].sort((x, y) => x - y)))}
                          />
                          <span>
                            {a.item} · −{rupiah(a.amount)}
                            <span className="block text-xs text-slate-500">{REASON_LABEL[a.reason_code] ?? a.reason_code}</span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <label className="block text-sm">
                <span className="text-slate-600">Nilai dibayar (Rp)</span>
                <input
                  className="input mt-1"
                  inputMode="numeric"
                  value={amountText}
                  onChange={(e) => setAmountText(e.target.value)}
                  placeholder={`${autoAmount.toLocaleString("id-ID")} (otomatis dari koreksi item)`}
                />
              </label>
            </div>
          )}

          <label className="block text-sm">
            <span className="text-slate-600">Kode alasan {changed && !overturn ? <span className="text-rose-600">(wajib karena berbeda dari draf)</span> : "(opsional)"}</span>
            <select className="input mt-1" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">— pilih —</option>
              {Object.entries(ws.reason_codes).map(([k, v]) => (
                <option key={k} value={k}>{k} · {REASON_LABEL[k] ?? v}</option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Penjelasan untuk nasabah / RS (opsional)</span>
            <textarea
              className="input mt-1 h-28"
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              placeholder="Kosongkan untuk memakai ringkasan temuan dari draf ditambah keputusan Anda."
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">
              {ws.dispute
                ? <>Pertimbangan telaah ulang {overturn && changed ? <span className="text-rose-600">(wajib)</span> : "(opsional)"}; dibaca pengaju setelah banding diputus</>
                : "Catatan internal dokter (opsional)"}
            </span>
            <textarea className="input mt-1 h-16" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          <div className="flex gap-2">
            <button className="btn-primary" onClick={submitModify}>Tanda tangan</button>
            <button className="btn-secondary" onClick={() => setMode("none")}>Batal</button>
          </div>
        </div>
      )}

      {mode === "escalate" && (
        <div className="space-y-2">
          <label className="block text-sm">
            <span className="text-slate-600">
              Catatan untuk spesialis{ws.specialty ? ` (${ws.specialty})` : ""} <span className="text-rose-600">(wajib)</span>
            </span>
            <textarea className="input mt-1 h-24" value={escNotes} onChange={(e) => setEscNotes(e.target.value)} placeholder="Apa yang perlu dinilai spesialis?" />
          </label>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={!escNotes.trim()} onClick={escalate}>Eskalasi</button>
            <button className="btn-secondary" onClick={() => setMode("none")}>Batal</button>
          </div>
        </div>
      )}

      {error && <p className="text-sm text-rose-700">{error}</p>}

      {pending && (
        <PinDialog
          summary={`${RECOMMENDATION_LABEL[pending.recommendation]}${
            pending.recommendation === "PAY_PARTIAL" && pending.recommended_amount !== null ? ` · ${rupiah(pending.recommended_amount)}` : ""
          }${pending.reason_code ? ` · alasan ${pending.reason_code}` : ""}`}
          onCancel={() => setPending(null)}
          onConfirm={sign}
        />
      )}
    </div>
  );
}
