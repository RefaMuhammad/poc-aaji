"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { FraudClaim } from "@/lib/types";
import { FRAUD_ENTITY_LABEL, FRAUD_LEVEL_STYLE, FRAUD_REVIEW_LABEL, FRAUD_REVIEW_STYLE, waktu } from "@/lib/format";

/** Analitik fraud satu klaim. Terpisah dari skor risiko klinis dan tidak memengaruhi rekomendasi. */
export function FraudClaimCard({ claimId }: { claimId: string }) {
  const [data, setData] = useState<FraudClaim | null>(null);
  useEffect(() => {
    apiJson<FraudClaim>(`/fraud/claims/${claimId}`).then(setData).catch(() => setData(null));
  }, [claimId]);
  if (!data) return null;
  return (
    <div className="card text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-medium">Analitik fraud</h2>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">Skor fraud</span>
          <span className="text-lg font-semibold tabular-nums">{data.score}</span>
          {data.level && <span className={`rounded px-1.5 py-0.5 text-xs ${FRAUD_LEVEL_STYLE[data.level] ?? ""}`}>{data.level}</span>}
        </div>
      </div>
      {data.signals.length === 0 ? (
        <p className="mt-1 text-slate-500">
          {data.run_at ? "Tidak ada pola fraud yang terkait klaim ini, RS-nya, dokternya, atau pesertanya." : "Analisis fraud belum pernah dijalankan untuk asuransi ini."}
        </p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {data.signals.map((s) => (
            <li key={s.id} className="rounded border px-2 py-1.5">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="font-mono">{s.rule_id}</span>
                <span>{FRAUD_ENTITY_LABEL[s.entity_type]}: {s.entity_label}</span>
                <span>· bobot {s.weight}</span>
                <span className={`ml-auto rounded px-1.5 py-0.5 ${FRAUD_REVIEW_STYLE[s.review?.status ?? "OPEN"]}`}>{FRAUD_REVIEW_LABEL[s.review?.status ?? "OPEN"]}</span>
              </div>
              <p className="mt-0.5">{s.message}</p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Skor fraud terpisah dari skor risiko klinis dan tidak mengubah rekomendasi atau keputusan klaim. Sinyal ditelaah investigator di{" "}
        <Link className="text-sky-800 hover:underline" href="/fraud">Fraud Monitor</Link>
        {data.run_at ? ` (analisis ${waktu(data.run_at)}, aturan ${data.ruleset_version})` : ""}.
        {!data.in_analysis && " Klaim ini belum masuk data analitik (belum selesai diproses)."}
      </p>
    </div>
  );
}
