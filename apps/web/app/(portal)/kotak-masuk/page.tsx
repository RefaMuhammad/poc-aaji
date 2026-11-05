"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { NotificationItem } from "@/lib/types";
import { NOTIFICATION_EVENT_LABEL, waktu } from "@/lib/format";

/** Kotak masuk: email notifikasi yang (selama demo) disimulasikan, tidak benar-benar dikirim. */
export default function InboxPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const load = useCallback(() => {
    apiJson<NotificationItem[]>("/notifications").then(setItems).catch(() => setItems([]));
  }, []);
  useEffect(load, [load]);

  const claimHref = (claimId: string) =>
    user?.role === "facility_officer" ? `/faskes/${claimId}` : user?.role === "member" ? `/peserta/${claimId}` : `/klaim/${claimId}`;

  const open = async (n: NotificationItem) => {
    setOpenId(openId === n.id ? null : n.id);
    if (!n.read_at) {
      await apiJson(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => null);
      load();
      window.dispatchEvent(new Event("mab:inbox"));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Kotak masuk</h1>
          <p className="text-sm text-slate-600">
            Salinan email notifikasi untuk {user?.email}. Selama demo, email <b>tidak benar-benar dikirim</b> (disimulasikan).
          </p>
        </div>
        <button className="btn-secondary" onClick={() => apiJson("/notifications/read-all", { method: "POST" }).then(() => { load(); window.dispatchEvent(new Event("mab:inbox")); })}>
          Tandai semua dibaca
        </button>
      </div>
      {items === null ? (
        <p className="text-sm text-slate-500">Memuat…</p>
      ) : items.length === 0 ? (
        <p className="card text-sm text-slate-500">Belum ada notifikasi.</p>
      ) : (
        <ul className="card divide-y p-0">
          {items.map((n) => (
            <li key={n.id} className={n.read_at ? "" : "bg-sky-50/60"}>
              <button className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left" onClick={() => open(n)}>
                <span className="flex items-center gap-2">
                  {!n.read_at && <span className="h-2 w-2 rounded-full bg-sky-600" />}
                  <span className={n.read_at ? "" : "font-medium"}>{n.subject}</span>
                </span>
                <span className="text-xs text-slate-500">
                  {NOTIFICATION_EVENT_LABEL[n.event] ?? n.event} · {waktu(n.created_at)}
                </span>
              </button>
              {openId === n.id && (
                <div className="border-t bg-white px-4 py-3 text-sm">
                  <p className="text-xs text-slate-500">Kepada: {n.email} · Pengiriman: {n.delivery === "SIMULATED" ? "disimulasikan" : n.delivery}</p>
                  <div className="mt-2 whitespace-pre-line text-slate-800">{n.body}</div>
                  {n.claim_id && (
                    <Link href={claimHref(n.claim_id)} className="btn-secondary mt-3 inline-block">Buka klaim</Link>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
