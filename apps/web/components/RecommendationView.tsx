"use client";

import { useState } from "react";
import type { DocumentInfo, Recommendation } from "@/lib/types";
import { REASON_LABEL, RECOMMENDATION_LABEL, rupiah, tanggal, waktu } from "@/lib/format";
import { TriageBadge } from "./Badges";
import { FindingCard } from "./FindingCard";
import { DocumentViewer, type ViewerTarget } from "./DocumentViewer";

/** Rekomendasi per klaim sesuai spesifikasi output PRD. */
export function RecommendationView({ rec, documents }: { rec: Recommendation; documents: DocumentInfo[] }) {
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const correction = rec.recommended_amount !== null ? rec.billed_amount - rec.recommended_amount : 0;

  return (
    <section className="space-y-5">
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">Rekomendasi</div>
            <div className="mt-1 text-xl font-semibold">{RECOMMENDATION_LABEL[rec.recommendation] ?? rec.recommendation}</div>
            <div className="mt-2 flex items-center gap-2">
              <TriageBadge triage={rec.triage_status} />
              <span className="text-sm text-slate-500">Skor risiko {rec.risk_score}/100</span>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            <dt className="text-slate-500">Nilai tagihan</dt>
            <dd className="text-right tabular-nums">{rupiah(rec.billed_amount)}</dd>
            <dt className="text-slate-500">Direkomendasikan</dt>
            <dd className="text-right font-semibold tabular-nums">{rupiah(rec.recommended_amount)}</dd>
            {correction > 0 && (
              <>
                <dt className="text-slate-500">Koreksi</dt>
                <dd className="text-right tabular-nums text-rose-700">−{rupiah(correction)}</dd>
              </>
            )}
          </dl>
        </div>

        {rec.next_action && (
          <div className="mt-4 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm">
            <span className="font-medium">Tindak lanjut:</span> {rec.next_action}
          </div>
        )}

        <div className="mt-4 border-t pt-3 text-sm">
          {rec.reviewer ? (
            <span>
              Ditandatangani <b>{rec.reviewer.name}</b>
              {rec.reviewer.specialty ? ` (${rec.reviewer.specialty})` : ""} pada {waktu(rec.reviewer.signed_at)}
            </span>
          ) : rec.recommendation === "PAY_FULL" ? (
            <span className="text-slate-600">Klaim hijau: bayar penuh tanpa tanda tangan dokter.</span>
          ) : (
            <span className="text-violet-700">Draf, belum ditandatangani dokter.</span>
          )}
        </div>
      </div>

      {rec.quality_flags.length > 0 && (
        <div className="card border-amber-200 bg-amber-50">
          <div className="text-sm font-medium text-amber-900">Catatan kualitas data</div>
          <ul className="mt-1 list-disc pl-5 text-sm text-amber-900">
            {rec.quality_flags.map((q) => (
              <li key={q.code}>{q.message}</li>
            ))}
          </ul>
        </div>
      )}

      {rec.line_adjustments.length > 0 && (
        <div className="card overflow-x-auto">
          <h3 className="mb-2 font-medium">Koreksi item tagihan</h3>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1 pr-3">Item</th>
                <th className="py-1 pr-3">Tanggal</th>
                <th className="py-1 pr-3 text-right">Jml</th>
                <th className="py-1 pr-3 text-right">Dikoreksi</th>
                <th className="py-1">Alasan</th>
              </tr>
            </thead>
            <tbody>
              {rec.line_adjustments.map((a, i) => (
                <tr key={i} className="border-t align-top">
                  <td className="py-1.5 pr-3">{a.item}</td>
                  <td className="py-1.5 pr-3 whitespace-nowrap">{a.date ? tanggal(a.date) : "-"}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{a.qty}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-rose-700">−{rupiah(a.amount)}</td>
                  <td className="py-1.5">
                    <div>{REASON_LABEL[a.reason_code] ?? a.reason_code}</div>
                    {a.note && <div className="text-xs text-slate-500">{a.note}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div>
        <h3 className="mb-2 font-medium">Temuan ({rec.findings.length})</h3>
        {rec.findings.length === 0 ? (
          <div className="card text-sm text-slate-500">Tidak ada temuan.</div>
        ) : (
          <div className="space-y-3">
            {rec.findings.map((f, i) => (
              <FindingCard key={i} finding={f} documents={documents} onOpenEvidence={setViewer} />
            ))}
          </div>
        )}
      </div>

      {rec.explanation_text && (
        <div className="card">
          <h3 className="mb-1 font-medium">Draf penjelasan untuk nasabah / RS</h3>
          <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">{rec.explanation_text}</p>
        </div>
      )}

      {rec.guideline_refs.length > 0 && (
        <div className="text-sm text-slate-600">
          <span className="font-medium">Rujukan:</span> {rec.guideline_refs.join("; ")}
        </div>
      )}

      <div className="text-xs text-slate-400">
        Versi model {rec.model_version} · prompt {rec.prompt_version} · aturan {rec.ruleset_version}
      </div>

      {viewer && <DocumentViewer target={viewer} documents={documents} onClose={() => setViewer(null)} />}
    </section>
  );
}
