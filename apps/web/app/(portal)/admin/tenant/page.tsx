"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiJson } from "@/lib/api";
import type { ApiClient, ApiScope, RulesetInfo, RulesetRule, Tenant, TenantSettingsInput } from "@/lib/types";
import { SEVERITY_LABEL, waktu } from "@/lib/format";
import { IntegrationLog } from "@/components/IntegrationLog";

const MAX_LOGO_BYTES = 200 * 1024;

function toInput(t: Tenant): TenantSettingsInput {
  return {
    display_name: t.display_name,
    logo_data_url: t.logo_data_url,
    primary_color: t.primary_color,
    triage_red_min_score: t.triage_red_min_score,
    triage_yellow_min_score: t.triage_yellow_min_score,
    disabled_rules: t.disabled_rules,
    sla_gp_hours: t.sla_gp_hours,
    sla_specialist_hours: t.sla_specialist_hours,
    auto_assign: t.auto_assign,
    webhook_url: t.webhook_url,
  };
}

function randomSecret(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function numOrNull(v: string): number | null {
  return v.trim() === "" ? null : Number(v);
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2 border-t pt-4 first:border-0 first:pt-0">
      <div>
        <h3 className="font-medium">{title}</h3>
        {hint && <p className="text-xs text-slate-500">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

function RuleChecklist({
  title,
  rules,
  disabled,
  onToggle,
}: {
  title: string;
  rules: RulesetRule[];
  disabled: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-500">{title}</div>
      <ul className="grid gap-1 sm:grid-cols-2">
        {rules.map((r) => (
          <li key={r.id}>
            <label className={`flex items-start gap-2 text-sm ${disabled.has(r.id) ? "text-slate-400 line-through" : ""}`}>
              <input type="checkbox" className="mt-1" checked={!disabled.has(r.id)} onChange={() => onToggle(r.id)} />
              <span>
                <span className="font-mono text-xs">{r.id}</span> {r.name}{" "}
                <span className="text-xs text-slate-400">({SEVERITY_LABEL[r.severity] ?? r.severity})</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SettingsForm({ tenant, ruleset, onSaved }: { tenant: Tenant; ruleset: RulesetInfo | null; onSaved: (t: Tenant) => void }) {
  const [form, setForm] = useState<TenantSettingsInput>(toInput(tenant));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    setForm(toInput(tenant));
  }, [tenant]);
  useEffect(() => {
    setError(null);
    setMessage(null);
  }, [tenant.insurer_id]);

  const disabled = useMemo(() => new Set(form.disabled_rules), [form.disabled_rules]);
  const toggleRule = (id: string) =>
    setForm((f) => ({
      ...f,
      disabled_rules: f.disabled_rules.includes(id) ? f.disabled_rules.filter((x) => x !== id) : [...f.disabled_rules, id].sort(),
    }));

  const onLogo = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_LOGO_BYTES) {
      setError("Logo terlalu besar (maksimal 200 KB)");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setForm((f) => ({ ...f, logo_data_url: String(reader.result) }));
    reader.readAsDataURL(file);
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const t = await apiJson<Tenant>(`/tenants/${tenant.insurer_id}/settings`, { method: "PUT", body: JSON.stringify(form) });
      onSaved(t);
      setMessage(`Tersimpan sebagai versi ${t.version}. Berlaku untuk klaim yang diproses setelah ini.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="card space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold">Pengaturan {tenant.display_name ?? tenant.name}</h2>
        <span className="text-xs text-slate-500">
          versi {tenant.version}
          {tenant.updated_at ? ` · diubah ${waktu(tenant.updated_at)}` : ""} · versi aturan efektif{" "}
          <span className="font-mono">{tenant.effective_ruleset_version}</span>
        </span>
      </div>

      <Section title="Tampilan" hint="Nama dan logo tampil di header portal pengguna asuransi ini.">
        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <label className="block text-sm">
            <span className="text-slate-600">Nama tampilan</span>
            <input
              className="input mt-1"
              value={form.display_name ?? ""}
              placeholder={tenant.name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value || null })}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Warna utama</span>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="color"
                className="h-9 w-12 rounded border"
                value={form.primary_color ?? "#334155"}
                onChange={(e) => setForm({ ...form, primary_color: e.target.value })}
              />
              <button type="button" className="text-xs text-slate-500 hover:underline" onClick={() => setForm({ ...form, primary_color: null })}>
                bawaan
              </button>
            </div>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {form.logo_data_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={form.logo_data_url} alt="Logo" className="h-12 w-12 rounded border object-contain" />
          ) : (
            <div className="flex h-12 w-12 items-center justify-center rounded border text-xs text-slate-400">logo</div>
          )}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml"
            className="text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5"
            onChange={(e) => onLogo(e.target.files?.[0])}
          />
          {form.logo_data_url && (
            <button type="button" className="text-xs text-rose-700 hover:underline" onClick={() => setForm({ ...form, logo_data_url: null })}>
              Hapus logo
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 rounded border border-t-4 bg-white px-3 py-2 text-sm" style={{ borderTopColor: form.primary_color ?? "#334155" }}>
          <span className="font-semibold">MAB Indonesia</span>
          <span className="flex items-center gap-2 border-l pl-2">
            {form.logo_data_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={form.logo_data_url} alt="" className="h-6 w-6 rounded object-contain" />
            )}
            <span className="font-medium" style={form.primary_color ? { color: form.primary_color } : undefined}>
              {form.display_name || tenant.name}
            </span>
          </span>
          <span className="ml-auto text-xs text-slate-400">pratinjau header</span>
        </div>
      </Section>

      <Section
        title="Ambang triase"
        hint="Kosongkan untuk memakai nilai file aturan. Temuan berat (HIGH) selalu merah dan dokumen wajib yang hilang selalu kuning, berapa pun ambangnya."
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-600">Merah bila skor ≥</span>
            <input
              type="number"
              min={1}
              max={100}
              className="input mt-1"
              value={form.triage_red_min_score ?? ""}
              placeholder={`bawaan ${tenant.default_red_min_score ?? "-"}`}
              onChange={(e) => setForm({ ...form, triage_red_min_score: numOrNull(e.target.value) })}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">Kuning bila skor ≥</span>
            <input
              type="number"
              min={1}
              max={100}
              className="input mt-1"
              value={form.triage_yellow_min_score ?? ""}
              placeholder={`bawaan ${tenant.default_yellow_min_score ?? "-"}`}
              onChange={(e) => setForm({ ...form, triage_yellow_min_score: numOrNull(e.target.value) })}
            />
          </label>
        </div>
        <p className="text-xs text-slate-500">Bobot temuan: berat 40, sedang 20, ringan 10. Contoh: ambang merah 20 membuat satu temuan sedang langsung merah.</p>
      </Section>

      <Section title="Aturan aktif" hint="Aturan yang dicentang dinilai untuk klaim asuransi ini. Isi aturan tetap dari file YAML yang divalidasi dokter.">
        {ruleset ? (
          <div className="space-y-3">
            <RuleChecklist title="Aturan umum" rules={ruleset.general_rules} disabled={disabled} onToggle={toggleRule} />
            {ruleset.diagnoses.map((d) => (
              <RuleChecklist key={d.id} title={d.name} rules={d.rules} disabled={disabled} onToggle={toggleRule} />
            ))}
            {ruleset.benefit && (
              <RuleChecklist
                title={`Aturan benefit polis (${ruleset.benefit.version}, hanya bila tenant punya data polis)`}
                rules={ruleset.benefit.rules}
                disabled={disabled}
                onToggle={toggleRule}
              />
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-500">Memuat aturan…</p>
        )}
      </Section>

      <Section title="SLA dan penugasan dokter" hint="Batas waktu dihitung sejak kasus masuk antrean dokter (atau sejak dieskalasi).">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-600">SLA dokter umum (jam)</span>
            <input
              type="number"
              min={1}
              max={720}
              className="input mt-1"
              value={form.sla_gp_hours}
              onChange={(e) => setForm({ ...form, sla_gp_hours: Number(e.target.value) })}
            />
          </label>
          <label className="block text-sm">
            <span className="text-slate-600">SLA dokter spesialis (jam)</span>
            <input
              type="number"
              min={1}
              max={720}
              className="input mt-1"
              value={form.sla_specialist_hours}
              onChange={(e) => setForm({ ...form, sla_specialist_hours: Number(e.target.value) })}
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.auto_assign} onChange={(e) => setForm({ ...form, auto_assign: e.target.checked })} />
          Tugaskan kasus otomatis ke dokter dengan beban paling ringan (bila mati, kasus masuk antrean bersama)
        </label>
      </Section>

      <Section
        title="Webhook ke sistem asuransi"
        hint="Dikirim saat rekomendasi dirilis ke asuransi, saat keputusan dicatat, dan saat klaim gagal diproses. Draf yang menunggu dokter tidak pernah dikirim."
      >
        <label className="block text-sm">
          <span className="text-slate-600">URL penerima</span>
          <input
            className="input mt-1 font-mono text-xs"
            value={form.webhook_url ?? ""}
            placeholder="https://sistem-inti-asuransi.example/mab/webhook (kosong = webhook mati)"
            onChange={(e) => setForm({ ...form, webhook_url: e.target.value || null })}
          />
        </label>
        <button
          type="button"
          className="text-xs text-sky-800 hover:underline"
          onClick={() => setForm({ ...form, webhook_url: `http://api:8000/integrations/demo-sink/${tenant.code}` })}
        >
          Pakai penerima demo (sistem inti rekaan di dalam docker compose)
        </button>
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label className="block min-w-[16rem] flex-1">
            <span className="text-slate-600">Rahasia tanda tangan (HMAC-SHA256)</span>
            <input
              className="input mt-1 font-mono text-xs"
              value={form.webhook_secret ?? ""}
              placeholder={tenant.webhook_secret_set ? "tersimpan (kosongkan untuk tidak mengubah)" : "minimal 16 karakter"}
              onChange={(e) => setForm({ ...form, webhook_secret: e.target.value || null })}
            />
          </label>
          <button type="button" className="btn-secondary" onClick={() => setForm({ ...form, webhook_secret: randomSecret() })}>
            Buat acak
          </button>
          {tenant.webhook_secret_set && (
            <button type="button" className="text-xs text-rose-700 hover:underline" onClick={() => setForm({ ...form, webhook_secret: "" })}>
              Hapus rahasia
            </button>
          )}
        </div>
        <p className="text-xs text-slate-500">
          Header: <code>X-MAB-Event</code>, <code>X-MAB-Delivery</code>, dan <code>X-MAB-Signature: sha256=…</code> atas body mentah.
          {form.webhook_secret ? " Salin rahasia ini ke sistem penerima sebelum menyimpan; setelah disimpan rahasia tidak ditampilkan lagi." : ""}
          {form.webhook_secret === "" ? " Rahasia akan dihapus saat disimpan." : ""}
        </p>
      </Section>

      {error && <p className="text-sm text-rose-700">{error}</p>}
      {message && <p className="text-sm text-emerald-700">{message}</p>}
      <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Menyimpan…" : "Simpan pengaturan"}</button>
    </form>
  );
}

function ApiClients({ tenant }: { tenant: Tenant }) {
  const [clients, setClients] = useState<ApiClient[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<ApiClient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scopes, setScopes] = useState<ApiScope[]>([]);
  const [chosen, setChosen] = useState<string[]>(["claims:read"]);
  useEffect(() => {
    apiJson<ApiScope[]>("/tenants/api-scopes").then(setScopes).catch(() => setScopes([]));
  }, []);

  const load = useCallback(() => {
    apiJson<ApiClient[]>(`/tenants/${tenant.insurer_id}/api-clients`).then(setClients).catch((e) => setError(e.message));
  }, [tenant.insurer_id]);
  useEffect(() => {
    setCreated(null);
    load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const c = await apiJson<ApiClient>(`/tenants/${tenant.insurer_id}/api-clients`, {
        method: "POST",
        body: JSON.stringify({ name, scopes: chosen }),
      });
      setCreated(c);
      setName("");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const revoke = async (c: ApiClient) => {
    setError(null);
    try {
      await apiJson(`/tenants/${tenant.insurer_id}/api-clients/${c.id}/revoke`, { method: "POST" });
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="card space-y-3">
      <div>
        <h2 className="font-semibold">Akun layanan (API key)</h2>
        <p className="text-xs text-slate-500">
          Untuk sistem inti asuransi/TPA: kirim klaim (multipart atau FHIR R4 Bundle), kirim data polis, dan baca status klaim lewat{" "}
          <code>/integrations/v1</code> dengan header <code>X-API-Key</code>. Kunci hanya berlaku untuk data asuransi ini. Dokumentasi
          lengkap di <a className="text-sky-800 hover:underline" href="http://localhost:8000/docs" target="_blank" rel="noreferrer">OpenAPI (localhost:8000/docs)</a>.
        </p>
      </div>
      {created?.api_key && (
        <div className="space-y-1 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          <div className="font-medium text-amber-900">Salin kunci ini sekarang. Kunci tidak akan ditampilkan lagi.</div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all rounded bg-white px-2 py-1 text-xs">{created.api_key}</code>
            <button type="button" className="btn-secondary py-1 text-xs" onClick={() => navigator.clipboard?.writeText(created.api_key ?? "")}>
              Salin
            </button>
          </div>
        </div>
      )}
      <form onSubmit={create} className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <input className="input w-auto flex-1" placeholder="Nama akun layanan, mis. Core claim system" value={name} onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn-primary" disabled={name.trim().length < 3 || chosen.length === 0}>Buat API key</button>
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {scopes.map((s) => (
            <label key={s.scope} className="flex items-center gap-1.5" title={s.description}>
              <input
                type="checkbox"
                checked={chosen.includes(s.scope)}
                onChange={() => setChosen((c) => (c.includes(s.scope) ? c.filter((x) => x !== s.scope) : [...c, s.scope].sort()))}
              />
              <code className="text-xs">{s.scope}</code>
              <span className="text-xs text-slate-500">{s.description}</span>
            </label>
          ))}
        </div>
      </form>
      {error && <p className="text-sm text-rose-700">{error}</p>}
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr>
            <th className="py-1 pr-2">Nama</th>
            <th className="py-1 pr-2">Prefix</th>
            <th className="py-1 pr-2">Cakupan</th>
            <th className="py-1 pr-2">Terakhir dipakai</th>
            <th className="py-1" />
          </tr>
        </thead>
        <tbody>
          {clients?.length === 0 && (
            <tr><td colSpan={5} className="py-2 text-slate-500">Belum ada akun layanan.</td></tr>
          )}
          {clients?.map((c) => (
            <tr key={c.id} className={`border-t ${c.is_active ? "" : "text-slate-400"}`}>
              <td className="py-1.5 pr-2">{c.name}</td>
              <td className="py-1.5 pr-2 font-mono text-xs">mab_{c.key_prefix}_…</td>
              <td className="py-1.5 pr-2 text-xs">{c.scopes.join(", ")}</td>
              <td className="py-1.5 pr-2 text-xs">{c.last_used_at ? waktu(c.last_used_at) : "-"}</td>
              <td className="py-1.5 text-right">
                {c.is_active ? (
                  <button type="button" className="text-xs text-rose-700 hover:underline" onClick={() => revoke(c)}>Cabut</button>
                ) : (
                  <span className="text-xs">dicabut {c.revoked_at ? waktu(c.revoked_at) : ""}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NewTenant({ onCreated }: { onCreated: (t: Tenant) => void }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  if (!open) return <button className="btn-secondary w-full" onClick={() => setOpen(true)}>+ Tenant baru</button>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      onCreated(await apiJson<Tenant>("/tenants", { method: "POST", body: JSON.stringify({ code, name }) }));
      setOpen(false);
      setCode("");
      setName("");
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <form onSubmit={submit} className="card space-y-2 text-sm">
      <input className="input" placeholder="Kode, mis. ASURANSI_X" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
      <input className="input" placeholder="Nama asuransi (rekaan)" value={name} onChange={(e) => setName(e.target.value)} />
      {error && <p className="text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" className="btn-primary">Buat</button>
        <button type="button" className="btn-secondary" onClick={() => setOpen(false)}>Batal</button>
      </div>
    </form>
  );
}

export default function TenantAdminPage() {
  const [tenants, setTenants] = useState<Tenant[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [ruleset, setRuleset] = useState<RulesetInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiJson<Tenant[]>("/tenants")
      .then((t) => {
        setTenants(t);
        setSelectedId((id) => id ?? t[0]?.insurer_id ?? null);
      })
      .catch((e) => setError(e.message));
    apiJson<RulesetInfo>("/admin/ruleset").then(setRuleset).catch(() => setRuleset(null));
  }, []);

  const selected = tenants?.find((t) => t.insurer_id === selectedId) ?? null;
  const replace = (t: Tenant) => setTenants((ts) => (ts ?? []).map((x) => (x.insurer_id === t.insurer_id ? t : x)));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">Tenant &amp; API key</h1>
        <p className="text-sm text-slate-500">
          Setiap asuransi (tenant) punya tampilan, ambang triase, aturan aktif, dan SLA sendiri. Setiap perubahan tercatat di log
          audit, dan versi pengaturan ikut tercatat di setiap rekomendasi. Data rekaan untuk demonstrasi.
        </p>
      </div>
      {error && <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</div>}
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <aside className="space-y-2">
          {tenants?.map((t) => (
            <button
              key={t.insurer_id}
              onClick={() => setSelectedId(t.insurer_id)}
              className={`card flex w-full items-center gap-3 text-left ${t.insurer_id === selectedId ? "ring-2 ring-sky-500" : ""}`}
            >
              {t.logo_data_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={t.logo_data_url} alt="" className="h-9 w-9 rounded object-contain" />
              ) : (
                <div className="flex h-9 w-9 items-center justify-center rounded bg-slate-100 text-xs text-slate-500">{t.code.slice(0, 2)}</div>
              )}
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{t.display_name ?? t.name}</div>
                <div className="text-xs text-slate-500">
                  {t.code} · {t.claim_count} klaim · {t.policy_count} polis · v{t.version}
                </div>
              </div>
            </button>
          ))}
          <NewTenant
            onCreated={(t) => {
              setTenants((ts) => [...(ts ?? []), t]);
              setSelectedId(t.insurer_id);
            }}
          />
        </aside>
        <div className="space-y-4">
          {selected && <SettingsForm tenant={selected} ruleset={ruleset} onSaved={replace} />}
          {selected && <ApiClients tenant={selected} />}
          {selected && <IntegrationLog tenant={selected} canResend />}
        </div>
      </div>
    </div>
  );
}
