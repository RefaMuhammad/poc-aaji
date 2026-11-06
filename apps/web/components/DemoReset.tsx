"use client";

import { useEffect, useState } from "react";
import { apiJson, clearSession } from "@/lib/api";

type ResetStatus = {
  enabled: boolean;
  state: "idle" | "running" | "done" | "failed";
  step?: string | null;
  step_no?: number | null;
  steps_total?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
  log_tail?: string[];
};

const FLAG = "mab_demo_reset";

function setFlag(on: boolean) {
  try {
    if (on) sessionStorage.setItem(FLAG, "1");
    else sessionStorage.removeItem(FLAG);
  } catch {
    /* penyimpanan browser tidak tersedia */
  }
}

function hasFlag(): boolean {
  try {
    return sessionStorage.getItem(FLAG) === "1";
  } catch {
    return false;
  }
}

async function fetchStatus(): Promise<ResetStatus | null> {
  try {
    const r = await fetch("/api/demo/reset", { cache: "no-store" });
    return r.ok ? ((await r.json()) as ResetStatus) : null;
  } catch {
    return null;
  }
}

/** Kartu di halaman admin: tombol reset dengan konfirmasi. Tidak tampil bila mode demo mati. */
export function DemoResetCard() {
  const [status, setStatus] = useState<ResetStatus | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStatus().then(setStatus);
  }, []);

  if (!status?.enabled) return null;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiJson("/demo/reset", { method: "POST" });
      setFlag(true);
      clearSession();
      window.location.href = "/login";
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <section className="card space-y-3 border-amber-200">
      <div>
        <h2 className="font-medium">Reset data demo</h2>
        <p className="text-sm text-slate-600">
          Menghapus semua klaim, dokumen, telaah, keputusan, banding, underwriting, laporan, dan log audit, lalu
          mengisi ulang data demo seperti setelah instalasi baru. Pakai ini supaya skenario yang hanya bisa
          dijalankan sekali (unggah SYN-DEN-09, dokumen susulan SYN-TIF-10, banding SYN-GEA-06, unggah UW-24) bisa
          didemokan lagi. Prosesnya beberapa menit, dan semua pengguna harus login ulang setelahnya.
        </p>
        <p className="mt-1 text-xs text-slate-500">Hanya tersedia di mode demo. Data rekaan untuk demonstrasi.</p>
      </div>
      {status.state === "running" && (
        <p className="text-sm text-amber-800">Reset sedang berjalan: {status.step}. Buka halaman login untuk melihat progres.</p>
      )}
      {error && <p className="text-sm text-rose-700">{error}</p>}
      {!confirming ? (
        <button type="button" className="btn-secondary" disabled={status.state === "running"} onClick={() => setConfirming(true)}>
          Reset data demo
        </button>
      ) : (
        <div className="space-y-2 rounded border border-rose-200 bg-rose-50 p-3">
          <p className="text-sm text-rose-800">
            Semua data di aplikasi ini akan dihapus dan diganti data demo baru. Lanjutkan?
          </p>
          <div className="flex gap-2">
            <button type="button" className="btn-danger" disabled={busy} onClick={start}>
              {busy ? "Memulai…" : "Ya, hapus dan isi ulang"}
            </button>
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => setConfirming(false)}>
              Batal
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/** Banner di halaman login: progres reset, lalu hasilnya. */
export function DemoResetProgress({ onRunningChange }: { onRunningChange?: (running: boolean) => void }) {
  const [status, setStatus] = useState<ResetStatus | null>(null);
  const [fromReset, setFromReset] = useState(false);

  useEffect(() => {
    setFromReset(hasFlag());
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const poll = async () => {
      const s = await fetchStatus();
      if (stopped) return;
      setStatus(s);
      onRunningChange?.(s?.state === "running");
      if (s?.state === "running") timer = setTimeout(poll, 3000);
    };
    poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!status?.enabled) return null;
  if (status.state === "running") {
    const total = status.steps_total || 12;
    const pct = Math.max(5, Math.round(((status.step_no ?? 0) / total) * 100));
    return (
      <div className="w-full max-w-sm space-y-2 rounded border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900" role="status">
        <p className="font-medium">Data demo sedang diisi ulang</p>
        <p>{status.step ?? "Menyiapkan"}…</p>
        <div className="h-2 w-full rounded bg-amber-100">
          <div className="h-2 rounded bg-amber-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-xs">Biasanya beberapa menit. Login bisa dipakai lagi setelah selesai.</p>
      </div>
    );
  }
  if (!fromReset) return null;
  if (status.state === "done") {
    return (
      <div className="w-full max-w-sm rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900" role="status">
        {status.message ?? "Data demo sudah diisi ulang."}
        <button type="button" className="ml-2 text-xs underline" onClick={() => { setFlag(false); setFromReset(false); }}>
          Tutup
        </button>
      </div>
    );
  }
  if (status.state === "failed") {
    return (
      <div className="w-full max-w-sm space-y-2 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900" role="alert">
        <p className="font-medium">Reset data demo gagal</p>
        <p>{status.message}</p>
        {status.log_tail && status.log_tail.length > 0 && (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-xs">{status.log_tail.join("\n")}</pre>
        )}
        <p className="text-xs">Jalankan ulang dari terminal: lihat bagian Persiapan di docs/demo-script.md.</p>
      </div>
    );
  }
  return null;
}
