"use client";

import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { ClaimStatus, CountItem, Dashboard } from "@/lib/types";
import { DISPUTE_OUTCOME_LABEL, REASON_LABEL, RECOMMENDATION_LABEL, STATUS_LABEL, desimal, durasi, rupiah } from "@/lib/format";

const TRIAGE_STYLE: Record<string, { label: string; bar: string }> = {
  GREEN: { label: "Hijau", bar: "bg-emerald-500" },
  YELLOW: { label: "Kuning", bar: "bg-amber-400" },
  RED: { label: "Merah", bar: "bg-rose-500" },
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function Bars({ items, label, color = "bg-sky-600" }: { items: CountItem[]; label: (i: CountItem) => string; color?: string }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  if (items.length === 0) return <p className="text-sm text-slate-500">Belum ada data.</p>;
  return (
    <ul className="space-y-2">
      {items.map((i) => (
        <li key={i.key} className="text-sm">
          <div className="flex justify-between gap-3">
            <span className="truncate">{label(i)}</span>
            <span className="tabular-nums text-slate-600">{i.count}</span>
          </div>
          <div className="mt-1 h-2 rounded bg-slate-100">
            <div className={`h-2 rounded ${color}`} style={{ width: `${(100 * i.count) / max}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function DashboardPage() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJson<Dashboard>("/dashboard").then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!d) return <div className="text-sm text-slate-500">Memuat…</div>;

  const triageTotal = d.by_triage.reduce((s, t) => s + t.count, 0);
  const decided = d.decisions.reduce((s, t) => s + t.count, 0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">Ringkasan pilot</h1>
        <p className="text-sm text-slate-500">
          {d.label}. Angka dihitung dari klaim yang terlihat oleh akun Anda; rekomendasi yang belum ditandatangani dokter dihitung sebagai “menunggu dokter”.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Klaim" value={String(d.total_claims)} hint={`${d.awaiting_doctor} menunggu dokter`} />
        <Stat label="Nilai koreksi" value={rupiah(d.correction_total)} hint={`dari tagihan ${rupiah(d.billed_total)}`} />
        <Stat label="Waktu proses rata-rata" value={durasi(d.avg_processing_seconds === null ? null : Math.round(d.avg_processing_seconds))} hint="unggah sampai rekomendasi awal" />
        <Stat
          label="Persetujuan dokter atas draf AI"
          value={d.doctor_agreement_pct === null ? "-" : `${d.doctor_agreement_pct}%`}
          hint={`${d.doctor_reviews} telaah · rata-rata ${durasi(d.avg_review_seconds === null ? null : Math.round(d.avg_review_seconds))}`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card">
          <h2 className="mb-3 font-medium">Status triase</h2>
          {triageTotal === 0 ? (
            <p className="text-sm text-slate-500">Belum ada rekomendasi.</p>
          ) : (
            <>
              <div className="flex h-4 overflow-hidden rounded">
                {d.by_triage.filter((t) => t.count).map((t) => (
                  <div key={t.key} className={TRIAGE_STYLE[t.key]?.bar} style={{ width: `${(100 * t.count) / triageTotal}%` }} title={`${TRIAGE_STYLE[t.key]?.label}: ${t.count}`} />
                ))}
              </div>
              <ul className="mt-3 space-y-1 text-sm">
                {d.by_triage.map((t) => (
                  <li key={t.key} className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${TRIAGE_STYLE[t.key]?.bar}`} />
                      {TRIAGE_STYLE[t.key]?.label}
                    </span>
                    <span className="tabular-nums">{t.count}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="card">
          <h2 className="mb-3 font-medium">Status klaim</h2>
          <Bars items={d.by_status} label={(i) => STATUS_LABEL[i.key as ClaimStatus] ?? i.key} color="bg-slate-500" />
        </div>
        <div className="card">
          <h2 className="mb-3 font-medium">Rekomendasi</h2>
          <Bars items={d.by_recommendation} label={(i) => RECOMMENDATION_LABEL[i.key] ?? i.key} color="bg-sky-600" />
          <p className="mt-3 text-xs text-slate-500">
            Keputusan asuransi: {decided} klaim
            {d.decisions.length > 0 && ` (${d.decisions.map((x) => `${x.key === "AGREE" ? "setuju" : "berbeda"} ${x.count}`).join(", ")})`}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-medium">Temuan terbanyak</h2>
          <Bars items={d.top_findings} label={(i) => `${REASON_LABEL[i.key] ?? i.label ?? i.key} (${i.key})`} color="bg-amber-500" />
        </div>
        <div className="card">
          <h2 className="mb-3 font-medium">Rumah sakit dengan temuan terbanyak</h2>
          <Bars items={d.top_hospitals} label={(i) => i.key} color="bg-rose-400" />
        </div>
      </div>

      {d.disputes && (
        <div className="card">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-medium">Banding (sengketa)</h2>
            <span className="text-xs text-slate-500">telaah ulang oleh dokter yang berbeda · SLA 14 hari</span>
          </div>
          {d.disputes.total === 0 ? (
            <p className="text-sm text-slate-500">Belum ada banding.</p>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><div className="text-xs text-slate-500">Terbuka</div><div className="text-xl font-semibold">{d.disputes.open}</div>
                  <div className="text-xs text-slate-500">{d.disputes.in_review} telaah ulang · {d.disputes.awaiting_decision} menunggu putusan</div></div>
                <div><div className="text-xs text-slate-500">Lewat SLA</div>
                  <div className={`text-xl font-semibold ${d.disputes.overdue ? "text-rose-700" : ""}`}>{d.disputes.overdue}</div></div>
                <div><div className="text-xs text-slate-500">Selesai</div><div className="text-xl font-semibold">{d.disputes.resolved}</div>
                  <div className="text-xs text-slate-500">{d.disputes.resolved_on_time} tepat waktu · {d.disputes.withdrawn} ditarik</div></div>
                <div><div className="text-xs text-slate-500">Keputusan berubah</div>
                  <div className="text-xl font-semibold">{d.disputes.overturn_rate === null ? "-" : `${desimal(d.disputes.overturn_rate)}%`}</div>
                  <div className="text-xs text-slate-500">
                    rata-rata {d.disputes.avg_resolution_days === null ? "-" : `${desimal(d.disputes.avg_resolution_days)} hari`}
                  </div></div>
              </div>
              <div>
                <h3 className="mb-2 text-sm text-slate-600">Hasil banding</h3>
                <Bars items={d.disputes.by_outcome} label={(i) => DISPUTE_OUTCOME_LABEL[i.key] ?? i.label ?? i.key} color="bg-violet-500" />
              </div>
              <div>
                <h3 className="mb-2 text-sm text-slate-600">Yang dipersoalkan</h3>
                <Bars items={d.disputes.by_category} label={(i) => i.label ?? i.key} color="bg-slate-500" />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
