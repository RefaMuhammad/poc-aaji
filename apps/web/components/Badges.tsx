import type { ClaimStatus, Triage } from "@/lib/types";
import { IN_PROGRESS, STATUS_LABEL } from "@/lib/format";

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
