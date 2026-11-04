"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Workspace } from "@/lib/types";
import { LEVEL_LABEL, REASON_LABEL, REVIEW_ACTION_LABEL, durasi, rupiah, tanggal, waktu } from "@/lib/format";
import { StatusBadge, TriageBadge } from "@/components/Badges";
import { DocumentPane, type ViewerTarget } from "@/components/DocumentViewer";
import { RecommendationView } from "@/components/RecommendationView";
import { FindingCard } from "@/components/FindingCard";
import { ExtractedFields } from "@/components/ExtractedFields";
import { ReviewActions } from "@/components/ReviewActions";

type Tab = "findings" | "fields" | "history";

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);
  return <>{durasi(Math.max(0, Math.round((now - new Date(since).getTime()) / 1000)))}</>;
}

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const router = useRouter();
  const [ws, setWs] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<ViewerTarget | null>(null);
  const [tab, setTab] = useState<Tab>("findings");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setWs(await apiJson<Workspace>(`/review/${id}`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const start = async () => {
    setBusy(true);
    try {
      await apiJson(`/review/${id}/start`, { method: "POST" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error && !ws) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!ws) return <div className="text-sm text-slate-500">Memuat…</div>;

  const { claim, draft } = ws;
  const reviewing = !!ws.my_review && draft?.state === "DRAFT";
  const signed = draft?.state === "SIGNED";
  const tabs: { key: Tab; label: string }[] = [
    { key: "findings", label: `Temuan & draf (${draft?.findings.length ?? 0})` },
    { key: "fields", label: `Data ekstraksi (${ws.fields.length})` },
    { key: "history", label: `Riwayat telaah (${ws.reviews.length})` },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link href="/telaah" className="text-sm text-sky-800 hover:underline">‹ Antrean telaah</Link>
          <h1 className="text-lg font-semibold">
            Klaim {claim.claim_number}{" "}
            <span className="font-normal text-slate-500">
              · <span className="font-mono text-sm">{claim.primary_icd10 ?? "-"}</span> {ws.diagnosis_name ?? ""}
            </span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <TriageBadge triage={draft?.triage_status ?? null} score={draft?.risk_score} />
          <span className="text-slate-600">
            {LEVEL_LABEL[ws.level]}
            {ws.level === "SPECIALIST" && ws.specialty ? ` · ${ws.specialty}` : ""}
          </span>
          {ws.escalated && <span className="rounded bg-violet-100 px-1.5 py-0.5 text-xs text-violet-800">hasil eskalasi</span>}
          <StatusBadge status={claim.status} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* Panel kiri: dokumen asli */}
        <DocumentPane
          target={target}
          documents={claim.documents}
          onSelect={setTarget}
          className="h-[60vh] rounded-lg border lg:sticky lg:top-4 lg:h-[calc(100vh-7rem)]"
        />

        {/* Panel kanan: data, temuan, draf, aksi */}
        <div className="min-w-0 space-y-4">
          <div className="card grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <div><span className="text-slate-500">RS</span><div>{claim.hospital_name}</div></div>
            <div><span className="text-slate-500">Rawat inap</span><div>{tanggal(claim.admission_date)} – {tanggal(claim.discharge_date)}</div></div>
            <div><span className="text-slate-500">Tagihan</span><div>{rupiah(claim.billed_amount)}</div></div>
            {claim.missing_documents.length > 0 && (
              <div className="col-span-full text-amber-800">Dokumen belum ada: {claim.missing_documents.join(", ")}</div>
            )}
          </div>

          {notice && <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</div>}
          {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

          {reviewing ? (
            <div className="rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
              Anda menelaah kasus ini sejak {waktu(ws.my_review!.started_at)} (<Elapsed since={ws.my_review!.started_at} />).
            </div>
          ) : signed ? (
            <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              Rekomendasi sudah ditandatangani {draft?.reviewer?.name} pada {waktu(draft?.reviewer?.signed_at)} dan terlihat di portal asuransi.
            </div>
          ) : ws.can_start ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded border bg-white px-3 py-2 text-sm">
              <span>Ambil kasus ini untuk mulai menelaah. Waktu telaah mulai dihitung dan kasus terkunci untuk Anda.</span>
              <button className="btn-primary" disabled={busy} onClick={start}>Mulai telaah</button>
            </div>
          ) : (
            <div className="rounded border bg-slate-50 px-3 py-2 text-sm text-slate-600">
              {ws.blocked_reason ?? "Kasus tidak bisa ditelaah"}
              {ws.assigned_to ? ` (${ws.assigned_to})` : ""}.
            </div>
          )}

          <div className="flex gap-1 border-b text-sm">
            {tabs.map((t) => (
              <button
                key={t.key}
                className={`-mb-px border-b-2 px-3 py-1.5 ${tab === t.key ? "border-sky-700 font-medium text-sky-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {tab === "findings" && draft && (
            <div className="space-y-4">
              {draft.findings.length === 0 ? (
                <div className="card text-sm text-slate-500">Tidak ada temuan.</div>
              ) : (
                draft.findings.map((f, i) => <FindingCard key={i} finding={f} documents={claim.documents} onOpenEvidence={setTarget} />)
              )}
              <div>
                <h3 className="mb-2 font-medium">{signed ? "Rekomendasi final" : "Draf rekomendasi AI"}</h3>
                <RecommendationView rec={draft} documents={claim.documents} onOpenEvidence={setTarget} showFindings={false} />
              </div>
            </div>
          )}

          {tab === "fields" && (
            <ExtractedFields
              fields={ws.fields}
              history={ws.field_history}
              claimId={claim.id}
              editable={reviewing}
              onChanged={load}
              onOpenEvidence={setTarget}
            />
          )}

          {tab === "history" && (
            <ul className="space-y-2">
              {ws.reviews.length === 0 && <li className="card text-sm text-slate-500">Belum ada telaah.</li>}
              {ws.reviews.map((r) => (
                <li key={r.id} className="card text-sm">
                  <div className="font-medium">
                    {r.doctor}
                    {r.doctor_specialty ? ` (${r.doctor_specialty})` : ""} ·{" "}
                    {r.action ? REVIEW_ACTION_LABEL[r.action] ?? r.action : "sedang menelaah"}
                  </div>
                  <div className="text-xs text-slate-500">
                    Mulai {waktu(r.started_at)}
                    {r.finished_at ? ` · selesai ${waktu(r.finished_at)} · ${durasi(r.duration_seconds)}` : ""}
                    {r.agrees_with_ai !== null ? ` · ${r.agrees_with_ai ? "setuju dengan draf AI" : "mengubah draf AI"}` : ""}
                  </div>
                  {r.reason_code && <div className="mt-1">Alasan: {r.reason_code} · {REASON_LABEL[r.reason_code] ?? ""}</div>}
                  {r.escalated_specialty && <div className="mt-1">Diteruskan ke spesialis {r.escalated_specialty}</div>}
                  {r.notes && <div className="mt-1 whitespace-pre-line text-slate-700">{r.notes}</div>}
                </li>
              ))}
            </ul>
          )}

          {reviewing && ws.suggestion && (
            <ReviewActions
              ws={ws}
              isGp={user?.role === "doctor_gp"}
              onDone={async (kind) => {
                if (kind !== "signed") {
                  router.push("/telaah");
                  return;
                }
                setNotice(null);
                setTab("findings");
                await load();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
