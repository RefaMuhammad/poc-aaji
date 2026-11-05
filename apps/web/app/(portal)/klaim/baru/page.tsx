"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, apiFetch, apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { BatchResult, Tenant } from "@/lib/types";

const EMPTY = {
  claim_number: "",
  policy_number: "",
  member_id: "",
  patient_name: "",
  hospital_name: "",
  admission_date: "",
  discharge_date: "",
  billed_amount: "",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-slate-600">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function SingleClaimForm({ insurerId }: { insurerId: string | null }) {
  const router = useRouter();
  const [form, setForm] = useState(EMPTY);
  const [files, setFiles] = useState<File[]>([]);
  const [step, setStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(null);

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0) {
      setError("Lampirkan minimal satu dokumen (PDF/JPG/PNG)");
      return;
    }
    setError(null);
    try {
      let id = claimId;
      if (!id) {
        setStep("Membuat klaim…");
        const claim = await apiJson<{ id: string }>("/claims", {
          method: "POST",
          body: JSON.stringify({
            ...form,
            patient_name: form.patient_name || null,
            insurer_id: insurerId,
            billed_amount: Number(form.billed_amount.replace(/\D/g, "")),
          }),
        });
        id = claim.id;
        setClaimId(id); // bila unggah gagal, coba lagi tanpa membuat klaim baru
      }
      setStep(`Mengunggah ${files.length} dokumen…`);
      const body = new FormData();
      files.forEach((f) => body.append("files", f));
      await apiFetch(`/claims/${id}/documents`, { method: "POST", body });
      router.push(`/klaim/${id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal menghubungi server");
      setStep(null);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-4">
      <h2 className="font-medium">Satu klaim</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Nomor klaim"><input className="input" value={form.claim_number} onChange={set("claim_number")} required disabled={!!claimId} /></Field>
        <Field label="Nomor polis"><input className="input" value={form.policy_number} onChange={set("policy_number")} required disabled={!!claimId} /></Field>
        <Field label="ID peserta"><input className="input" value={form.member_id} onChange={set("member_id")} required disabled={!!claimId} /></Field>
        <Field label="Nama peserta (opsional)"><input className="input" value={form.patient_name} onChange={set("patient_name")} disabled={!!claimId} /></Field>
        <Field label="Rumah sakit"><input className="input" value={form.hospital_name} onChange={set("hospital_name")} required disabled={!!claimId} /></Field>
        <Field label="Nilai tagihan (Rp)"><input className="input" inputMode="numeric" value={form.billed_amount} onChange={set("billed_amount")} required disabled={!!claimId} /></Field>
        <Field label="Tanggal masuk"><input type="date" className="input" value={form.admission_date} onChange={set("admission_date")} required disabled={!!claimId} /></Field>
        <Field label="Tanggal keluar"><input type="date" className="input" value={form.discharge_date} onChange={set("discharge_date")} required disabled={!!claimId} /></Field>
      </div>
      <Field label="Dokumen klaim (resume medis, hasil lab, CPPT, rincian tagihan; PDF/JPG/PNG maks. 20 MB)">
        <input
          type="file"
          multiple
          accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
          className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
      </Field>
      {files.length > 0 && <p className="text-xs text-slate-500">{files.map((f) => f.name).join(", ")}</p>}
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <button type="submit" className="btn-primary" disabled={!!step}>
        {step ?? (claimId ? "Coba unggah lagi" : "Kirim klaim")}
      </button>
    </form>
  );
}

function BatchUpload({ insurerId }: { insurerId: string | null }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const qs = insurerId ? `?insurer_id=${encodeURIComponent(insurerId)}` : "";
      setResult(await apiJson<BatchResult>(`/claims/batch${qs}`, { method: "POST", body }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card space-y-3">
      <h2 className="font-medium">Banyak klaim (ZIP)</h2>
      <p className="text-sm text-slate-600">
        ZIP berisi <code>manifest.xlsx</code> dan satu folder per klaim. Kolom manifest: folder, nomor_klaim, nomor_polis,
        id_peserta, nama_peserta, nama_rs, tanggal_masuk, tanggal_keluar, nilai_tagihan.
      </p>
      <input
        type="file"
        accept=".zip,application/zip"
        className="block w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <button type="submit" className="btn-primary" disabled={!file || busy}>
        {busy ? "Mengunggah dan memeriksa ZIP…" : "Unggah ZIP"}
      </button>
      {result && (
        <div className="space-y-2">
          <p className="text-sm">
            <b>{result.created}</b> klaim dibuat dan masuk antrean proses, <b>{result.failed}</b> baris gagal.{" "}
            <Link href="/klaim" className="text-sky-800 underline">Lihat daftar klaim</Link>
          </p>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1 pr-2">Baris</th><th className="py-1 pr-2">Folder</th><th className="py-1 pr-2">Nomor klaim</th><th className="py-1 pr-2">Dokumen</th><th className="py-1">Hasil</th></tr>
            </thead>
            <tbody>
              {result.rows.map((r) => (
                <tr key={r.row} className="border-t">
                  <td className="py-1 pr-2">{r.row}</td>
                  <td className="py-1 pr-2">{r.folder ?? "-"}</td>
                  <td className="py-1 pr-2">
                    {r.claim_id ? <Link href={`/klaim/${r.claim_id}`} className="text-sky-800 hover:underline">{r.claim_number}</Link> : r.claim_number ?? "-"}
                  </td>
                  <td className="py-1 pr-2">{r.documents}</td>
                  <td className={`py-1 ${r.ok ? "text-emerald-700" : "text-rose-700"}`}>{r.ok ? "Berhasil" : r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </form>
  );
}

/** Operator TPA melayani beberapa asuransi: pilih asuransi pemilik klaim sebelum mengunggah. */
function useTargetTenant() {
  const { user } = useAuth();
  const isTpa = user?.role === "tpa_operator";
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [insurerId, setInsurerId] = useState<string | null>(null);
  useEffect(() => {
    if (!isTpa) return;
    apiJson<Tenant[]>("/tenants")
      .then((t) => {
        setTenants(t);
        const wanted = new URLSearchParams(window.location.search).get("insurer_id");
        setInsurerId(t.find((x) => x.insurer_id === wanted)?.insurer_id ?? t[0]?.insurer_id ?? null);
      })
      .catch(() => setTenants([]));
  }, [isTpa]);
  return { isTpa, tenants, insurerId, setInsurerId };
}

export default function NewClaimPage() {
  const { isTpa, tenants, insurerId, setInsurerId } = useTargetTenant();
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Unggah klaim</h1>
      <p className="text-sm text-slate-600">Gunakan hanya data rekaan. Jangan unggah data pasien sungguhan.</p>
      {isTpa && (
        <label className="card flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">Asuransi pemilik klaim</span>
          <select className="input w-auto" value={insurerId ?? ""} onChange={(e) => setInsurerId(e.target.value)}>
            {tenants.map((t) => (
              <option key={t.insurer_id} value={t.insurer_id}>{t.display_name ?? t.name}</option>
            ))}
          </select>
          <span className="text-slate-500">Ambang triase dan SLA mengikuti pengaturan asuransi yang dipilih.</span>
        </label>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <SingleClaimForm insurerId={isTpa ? insurerId : null} />
        <BatchUpload insurerId={isTpa ? insurerId : null} />
      </div>
    </div>
  );
}
