"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { PinDialog } from "@/components/ReviewActions";
import { apiJson, blobUrl, downloadFile } from "@/lib/api";
import { rupiah, tanggal, waktu } from "@/lib/format";
import {
  UW_FIELD_LABEL, UW_KIND_LABEL, UW_REC_LABEL, UW_REC_STYLE, UW_STATUS_LABEL, uwValue,
  type UwAssessment, type UwDetail, type UwField, type UwRecommendation,
} from "@/lib/underwriting";

const GROUPS: { title: string; prefix: string[] }[] = [
  { title: "Calon peserta", prefix: ["applicant."] },
  { title: "Pemeriksaan fisik (MCU)", prefix: ["vital."] },
  { title: "Laboratorium", prefix: ["lab."] },
  { title: "Riwayat kesehatan (kuesioner)", prefix: ["history."] },
  { title: "Surat keterangan dokter", prefix: ["doctor."] },
];
const KIND_STYLE: Record<string, string> = {
  tolak: "bg-rose-100 text-rose-800",
  tunda: "bg-sky-100 text-sky-800",
  debit: "bg-amber-100 text-amber-900",
  debit_pengecualian: "bg-amber-100 text-amber-900",
  pengecualian: "bg-violet-100 text-violet-800",
  catatan: "bg-slate-100 text-slate-700",
};
const RECS: UwRecommendation[] = ["ACCEPT_STANDARD", "ACCEPT_CONDITIONAL", "POSTPONE", "DECLINE"];

function Quotes({ a, ids, docTypes }: { a: UwAssessment; ids: string[]; docTypes: Record<string, string> }) {
  const lines = ids.map((i) => a.evidence[i]).filter(Boolean);
  if (!lines.length) return null;
  return (
    <ul className="mt-1 space-y-0.5">
      {lines.map((l, i) => (
        <li key={i} className="rounded bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-700">
          <span className="font-sans text-slate-400">{docTypes[l.doc_type] ?? l.doc_type} hal. {l.page}: </span>{l.text}
        </li>
      ))}
    </ul>
  );
}

