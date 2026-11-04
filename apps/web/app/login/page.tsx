"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiJson, saveSession } from "@/lib/api";
import type { User } from "@/lib/types";
import { homeFor } from "@/lib/format";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await apiJson<{ access_token: string; user: User }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      saveSession(r.access_token, r.user);
      router.replace(homeFor(r.user.role));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-[80vh] items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-lg font-semibold">MAB Indonesia</h1>
          <p className="text-sm text-slate-500">Telaah medis klaim rawat inap · POC</p>
        </div>
        <div>
          <label className="text-sm text-slate-600" htmlFor="email">Email</label>
          <input id="email" type="email" className="input mt-1" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
        </div>
        <div>
          <label className="text-sm text-slate-600" htmlFor="password">Kata sandi</label>
          <input id="password" type="password" className="input mt-1" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <p className="text-sm text-rose-700">{error}</p>}
        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "Masuk…" : "Masuk"}
        </button>
      </form>
    </main>
  );
}
