"use client";

import { useMemo, useState } from "react";
import type { FraudGraphEdge, FraudGraphNode } from "@/lib/types";
import { FRAUD_ENTITY_LABEL } from "@/lib/format";

const COLOR: Record<string, string> = {
  MEMBER: "#0ea5e9",
  HOSPITAL: "#6366f1",
  DOCTOR: "#14b8a6",
  BANK_ACCOUNT: "#f59e0b",
  ADDRESS: "#a855f7",
};

const W = 640;
const H = 380;

interface Pos { x: number; y: number }

/** Tata letak gaya-pegas sederhana yang deterministik (tanpa pustaka tambahan). */
function layout(nodes: FraudGraphNode[], edges: FraudGraphEdge[]): Record<string, Pos> {
  const pos: Record<string, Pos & { vx: number; vy: number }> = {};
  const n = nodes.length;
  nodes.forEach((node, i) => {
    const a = (2 * Math.PI * i) / Math.max(n, 1);
    const r = node.subject ? 0 : Math.min(W, H) * 0.35;
    pos[node.id] = { x: W / 2 + r * Math.cos(a), y: H / 2 + r * Math.sin(a), vx: 0, vy: 0 };
  });
  const k = Math.sqrt((W * H) / Math.max(n, 1)) * 0.55;
  for (let iter = 0; iter < 250; iter++) {
    const t = 1 - iter / 250;
    for (const a of nodes) {
      const pa = pos[a.id];
      for (const b of nodes) {
        if (a.id === b.id) continue;
        const pb = pos[b.id];
        const dx = pa.x - pb.x || 0.01;
        const dy = pa.y - pb.y || 0.01;
        const d2 = dx * dx + dy * dy;
        const f = (k * k) / d2;
        pa.vx += dx * f * 0.05;
        pa.vy += dy * f * 0.05;
      }
    }
    for (const e of edges) {
      const ps = pos[e.source];
      const pt = pos[e.target];
      if (!ps || !pt) continue;
      const dx = pt.x - ps.x;
      const dy = pt.y - ps.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (d - k) / d * 0.08;
      ps.vx += dx * f; ps.vy += dy * f;
      pt.vx -= dx * f; pt.vy -= dy * f;
    }
    for (const node of nodes) {
      const p = pos[node.id];
      if (node.subject && nodes.filter((x) => x.subject).length === 1) {
        p.x = W / 2; p.y = H / 2; p.vx = 0; p.vy = 0;
        continue;
      }
      const cap = 12 * t + 1;
      p.x += Math.max(-cap, Math.min(cap, p.vx));
      p.y += Math.max(-cap, Math.min(cap, p.vy));
      p.x = Math.max(70, Math.min(W - 70, p.x));
      p.y = Math.max(24, Math.min(H - 24, p.y));
      p.vx *= 0.5; p.vy *= 0.5;
    }
  }
  return Object.fromEntries(Object.entries(pos).map(([id, p]) => [id, { x: p.x, y: p.y }]));
}

function short(text: string, max = 26) {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

/** Graf relasi peserta - RS - dokter - rekening - alamat untuk satu sinyal fraud. */
export function FraudGraph({ nodes, edges }: { nodes: FraudGraphNode[]; edges: FraudGraphEdge[] }) {
  const [hover, setHover] = useState<string | null>(null);
  const shown = nodes.slice(0, 60);
  const ids = new Set(shown.map((n) => n.id));
  const shownEdges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const pos = useMemo(() => layout(shown, shownEdges), [nodes, edges]); // eslint-disable-line react-hooks/exhaustive-deps
  const types = Array.from(new Set(shown.map((n) => n.type)));
  const linked = (id: string) => hover === null || hover === id || shownEdges.some((e) => (e.source === hover && e.target === id) || (e.target === hover && e.source === id));

  if (shown.length === 0) return <p className="text-sm text-slate-500">Tidak ada relasi untuk ditampilkan.</p>;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full rounded border bg-white" role="img" aria-label="Graf relasi sinyal fraud">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
          </marker>
        </defs>
        {shownEdges.map((e, i) => {
          const s = pos[e.source];
          const t = pos[e.target];
          const on = hover === null || hover === e.source || hover === e.target;
          // dua arah (A->B dan B->A): lengkungkan supaya keduanya terlihat
          const twin = e.directed && shownEdges.some((o) => o.directed && o.source === e.target && o.target === e.source);
          const mx = (s.x + t.x) / 2 + (twin ? (t.y - s.y) * 0.15 : 0);
          const my = (s.y + t.y) / 2 - (twin ? (t.x - s.x) * 0.15 : 0);
          return (
            <g key={i} opacity={on ? 1 : 0.15}>
              <path d={`M ${s.x} ${s.y} Q ${mx} ${my} ${t.x} ${t.y}`} fill="none" stroke="#94a3b8"
                    strokeWidth={Math.min(1 + Math.log2(e.count || 1), 4)} markerEnd={e.directed ? "url(#arrow)" : undefined} />
              {(e.directed || hover !== null) && e.label && (
                <text x={mx} y={my - 4} textAnchor="middle" className="fill-slate-500" fontSize="10">{short(e.label, 30)}</text>
              )}
            </g>
          );
        })}
        {shown.map((n) => {
          const p = pos[n.id];
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={linked(n.id) ? 1 : 0.2}
               onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} className="cursor-default">
              <title>{`${FRAUD_ENTITY_LABEL[n.type] ?? n.type}: ${n.label}`}</title>
              <circle r={n.subject ? 13 : 9} fill={COLOR[n.type] ?? "#64748b"} stroke={n.subject ? "#be123c" : "#fff"} strokeWidth={n.subject ? 3 : 1.5} />
              <text y={n.subject ? 26 : 21} textAnchor="middle" fontSize="10" className="fill-slate-700">{short(n.label)}</text>
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-600">
        {types.map((t) => (
          <span key={t} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: COLOR[t] ?? "#64748b" }} />
            {FRAUD_ENTITY_LABEL[t] ?? t}
          </span>
        ))}
        <span className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-rose-700" /> entitas yang ditandai</span>
        {nodes.length > shown.length && <span>({nodes.length - shown.length} simpul lain tidak ditampilkan)</span>}
      </div>
    </div>
  );
}
