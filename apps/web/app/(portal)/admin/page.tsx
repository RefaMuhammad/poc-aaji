"use client";

import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { RulesetInfo, RulesetRule, User } from "@/lib/types";
import { REASON_LABEL, RECOMMENDATION_LABEL, ROLE_LABEL, SEVERITY_LABEL } from "@/lib/format";
import { TriageBadge } from "@/components/Badges";
import { DemoResetCard } from "@/components/DemoReset";

function RuleTable({ rules }: { rules: RulesetRule[] }) {
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-slate-500">
        <tr>
          <th className="py-1 pr-3">ID</th>
          <th className="py-1 pr-3">Aturan</th>
          <th className="py-1 pr-3">Kode alasan</th>
          <th className="py-1 pr-3">Keparahan</th>
          <th className="py-1 pr-3">Butuh AI</th>
          <th className="py-1">Rujukan</th>
        </tr>
      </thead>
      <tbody>
        {rules.map((r) => (
          <tr key={r.id} className="border-t align-top">
            <td className="py-1.5 pr-3 font-mono text-xs">{r.id}</td>
            <td className="py-1.5 pr-3">{r.name}</td>
            <td className="py-1.5 pr-3" title={REASON_LABEL[r.reason_code]}>{r.reason_code}</td>
            <td className="py-1.5 pr-3">{SEVERITY_LABEL[r.severity] ?? r.severity}</td>
            <td className="py-1.5 pr-3">{r.needs_ai ? "ya" : "tidak"}</td>
            <td className="py-1.5 text-xs text-slate-500">{r.reference ?? "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AdminPage() {
  const [rs, setRs] = useState<RulesetInfo | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJson<RulesetInfo>("/admin/ruleset").then(setRs).catch((e) => setError(e.message));
    apiJson<User[]>("/users").then(setUsers).catch((e) => setError(e.message));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold">Aturan & pengguna</h1>
        <p className="text-sm text-slate-500">
          Baca saja. Aturan klinis diubah lewat file konfigurasi YAML, bukan dari layar ini. Penyesuaian per asuransi
          (ambang triase, aturan yang dimatikan, SLA) diatur di halaman <a href="/admin/tenant" className="text-sky-800 hover:underline">Tenant &amp; API key</a>.
        </p>
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}

      <DemoResetCard />

      {rs && (
        <section className="space-y-4">
          <div className="card flex flex-wrap gap-x-8 gap-y-1 text-sm">
            <div><span className="text-slate-500">Versi aturan aktif</span><div className="font-mono font-medium">{rs.version}</div></div>
            <div><span className="text-slate-500">Status</span><div>{rs.status ?? "-"}</div></div>
            <div><span className="text-slate-500">File</span><div className="font-mono text-xs">{rs.path}</div></div>
          </div>

          <div className="card">
            <h2 className="mb-2 font-medium">Aturan triase (dievaluasi berurutan)</h2>
            <ol className="space-y-1 text-sm">
              {rs.triage.map((t, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <span className="w-5 text-slate-400">{i + 1}.</span>
                  <span className="min-w-[12rem]">{t.jika}</span>
                  <TriageBadge triage={t.status} />
                  <span className="text-slate-500">{RECOMMENDATION_LABEL[t.rekomendasi_awal] ?? t.rekomendasi_awal}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="card overflow-x-auto">
            <h2 className="mb-2 font-medium">Aturan umum</h2>
            <RuleTable rules={rs.general_rules} />
          </div>

          {rs.diagnoses.map((d) => (
            <div key={d.id} className="card overflow-x-auto">
              <h2 className="font-medium">{d.name}</h2>
              <p className="mb-2 text-xs text-slate-500">
                ICD-10 {d.icd10.join(", ")} · penelaah spesialis: {d.specialty ?? "semua spesialis"}
              </p>
              <RuleTable rules={d.rules} />
            </div>
          ))}

          {rs.benefit && (
            <div className="card overflow-x-auto">
              <h2 className="font-medium">Aturan benefit polis</h2>
              <p className="mb-2 text-xs text-slate-500">
                Versi <span className="font-mono">{rs.benefit.version}</span> · <span className="font-mono">{rs.benefit.path}</span> · hanya
                dijalankan untuk tenant yang punya data polis
              </p>
              <RuleTable rules={rs.benefit.rules} />
            </div>
          )}
        </section>
      )}

      {users && (
        <section className="card overflow-x-auto">
          <h2 className="mb-2 font-medium">Pengguna ({users.length})</h2>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1 pr-3">Nama</th><th className="py-1 pr-3">Email</th><th className="py-1 pr-3">Peran</th><th className="py-1">Keterangan</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t">
                  <td className="py-1.5 pr-3">{u.full_name}</td>
                  <td className="py-1.5 pr-3">{u.email}</td>
                  <td className="py-1.5 pr-3">{ROLE_LABEL[u.role] ?? u.role}</td>
                  <td className="py-1.5">{u.specialty ?? u.facility_name ?? u.member_ref ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
