"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { IntegrationJob, Tenant, WebhookDelivery } from "@/lib/types";
import { CHANNEL_LABEL, DELIVERY_STATUS_LABEL, JOB_STATUS_LABEL, waktu } from "@/lib/format";

const STATUS_STYLE: Record<string, string> = {
  SUCCESS: "bg-emerald-50 text-emerald-800",
  DELIVERED: "bg-emerald-50 text-emerald-800",
  PARTIAL: "bg-amber-50 text-amber-900",
  PENDING: "bg-sky-50 text-sky-900",
  FAILED: "bg-rose-50 text-rose-800",
};

interface SinkEntry {
  received_at: string;
  event: string | null;
  delivery_id: string | null;
  signature_valid: boolean | null;
  payload: { claim?: { claim_number?: string; recommendation?: string | null; decision?: string | null } };
}

function jobSummary(j: IntegrationJob): string {
  const s = j.summary as Record<string, unknown>;
  if (typeof s.error === "string") return s.error;
  if (j.channel === "SFTP") return `${s.created ?? 0} klaim diterima, ${s.failed ?? 0} ditolak`;
  if (j.channel === "FRAUD_HISTORY") return `${s.created ?? 0} baru, ${s.updated ?? 0} diperbarui, ${s.error_count ?? 0} baris salah`;
  if (j.channel.startsWith("POLICY")) return `${s.created ?? 0} baru, ${s.updated ?? 0} diperbarui, ${s.error_count ?? 0} baris salah`;
  if (typeof s.claim_number === "string") return `Klaim ${s.claim_number} · ${s.documents ?? 0} dokumen`;
  return "";
}

/** Riwayat data masuk (API, FHIR, SFTP, impor polis) dan webhook keluar satu tenant. */
export function IntegrationLog({ tenant, canResend = false }: { tenant: Pick<Tenant, "insurer_id" | "code">; canResend?: boolean }) {
  const [jobs, setJobs] = useState<IntegrationJob[] | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[] | null>(null);
  const [sink, setSink] = useState<SinkEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    apiJson<IntegrationJob[]>(`/tenants/${tenant.insurer_id}/integration-jobs?limit=30`).then(setJobs).catch((e) => setError(e.message));
    apiJson<WebhookDelivery[]>(`/tenants/${tenant.insurer_id}/webhook-deliveries?limit=30`).then(setDeliveries).catch((e) => setError(e.message));
    apiJson<SinkEntry[]>(`/integrations/demo-sink?limit=50`)
      .then((rows) => setSink(rows.filter((r) => (r as unknown as { insurer_id?: string }).insurer_id === tenant.insurer_id).slice(0, 10)))
      .catch(() => setSink([]));
  }, [tenant.insurer_id]);
  useEffect(load, [load]);

  const resend = async (d: WebhookDelivery) => {
    try {
      await apiJson(`/tenants/${tenant.insurer_id}/webhook-deliveries/${d.id}/resend`, { method: "POST" });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="card space-y-4">
      <div className="flex items-baseline justify-between gap-2">
        <div>
          <h2 className="font-semibold">Riwayat integrasi</h2>
          <p className="text-xs text-slate-500">Data masuk lewat API, FHIR, SFTP, dan impor polis; webhook yang dikirim ke sistem asuransi.</p>
        </div>
        <button type="button" className="btn-secondary py-1 text-xs" onClick={load}>Muat ulang</button>
      </div>
      {error && <p className="text-sm text-rose-700">{error}</p>}

      <div>
        <h3 className="mb-1 text-sm font-medium">Data masuk</h3>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="py-1 pr-2">Waktu</th><th className="py-1 pr-2">Kanal</th><th className="py-1 pr-2">Referensi</th><th className="py-1 pr-2">Status</th><th className="py-1">Ringkasan</th></tr>
          </thead>
          <tbody>
            {jobs?.length === 0 && <tr><td colSpan={5} className="py-2 text-slate-500">Belum ada data masuk lewat integrasi.</td></tr>}
            {jobs?.map((j) => (
              <tr key={j.id} className="border-t align-top">
                <td className="py-1.5 pr-2 text-xs">{waktu(j.created_at)}</td>
                <td className="py-1.5 pr-2 text-xs">{CHANNEL_LABEL[j.channel] ?? j.channel}</td>
                <td className="py-1.5 pr-2 font-mono text-xs">{j.reference ?? "-"}</td>
                <td className="py-1.5 pr-2"><span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLE[j.status] ?? ""}`}>{JOB_STATUS_LABEL[j.status] ?? j.status}</span></td>
                <td className="py-1.5 text-xs text-slate-600">{jobSummary(j)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-medium">Webhook keluar</h3>
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr><th className="py-1 pr-2">Waktu</th><th className="py-1 pr-2">Peristiwa</th><th className="py-1 pr-2">Klaim</th><th className="py-1 pr-2">Status</th><th className="py-1 pr-2">Percobaan</th><th className="py-1" /></tr>
          </thead>
          <tbody>
            {deliveries?.length === 0 && (
              <tr><td colSpan={6} className="py-2 text-slate-500">Belum ada webhook. Isi URL webhook di pengaturan tenant.</td></tr>
            )}
            {deliveries?.map((d) => {
              const claim = (d.payload as { claim?: { claim_number?: string } }).claim;
              return (
                <tr key={d.id} className="border-t align-top">
                  <td className="py-1.5 pr-2 text-xs">{waktu(d.created_at)}</td>
                  <td className="py-1.5 pr-2 font-mono text-xs">{d.event}</td>
                  <td className="py-1.5 pr-2 text-xs">
                    {d.claim_id ? <Link className="text-sky-800 hover:underline" href={`/klaim/${d.claim_id}`}>{claim?.claim_number ?? "buka"}</Link> : "-"}
                  </td>
                  <td className="py-1.5 pr-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLE[d.status] ?? ""}`} title={d.last_error ?? undefined}>
                      {DELIVERY_STATUS_LABEL[d.status] ?? d.status}
                      {d.last_status_code ? ` · HTTP ${d.last_status_code}` : ""}
                    </span>
                    {d.last_error && d.status !== "DELIVERED" && <div className="mt-0.5 max-w-xs truncate text-xs text-rose-700">{d.last_error}</div>}
                  </td>
                  <td className="py-1.5 pr-2 text-xs">{d.attempts}</td>
                  <td className="py-1.5 text-right">
                    {canResend && d.status !== "PENDING" && (
                      <button type="button" className="text-xs text-sky-800 hover:underline" onClick={() => resend(d)}>Kirim ulang</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {sink.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-medium">Diterima penerima demo (sistem inti rekaan)</h3>
          <ul className="space-y-1 text-xs">
            {sink.map((s, i) => (
              <li key={i} className="rounded border bg-slate-50 px-2 py-1">
                {waktu(s.received_at)} · <code>{s.event}</code> · klaim {s.payload?.claim?.claim_number ?? "-"}
                {s.payload?.claim?.recommendation ? ` · ${s.payload.claim.recommendation}` : ""}
                {s.payload?.claim?.decision ? ` · keputusan ${s.payload.claim.decision}` : ""} · tanda tangan{" "}
                {s.signature_valid === true ? "cocok" : s.signature_valid === false ? "TIDAK cocok" : "tidak diperiksa"}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