function SignPanel({ d, onDone }: { d: UwDetail; onDone: (x: UwDetail) => void }) {
  const a = d.assessment!;
  const [mode, setMode] = useState<"AGREE" | "MODIFY">("AGREE");
  const [rec, setRec] = useState<UwRecommendation>(a.recommendation);
  const [cls, setCls] = useState(a.risk_class);
  const [loading, setLoading] = useState(a.loading_pct);
  const [excl, setExcl] = useState(a.exclusions.map((e) => e.text).join("\n"));
  const [notes, setNotes] = useState("");
  const [pinOpen, setPinOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const subClasses = d.labels.classes.filter((c) => c.max_debit !== undefined);
  const summary = mode === "AGREE"
    ? `Setujui draf sistem: ${UW_REC_LABEL[a.recommendation]}, kelas ${a.risk_class}, loading ${a.loading_pct}%.`
    : `Ubah menjadi: ${UW_REC_LABEL[rec]}${rec === "ACCEPT_CONDITIONAL" ? `, kelas ${cls}, loading ${loading}%` : ""}.`;
  const sign = async (pin: string) => {
    const body = mode === "AGREE" ? { action: "AGREE", notes: notes || null, pin } : {
      action: "MODIFY", recommendation: rec, risk_class: cls, loading_pct: loading,
      exclusions: excl.split("\n").map((s) => s.trim()).filter(Boolean), notes, pin,
    };
    const res = await apiJson<UwDetail>(`/underwriting/applications/${d.id}/sign`, { method: "POST", body: JSON.stringify(body) });
    setPinOpen(false);
    onDone(res);
  };
  return (
    <div className="card space-y-3 border-violet-200">
      <h2 className="font-medium">Telaah dokter</h2>
      <p className="text-sm text-slate-600">Periksa temuan dan buktinya, lalu setujui atau ubah draf. Tanda tangan dengan PIN.</p>
      <div className="flex gap-4 text-sm">
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "AGREE"} onChange={() => setMode("AGREE")} /> Setujui draf sistem</label>
        <label className="flex items-center gap-1"><input type="radio" checked={mode === "MODIFY"} onChange={() => setMode("MODIFY")} /> Ubah rekomendasi</label>
      </div>
      {mode === "MODIFY" && (
        <div className="grid gap-2 sm:grid-cols-3">
          <label className="text-sm">Rekomendasi
            <select className="input mt-1" value={rec} onChange={(e) => setRec(e.target.value as UwRecommendation)}>
              {RECS.map((r) => <option key={r} value={r}>{UW_REC_LABEL[r]}</option>)}
            </select>
          </label>
          {rec === "ACCEPT_CONDITIONAL" && (
            <>
              <label className="text-sm">Kelas risiko
                <select className="input mt-1" value={cls} onChange={(e) => setCls(e.target.value)}>
                  {subClasses.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
                </select>
              </label>
              <label className="text-sm">Loading premi (%)
                <input type="number" min={0} max={300} step={25} className="input mt-1" value={loading}
                       onChange={(e) => setLoading(Number(e.target.value))} />
              </label>
              <label className="text-sm sm:col-span-3">Pengecualian (satu per baris)
                <textarea className="input mt-1" rows={2} value={excl} onChange={(e) => setExcl(e.target.value)} />
              </label>
            </>
          )}
        </div>
      )}
      <label className="block text-sm">Catatan dokter {mode === "MODIFY" || a.missing_docs.length || a.missing_fields.length ? "(wajib)" : "(opsional)"}
        <textarea className="input mt-1" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Pertimbangan medis, mis. syarat pemeriksaan ulang" />
      </label>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex justify-end">
        <button className="btn-primary" onClick={() => { setError(null); setPinOpen(true); }}>Tanda tangani…</button>
      </div>
      {pinOpen && <PinDialog summary={summary} onCancel={() => setPinOpen(false)} onConfirm={sign} />}
    </div>
  );
}

function DecisionPanel({ d, onDone }: { d: UwDetail; onDone: (x: UwDetail) => void }) {
  const [choice, setChoice] = useState<UwRecommendation>(d.allowed_decisions[d.allowed_decisions.length - 1]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await apiJson<UwDetail>(`/underwriting/applications/${d.id}/decision`, {
        method: "POST", body: JSON.stringify({ decision: choice, notes: notes || null }),
      }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const deviates = choice === "ACCEPT_STANDARD" && d.terms.recommendation !== "ACCEPT_STANDARD";
  return (
    <div className="card space-y-3 border-emerald-200">
      <h2 className="font-medium">Keputusan underwriter</h2>
      <p className="text-sm text-slate-600">
        Pilihan selain terima standar mengikuti rekomendasi yang ditandatangani dokter dan tidak bisa diubah di sini.
      </p>
      <div className="flex flex-wrap gap-4 text-sm">
        {d.allowed_decisions.map((r) => (
          <label key={r} className="flex items-center gap-1">
            <input type="radio" checked={choice === r} onChange={() => setChoice(r)} /> {UW_REC_LABEL[r]}
            {r !== "ACCEPT_STANDARD" && <span className="text-xs text-slate-500">(sesuai tanda tangan dokter)</span>}
          </label>
        ))}
      </div>
      <label className="block text-sm">Catatan {deviates ? "(wajib: berbeda dari rekomendasi dokter)" : "(opsional)"}
        <textarea className="input mt-1" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <div className="flex justify-end"><button className="btn-primary" disabled={busy} onClick={submit}>{busy ? "Menyimpan…" : "Simpan keputusan"}</button></div>
    </div>
  );
}

export default function UnderwritingWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<UwDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    apiJson<UwDetail>(`/underwriting/applications/${id}`).then(setD).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    if (d?.status !== "QUEUED" && d?.status !== "PROCESSING") return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [d, load]);

  if (error && !d) return <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</div>;
  if (!d) return <p className="text-sm text-slate-500">Memuat…</p>;
  const a = d.assessment;
  const docTypes = d.labels.doc_types;
  const p = (k: string) => a?.profile[k]?.value as string | number | null | undefined;
  const fieldLabel = (k: string) => UW_FIELD_LABEL[k] ?? d.labels.questions[k] ?? d.labels.lab_tests[k] ?? d.labels.fields[k] ?? k;
  const openDoc = async (docId: string) => {
    const w = window.open("", "_blank");
    const url = await blobUrl(`/underwriting/applications/${d.id}/documents/${docId}`);
    if (w) w.location.href = url;
  };
  const t = d.terms;
  const signedOrFinal = d.decision_detail ? "keputusan final underwriter" : t.source === "doctor" ? `ditandatangani ${d.review?.doctor}` : "draf sistem, belum ditandatangani";

  return (
    <div className="space-y-5">
      <div>
        <Link href="/underwriting" className="text-sm text-sky-800 hover:underline">‹ Underwriting</Link>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-lg font-semibold">{d.application_number} · {d.applicant_name ?? "calon peserta"}</h1>
          <div className="flex items-center gap-2">
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{UW_STATUS_LABEL[d.status]}</span>
            {a && <button className="btn-secondary" onClick={() => downloadFile(`/underwriting/applications/${d.id}/pdf`, `underwriting_${d.application_number}.pdf`).catch((e) => setError(e.message))}>Unduh PDF rekomendasi</button>}
          </div>
        </div>
        <p className="text-xs text-slate-400">{d.label}</p>
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      {(d.status === "QUEUED" || d.status === "PROCESSING") && <div className="card text-sm text-slate-600">Dokumen sedang dibaca dan dinilai…</div>}
      {d.status === "FAILED" && <div className="card border-rose-200 text-sm text-rose-800">Gagal diproses: {d.processing_error}</div>}

      {a && (
        <>
          <div className="grid gap-5 lg:grid-cols-[1fr_24rem]">
            <div className="card">
              <h2 className="mb-2 font-medium">Data pengajuan (SPAJ)</h2>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
                <div><dt className="text-xs text-slate-500">No. SPAJ</dt><dd>{d.spaj_number ?? "-"}</dd></div>
                <div><dt className="text-xs text-slate-500">Jenis kelamin</dt><dd>{d.applicant_sex === "P" ? "Perempuan" : d.applicant_sex === "L" ? "Laki-laki" : "-"}</dd></div>
                <div><dt className="text-xs text-slate-500">Tanggal lahir · usia</dt><dd>{tanggal(d.applicant_birth_date)} · {uwValue(a.fields["applicant.age"]?.value)} th</dd></div>
                <div><dt className="text-xs text-slate-500">Pekerjaan</dt><dd>{p("occupation") ?? "-"}</dd></div>
                <div><dt className="text-xs text-slate-500">Produk</dt><dd>{d.product_name ?? "-"}</dd></div>
                <div><dt className="text-xs text-slate-500">Uang pertanggungan</dt><dd>{rupiah(d.sum_assured)}</dd></div>
                <div><dt className="text-xs text-slate-500">Premi dasar tahunan</dt><dd>{rupiah(d.base_premium)}</dd></div>
                <div><dt className="text-xs text-slate-500">Tanggal SPAJ</dt><dd>{tanggal(p("spaj_date") as string)}</dd></div>
                <div><dt className="text-xs text-slate-500">Tanggal MCU</dt><dd>{tanggal(p("exam_date") as string)}</dd></div>
              </dl>
            </div>
            <div className="card space-y-2">
              <h2 className="font-medium">Rekomendasi</h2>
              {t.recommendation && <span className={`inline-block rounded px-2 py-1 text-sm font-semibold ${UW_REC_STYLE[d.decision_detail?.decision ?? t.recommendation]}`}>{UW_REC_LABEL[d.decision_detail?.decision ?? t.recommendation]}</span>}
              <p className="text-xs text-slate-500">{signedOrFinal}</p>
              <dl className="grid grid-cols-2 gap-1 text-sm">
                <dt className="text-slate-500">Kelas risiko</dt><dd>{d.labels.classes.find((c) => c.code === (d.decision_detail?.risk_class ?? t.risk_class))?.name ?? t.risk_class}</dd>
                <dt className="text-slate-500">Total debit sistem</dt><dd>{a.debit_total}</dd>
                <dt className="text-slate-500">Loading premi</dt><dd>{d.decision_detail?.loading_pct ?? t.loading_pct}%</dd>
                <dt className="text-slate-500">Premi setelah loading</dt><dd>{rupiah(d.decision_detail ? d.decision_detail.final_premium : d.premium_preview)}</dd>
              </dl>
              {(d.decision_detail?.exclusions ?? t.exclusions).length > 0 && (
                <div className="text-sm"><div className="text-slate-500">Pengecualian</div>
                  <ul className="list-disc pl-5">{(d.decision_detail?.exclusions ?? t.exclusions).map((e) => <li key={e}>{e}</li>)}</ul></div>
              )}
              {t.source === "doctor" && d.review && (
                <p className="text-xs text-slate-600">
                  {d.review.action === "AGREE" ? "Dokter menyetujui draf sistem" : `Dokter mengubah draf sistem (${UW_REC_LABEL[a.recommendation]})`} · {waktu(d.review.signed_at)}
                  {d.review.notes && <span className="block italic">“{d.review.notes}”</span>}
                </p>
              )}
              {d.decision_detail && (
                <p className="text-xs text-slate-600">Diputuskan {d.decision_detail.decided_by} · {waktu(d.decision_detail.decided_at)}
                  {d.decision_detail.notes && <span className="block italic">“{d.decision_detail.notes}”</span>}</p>
              )}
              {a.needs_doctor && !d.review && (
                <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                  <div className="font-medium">Wajib ditelaah dokter sebelum diputuskan</div>
                  <ul className="list-disc pl-4">{a.doctor_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                </div>
              )}
            </div>
          </div>

          {d.can_sign && <SignPanel d={d} onDone={setD} />}
          {d.can_decide && <DecisionPanel d={d} onDone={setD} />}

          <div className="card">
            <h2 className="mb-2 font-medium">Temuan ({a.findings.length})</h2>
            {a.findings.length === 0 && <p className="text-sm text-slate-600">Tidak ada aturan yang terpicu. Semua data wajib terbaca.</p>}
            <ul className="space-y-3">
              {a.findings.map((f) => (
                <li key={f.rule_id} className="border-l-4 border-slate-200 pl-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${KIND_STYLE[f.kind] ?? "bg-slate-100"}`}>{UW_KIND_LABEL[f.kind] ?? f.kind}{f.debit ? ` +${f.debit}` : ""}</span>
                    <span className="font-medium">{f.name}</span>
                    <span className="font-mono text-xs text-slate-400">{f.rule_id} · {f.reason_code}</span>
                  </div>
                  <p className="text-sm text-slate-700">{f.message}</p>
                  {f.exclusion && <p className="text-xs text-violet-800">Pengecualian: {f.exclusion}</p>}
                  <Quotes a={a} ids={f.line_ids} docTypes={docTypes} />
                  {f.reference && <p className="mt-0.5 text-[11px] text-slate-400">Dasar: {f.reference}</p>}
                </li>
              ))}
            </ul>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            {GROUPS.map((g) => {
              const entries = Object.entries(a.fields).filter(([k]) => g.prefix.some((x) => k.startsWith(x)));
              if (!entries.length) return null;
              return (
                <div key={g.title} className="card">
                  <h2 className="mb-2 font-medium">{g.title}</h2>
                  <table className="w-full text-sm">
                    <tbody>
                      {entries.map(([k, f]: [string, UwField]) => (
                        <tr key={k} className="border-t align-top">
                          <td className="py-1 pr-2 text-slate-600">{fieldLabel(k)}<div className="font-mono text-[10px] text-slate-400">{k}</div></td>
                          <td className="py-1">
                            <span className={f.value === null ? "text-amber-700" : "font-medium"}>{uwValue(f.value)}</span>
                            {f.detail && <span className="text-xs text-slate-500"> · {f.detail}</span>}
                            {f.source === "hitung" && <span className="ml-1 rounded bg-slate-100 px-1 text-[10px] text-slate-500">dihitung</span>}
                            <Quotes a={a} ids={f.line_ids.slice(0, 2)} docTypes={docTypes} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-medium">Dokumen ({d.documents_list.length})</h2>
          <ul className="space-y-2 text-sm">
            {d.documents_list.map((doc) => (
              <li key={doc.id} className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate">{doc.filename}</div>
                  <div className="text-xs text-slate-500">{docTypes[doc.doc_type] ?? doc.doc_type}{doc.page_count ? ` · ${doc.page_count} hal.` : ""}</div>
                  <div className="break-all font-mono text-[10px] text-slate-400" title="SHA-256">{doc.sha256}</div>
                </div>
                <button className="text-xs text-sky-800 hover:underline" onClick={() => openDoc(doc.id).catch((e) => setError(e.message))}>Buka</button>
              </li>
            ))}
          </ul>
        </div>
        {a && (
          <div className="card text-sm">
            <h2 className="mb-2 font-medium">Versi dan catatan sistem</h2>
            <dl className="grid grid-cols-2 gap-1 text-xs">
              <dt className="text-slate-500">Aturan</dt><dd className="font-mono">{a.rules_version}</dd>
              <dt className="text-slate-500">Model ekstraksi</dt><dd className="font-mono">{a.model_version}</dd>
              <dt className="text-slate-500">Prompt</dt><dd className="font-mono">{a.prompt_version}</dd>
              <dt className="text-slate-500">OCR</dt><dd className="font-mono">{a.ocr_engine}</dd>
              <dt className="text-slate-500">Penilaian</dt><dd>v{a.version} · {waktu(a.created_at)}</dd>
            </dl>
            {a.skipped.length > 0 && (
              <div className="mt-2 text-xs text-amber-800">Aturan tidak bisa dinilai: {a.skipped.map((s) => `${s.rule_id} (${s.missing.join(", ")})`).join("; ")}</div>
            )}
            {a.warnings.length > 0 && <ul className="mt-2 list-disc pl-4 text-xs text-slate-500">{a.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            <p className="mt-2 text-xs text-slate-500">Debit, kelas risiko, dan loading memakai tabel contoh. Pada pemakaian sungguhan memakai tabel underwriting klien.</p>
          </div>
        )}
      </div>
    </div>
  );
}
