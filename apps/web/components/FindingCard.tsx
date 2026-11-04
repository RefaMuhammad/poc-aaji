"use client";

import Link from "next/link";
import { useState } from "react";
import type { DocumentInfo, FindingView } from "@/lib/types";
import { REASON_LABEL, SEVERITY_LABEL } from "@/lib/format";
import type { ViewerTarget } from "./DocumentViewer";

const SEVERITY_STYLE: Record<string, string> = {
  HIGH: "border-l-rose-500",
  MEDIUM: "border-l-amber-500",
  LOW: "border-l-sky-500",
  INFO: "border-l-slate-400",
};

export function FindingCard({
  finding,
  documents,
  onOpenEvidence,
}: {
  finding: FindingView;
  documents: DocumentInfo[];
  onOpenEvidence: (t: ViewerTarget) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? finding.evidence : finding.evidence.slice(0, 3);
  const hidden = finding.evidence.length - shown.length;
  const docName = (id: string | null) => documents.find((d) => d.id === id)?.filename ?? "dokumen";
  return (
    <div className={`rounded-md border border-l-4 bg-white p-4 ${SEVERITY_STYLE[finding.severity] ?? ""}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{finding.code}</span>
        <span className="font-medium text-slate-600">{REASON_LABEL[finding.code] ?? ""}</span>
        <span className="text-slate-400">·</span>
        <span className="text-slate-500">Tingkat: {SEVERITY_LABEL[finding.severity] ?? finding.severity}</span>
        {finding.rule_id && <span className="text-slate-400">· aturan {finding.rule_id}</span>}
      </div>
      <p className="mt-2 text-sm leading-relaxed">{finding.text}</p>
      {finding.evidence.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {shown.map((e, i) => (
            <li key={i}>
              {e.doc ? (
                <button
                  type="button"
                  onClick={() => onOpenEvidence({ documentId: e.doc!, page: e.page ?? 1, bbox: e.bbox, quote: e.quote })}
                  className="group w-full rounded border border-yellow-200 bg-yellow-50 px-3 py-2 text-left text-sm hover:border-amber-400"
                >
                  <q className="italic text-slate-800">{e.quote}</q>
                  <span className="mt-0.5 block text-xs text-slate-500 group-hover:text-amber-800">
                    {docName(e.doc)}, hal. {e.page ?? 1} · klik untuk lihat di dokumen
                  </span>
                </button>
              ) : (
                <div className="rounded border bg-slate-50 px-3 py-2 text-sm">
                  {e.quote ?? "Bukti dari riwayat klaim"}
                  {e.claim_id && (
                    <Link href={`/klaim/${e.claim_id}`} className="block text-xs text-sky-800 hover:underline">
                      Buka klaim terkait
                    </Link>
                  )}
                </div>
              )}
            </li>
          ))}
          {hidden > 0 && (
            <li>
              <button type="button" className="text-xs text-sky-800 hover:underline" onClick={() => setShowAll(true)}>
                Tampilkan {hidden} bukti lainnya
              </button>
            </li>
          )}
        </ul>
      )}
      {finding.guideline_refs.length > 0 && (
        <div className="mt-2 text-xs text-slate-500">Rujukan: {finding.guideline_refs.join("; ")}</div>
      )}
    </div>
  );
}
