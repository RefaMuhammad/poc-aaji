import type { ClaimStatus, QueueItem, Triage } from "@/lib/types";
import { IN_PROGRESS, SLA_LABEL, STATUS_LABEL, slaRemaining, waktu } from "@/lib/format";

const TRIAGE_STYLE: Record<Triage, string> = {
  GREEN: "bg-emerald-100 text-emerald-800 ring-emerald-600/30",
  YELLOW: "bg-amber-100 text-amber-900 ring-amber-600/30",
  RED: "bg-rose-100 text-rose-800 ring-rose-600/30",
};

const TRIAGE_LABEL: Record<Triage, string> = { GREEN: "Hijau", YELLOW: "Kuning", RED: "Merah" };

export function TriageBadge({ triage, score }: { triage: Triage | null; score?: number | null }) {
  if (!triage) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${TRIAGE_STYLE[triage]}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {TRIAGE_LABEL[triage]}
      {score !== undefined && score !== null && <span className="font-normal opacity-75">· {score}</span>}
    </span>
  );
}

export function StatusBadge({ status }: { status: ClaimStatus }) {
  const busy = IN_PROGRESS.includes(status);
  const style =
    status === "FAILED"
      ? "bg-rose-50 text-rose-700"
      : status === "COMPLETED"
        ? "bg-slate-100 text-slate-700"
        : status === "AWAITING_DECISION"
          ? "bg-sky-50 text-sky-800"
          : status === "PENDING_DOCUMENTS"
            ? "bg-amber-50 text-amber-800"
          : status === "AWAITING_DOCTOR"
            ? "bg-violet-50 text-violet-800"
            : "bg-slate-50 text-slate-600";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${style}`}>
      {busy && <span className="h-2 w-2 animate-pulse rounded-full bg-sky-500" />}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

const SLA_STYLE: Record<string, string> = {
  ON_TRACK: "bg-emerald-50 text-emerald-800",
  AT_RISK: "bg-amber-100 text-amber-900",
  OVERDUE: "bg-rose-100 text-rose-800",
};

/** Indikator SLA antrean dokter: status + sisa waktu (menunggu), atau tepat/terlambat (selesai). */
export function SlaBadge({ item }: { item: Pick<QueueItem, "sla_state" | "sla_due_at" | "sla_hours" | "sla_met"> }) {
  const title = item.sla_due_at ? `Batas SLA ${waktu(item.sla_due_at)} (${item.sla_hours} jam)` : undefined;
  if (item.sla_met !== null && item.sla_met !== undefined) {
    return (
      <span title={title} className={`rounded px-2 py-0.5 text-xs ${item.sla_met ? SLA_STYLE.ON_TRACK : SLA_STYLE.OVERDUE}`}>
        {item.sla_met ? "Tepat waktu" : "Terlambat"}
      </span>
    );
  }
  if (!item.sla_state) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span title={title} className={`inline-flex flex-col rounded px-2 py-0.5 text-xs ${SLA_STYLE[item.sla_state]}`}>
      <span className="font-medium">{SLA_LABEL[item.sla_state]}</span>
      <span className="opacity-80">{slaRemaining(item.sla_due_at)}</span>
    </span>
  );
}
