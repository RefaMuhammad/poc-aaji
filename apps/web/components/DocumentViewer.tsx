"use client";

import { useEffect, useState } from "react";
import { blobUrl } from "@/lib/api";
import type { DocumentInfo } from "@/lib/types";
import { DOC_TYPE_LABEL } from "@/lib/format";

export interface ViewerTarget {
  documentId: string;
  page: number;
  bbox?: number[] | null;
  quote?: string | null;
}

/** Pratinjau halaman dokumen dengan sorotan lokasi bukti (bbox dalam proporsi halaman). */
export function DocumentViewer({
  target,
  documents,
  onClose,
}: {
  target: ViewerTarget;
  documents: DocumentInfo[];
  onClose: () => void;
}) {
  const doc = documents.find((d) => d.id === target.documentId);
  const [page, setPage] = useState(target.page);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pages = doc?.page_count ?? 1;

  useEffect(() => setPage(target.page), [target]);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setSrc(null);
    setError(null);
    blobUrl(`/documents/${target.documentId}/pages/${page}.png?dpi=130`)
      .then((u) => {
        url = u;
        if (!cancelled) setSrc(u);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [target.documentId, page]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const highlight = page === target.page && target.bbox && target.bbox.length === 4 ? target.bbox : null;

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-slate-900/60 p-2 sm:p-6" onClick={onClose}>
      <div className="flex w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
          <div className="min-w-0">
            <div className="truncate font-medium">{doc?.filename ?? "Dokumen"}</div>
            <div className="text-xs text-slate-500">
              {doc ? DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type : ""} · halaman {page} dari {pages}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              ‹ Sebelumnya
            </button>
            <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Berikutnya ›
            </button>
            <button className="btn-secondary" onClick={onClose} aria-label="Tutup">
              ✕
            </button>
          </div>
        </div>
        {target.quote && (
          <div className="border-b bg-yellow-50 px-4 py-2 text-sm text-slate-700">
            Kutipan: <q className="italic">{target.quote}</q>
          </div>
        )}
        <div className="flex-1 overflow-auto bg-slate-100 p-4">
          {error && <div className="text-sm text-rose-700">{error}</div>}
          {!error && !src && <div className="text-sm text-slate-500">Memuat halaman…</div>}
          {src && (
            <div className="relative mx-auto w-fit shadow">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt={`Halaman ${page}`} className="block max-w-full" />
              {highlight && (
                <div
                  className="pointer-events-none absolute rounded-sm border-2 border-amber-500 bg-yellow-300/30"
                  style={{
                    left: `${highlight[0] * 100 - 0.5}%`,
                    top: `${highlight[1] * 100 - 0.4}%`,
                    width: `${(highlight[2] - highlight[0]) * 100 + 1}%`,
                    height: `${(highlight[3] - highlight[1]) * 100 + 0.8}%`,
                  }}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
