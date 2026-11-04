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

/** Satu halaman dokumen sebagai gambar, dengan sorotan lokasi bukti (bbox dalam proporsi halaman). */
function PageImage({ target, page }: { target: ViewerTarget; page: number }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setSrc(null);
    setError(null);
    blobUrl(`/documents/${target.documentId}/pages/${page}.png?dpi=130`)
      .then((u) => {
        url = u;
        if (!cancelled) setSrc(u);
        else URL.revokeObjectURL(u);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [target.documentId, page]);

  const highlight = page === target.page && target.bbox && target.bbox.length === 4 ? target.bbox : null;

  if (error) return <div className="text-sm text-rose-700">{error}</div>;
  if (!src) return <div className="text-sm text-slate-500">Memuat halaman…</div>;
  return (
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
  );
}

/** Pratinjau dokumen: pilih dokumen, pindah halaman, dan sorot kutipan bukti. */
export function DocumentPane({
  target,
  documents,
  onSelect,
  onClose,
  className = "",
}: {
  target: ViewerTarget | null;
  documents: DocumentInfo[];
  onSelect: (t: ViewerTarget) => void;
  onClose?: () => void;
  className?: string;
}) {
  const current = target ?? (documents[0] ? { documentId: documents[0].id, page: 1 } : null);
  const doc = documents.find((d) => d.id === current?.documentId);
  const [page, setPage] = useState(current?.page ?? 1);
  const pages = doc?.page_count ?? 1;

  useEffect(() => setPage(current?.page ?? 1), [current?.documentId, current?.page, current?.quote]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`flex min-h-0 flex-col overflow-hidden bg-white ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <select
          className="input w-auto max-w-[16rem] py-1"
          value={current?.documentId ?? ""}
          onChange={(e) => onSelect({ documentId: e.target.value, page: 1 })}
          aria-label="Pilih dokumen"
        >
          {documents.map((d) => (
            <option key={d.id} value={d.id}>
              {DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type} · {d.filename}
            </option>
          ))}
        </select>
        <div className="flex items-center gap-1.5 text-sm">
          <button className="btn-secondary px-2" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Halaman sebelumnya">
            ‹
          </button>
          <span className="tabular-nums text-slate-600">
            {page} / {pages}
          </span>
          <button className="btn-secondary px-2" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} aria-label="Halaman berikutnya">
            ›
          </button>
          {onClose && (
            <button className="btn-secondary ml-1" onClick={onClose} aria-label="Tutup">
              ✕
            </button>
          )}
        </div>
      </div>
      {current?.quote && (
        <div className="border-b bg-yellow-50 px-3 py-1.5 text-sm text-slate-700">
          Kutipan: <q className="italic">{current.quote}</q>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto bg-slate-100 p-3">
        {current ? <PageImage target={current} page={page} /> : <div className="text-sm text-slate-500">Tidak ada dokumen.</div>}
      </div>
    </div>
  );
}

/** Pratinjau dalam jendela modal (portal asuransi). */
export function DocumentViewer({
  target,
  documents,
  onClose,
}: {
  target: ViewerTarget;
  documents: DocumentInfo[];
  onClose: () => void;
}) {
  const [current, setCurrent] = useState<ViewerTarget>(target);
  useEffect(() => setCurrent(target), [target]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-slate-900/60 p-2 sm:p-6" onClick={onClose}>
      <div className="flex w-full max-w-4xl flex-col overflow-hidden rounded-lg shadow-xl" onClick={(e) => e.stopPropagation()}>
        <DocumentPane target={current} documents={documents} onSelect={setCurrent} onClose={onClose} className="flex-1" />
      </div>
    </div>
  );
}
