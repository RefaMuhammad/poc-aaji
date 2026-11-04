"use client";

import { useState } from "react";
import { apiJson } from "@/lib/api";
import type { FieldHistory, ReviewField } from "@/lib/types";
import { nilai, waktu } from "@/lib/format";
import type { ViewerTarget } from "./DocumentViewer";

const STATUS_LABEL: Record<string, string> = {
  verified: "terverifikasi",
  absent: "tidak ada di dokumen",
  unverified: "bukti tidak cocok",
  unknown: "tidak diketahui",
};

function toInput(v: unknown, kind: string | null): string {
  if (v === null || v === undefined) return "";
  if (kind === "ya_tidak") return v ? "true" : "false";
  if (Array.isArray(v)) return v.every((x) => typeof x !== "object") ? v.join(", ") : JSON.stringify(v);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function parseInput(text: string, kind: string | null): unknown {
  const t = text.trim();
  if (t === "") return null;
  if (kind === "angka") {
    const n = Number(t.replace(/\./g, "").replace(",", "."));
    if (Number.isNaN(n)) throw new Error("Isi dengan angka");
    return n;
  }
  if (kind === "ya_tidak") return t === "true";
  if (kind === "daftar") {
    if (t.startsWith("[")) return JSON.parse(t);
    return t.split(",").map((x) => x.trim()).filter(Boolean);
  }
  return t;
}

function EditRow({ field, claimId, onSaved, onCancel }: { field: ReviewField; claimId: string; onSaved: () => void; onCancel: () => void }) {
  const current = field.corrected ? field.corrected_value : field.value;
  const [text, setText] = useState(toInput(current, field.kind));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const value = parseInput(text, field.kind);
      await apiJson(`/review/${claimId}/fields/${field.id}`, { method: "PATCH", body: JSON.stringify({ value, note: note || null }) });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 space-y-2 rounded border border-sky-200 bg-sky-50 p-2">
      {field.kind === "ya_tidak" ? (
        <select className="input py-1" value={text} onChange={(e) => setText(e.target.value)}>
          <option value="">tidak diketahui</option>
          <option value="true">ya</option>
          <option value="false">tidak</option>
        </select>
      ) : (
        <input
          className="input py-1"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={field.kind === "daftar" ? "pisahkan dengan koma; kosong = tidak diketahui" : "kosong = tidak diketahui"}
        />
      )}
      <input className="input py-1" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Catatan koreksi (opsional)" />
      {error && <p className="text-xs text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button className="btn-primary py-1" disabled={busy} onClick={save}>Simpan koreksi</button>
        <button className="btn-secondary py-1" onClick={onCancel}>Batal</button>
      </div>
    </div>
  );
}

export function ExtractedFields({
  fields,
  history,
  claimId,
  editable,
  onChanged,
  onOpenEvidence,
}: {
  fields: ReviewField[];
  history: FieldHistory[];
  claimId: string;
  editable: boolean;
  onChanged: () => void;
  onOpenEvidence: (t: ViewerTarget) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  // Field dengan nilai/bukti/koreksi lebih dulu; field kosong disembunyikan sampai diminta.
  const meaningful = (f: ReviewField) => f.corrected || f.evidence.length > 0 || (f.value !== null && f.value !== false && !(Array.isArray(f.value) && f.value.length === 0) && f.value !== 0);
  const shown = showAll ? fields : fields.filter(meaningful);

  return (
    <div className="space-y-3">
      <ul className="divide-y rounded-lg border bg-white">
        {shown.map((f) => {
          const ev = f.evidence[0];
          return (
            <li key={f.id} className="px-3 py-2 text-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium">{f.label ?? f.field_path}</div>
                  <div className="font-mono text-[11px] text-slate-400">
                    {f.field_path} · {f.source}
                    {f.status ? ` · ${STATUS_LABEL[f.status] ?? f.status}` : ""}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  {f.corrected ? (
                    <>
                      <div className="font-medium text-sky-800">{nilai(f.corrected_value)}</div>
                      <div className="text-xs text-slate-400 line-through">{nilai(f.value)}</div>
                    </>
                  ) : (
                    <div className={f.value === null ? "text-slate-400" : ""}>{nilai(f.value)}</div>
                  )}
                </div>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                {ev?.doc && (
                  <button
                    className="max-w-full truncate text-left text-amber-800 hover:underline"
                    onClick={() => onOpenEvidence({ documentId: ev.doc!, page: ev.page ?? 1, bbox: ev.bbox, quote: ev.quote })}
                  >
                    “{ev.quote}”
                  </button>
                )}
                {f.corrected && <span className="text-slate-500">dikoreksi {f.corrected_by} · {waktu(f.corrected_at)}</span>}
                {editable && editing !== f.id && (
                  <button className="text-sky-800 hover:underline" onClick={() => setEditing(f.id)}>Koreksi</button>
                )}
              </div>
              {editing === f.id && (
                <EditRow
                  field={f}
                  claimId={claimId}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    onChanged();
                  }}
                />
              )}
            </li>
          );
        })}
      </ul>
      {fields.length > shown.length || showAll ? (
        <button className="text-xs text-sky-800 hover:underline" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Sembunyikan field kosong" : `Tampilkan ${fields.length - shown.length} field kosong / tidak ditemukan`}
        </button>
      ) : null}
      {history.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">Riwayat koreksi</h4>
          <ul className="space-y-1 text-xs text-slate-600">
            {history.map((h, i) => (
              <li key={i}>
                {waktu(h.at)} · {h.by}: <span className="font-mono">{h.field_path}</span> {nilai(h.old)} → <b>{nilai(h.new)}</b>
                {h.note ? ` (${h.note})` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
