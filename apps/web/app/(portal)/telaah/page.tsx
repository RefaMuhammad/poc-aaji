"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { QueueItem } from "@/lib/types";
import { LEVEL_LABEL, rupiah, waktu } from "@/lib/format";
import { TriageBadge } from "@/components/Badges";

const DX_FILTERS = [
  { value: "", label: "Semua diagnosis" },
  { value: "A9", label: "Dengue (A90, A91)" },
  { value: "A01", label: "Demam tifoid (A01.0)" },
  { value: "A09", label: "GEA (A09)" },
];

export default function QueuePage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<"queue" | "done">("queue");
  const [icd, setIcd] = useState("");
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams();
    if (icd) params.set("icd", icd);
    if (tab === "done") params.set("done", "true");
    try {
      setItems(await apiJson<QueueItem[]>(`/review/queue?${params}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [icd, tab]);

  useEffect(() => {
    setItems(null);
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Antrean telaah</h1>
          <p className="text-sm text-slate-500">
            {user?.role === "doctor_gp"
              ? "Kasus kuning untuk dokter umum. Kasus bisa dieskalasi ke spesialis."
              : `Kasus merah dan hasil eskalasi${user?.specialty ? ` untuk spesialis ${user.specialty}` : ""}.`}{" "}
            Urut dari skor risiko tertinggi.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="flex rounded-md border border-slate-300 bg-white p-0.5 text-sm">
            {(["queue", "done"] as const).map((t) => (
              <button
                key={t}
                className={`rounded px-3 py-1 ${tab === t ? "bg-slate-800 text-white" : "text-slate-600"}`}
                onClick={() => setTab(t)}
              >
                {t === "queue" ? "Menunggu" : "Sudah saya tanda tangani"}
              </button>
            ))}
          </div>
          <select className="input w-auto py-1" value={icd} onChange={(e) => setIcd(e.target.value)} aria-label="Filter diagnosis">
            {DX_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="border-b bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2">Nomor klaim</th>
              <th className="px-3 py-2">Diagnosis</th>
              <th className="px-3 py-2">Triase</th>
              <th className="px-3 py-2 text-right">Temuan</th>
              <th className="px-3 py-2">Penelaah</th>
              <th className="px-3 py-2 text-right">Tagihan</th>
              <th className="px-3 py-2">{tab === "queue" ? "Menunggu sejak" : "Ditandatangani"}</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {items === null && <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-500">Memuat…</td></tr>}
            {items?.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-500">{tab === "queue" ? "Tidak ada kasus menunggu." : "Belum ada."}</td></tr>
            )}
            {items?.map((i) => (
              <tr key={i.id} className="border-b last:border-0 hover:bg-slate-50">
                <td className="px-3 py-2">
                  <Link href={`/telaah/${i.id}`} className="font-medium text-sky-800 hover:underline">{i.claim_number}</Link>
                  <div className="text-xs text-slate-500">{i.hospital_name}</div>
                </td>
                <td className="px-3 py-2">
                  <span className="font-mono text-xs">{i.primary_icd10 ?? "-"}</span>{" "}
                  <span className="text-slate-600">{i.diagnosis_name ?? ""}</span>
                </td>
                <td className="px-3 py-2"><TriageBadge triage={i.triage_status} score={i.risk_score} /></td>
                <td className="px-3 py-2 text-right tabular-nums">{i.findings}</td>
                <td className="px-3 py-2">
                  {LEVEL_LABEL[i.level]}
                  {i.level === "SPECIALIST" && i.specialty ? ` · ${i.specialty}` : ""}
                  {i.escalated && <span className="ml-1 rounded bg-violet-100 px-1.5 py-0.5 text-xs text-violet-800">eskalasi</span>}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{rupiah(i.billed_amount)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                  {tab === "queue" ? waktu(i.waiting_since) : waktu(i.signed_at)}
                </td>
                <td className="px-3 py-2 text-right">
                  {tab === "queue" && i.assigned_to_me && <span className="rounded bg-sky-100 px-2 py-0.5 text-xs text-sky-800">sedang Anda telaah</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
