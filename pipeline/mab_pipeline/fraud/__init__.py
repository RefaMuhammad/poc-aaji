"""Fraud analytics (U3): pola di banyak klaim, terpisah dari penilaian klinis per klaim.

Modul ini murni analisis (tidak membaca database). Masukannya daftar `ClaimRecord`
(riwayat klaim impor + klaim yang sudah diproses platform), keluarannya `FraudReport`
berisi SINYAL beserta bukti:
  - statistik sejawat per RS dan per dokter (lama rawat, biaya per hari, frekuensi lab;
    indeks terhadap median diagnosis yang sama dan z-score dibanding sejawat)
  - graf relasi peserta - RS - dokter - rekening - alamat (networkx): rekening bersama,
    alamat bersama, rujukan berputar
  - urutan klaim per peserta: klaim beruntun dan rawat inap tumpang tindih
Aturan (ambang, bobot, pesan) ada di YAML terpisah: rules/aturan_fraud_demo.yaml.

Sinyal fraud adalah bahan telaah investigator. Ia tidak pernah menolak klaim, tidak
mengubah status klaim, dan tidak ikut skor risiko klinis.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from mab_pipeline.rules.engine import (CompiledExpression, ExpressionError, MissingData, compile_expression, evaluate,
                                       message_fields, render_message)
from mab_pipeline.rules.loader import RuleValidationError
from mab_pipeline.schemas import Severity

# kelompok field di YAML -> jenis entitas sinyal
ENTITY_OF_GROUP: dict[str, str] = {
    "rs": "HOSPITAL",
    "dokter": "DOCTOR",
    "peserta": "MEMBER",
    "rekening": "BANK_ACCOUNT",
    "alamat": "ADDRESS",
    "rujukan": "REFERRAL_LOOP",
}
FRAUD_GROUPS: tuple[str, ...] = tuple(ENTITY_OF_GROUP)
DEFAULT_PARAMS: dict[str, Any] = {
    "min_klaim_sejawat": 8,
    "jendela_klaim_beruntun_hari": 180,
    "min_rujukan_per_arah": 3,
    "maks_klaim_bukti": 10,
    "tingkat": {"TINGGI": 50, "SEDANG": 25, "RENDAH": 1},
}


# ----------------------------------------------------------------------------- aturan


@dataclass(frozen=True)
class FraudRule:
    id: str
    name: str
    group: str
    condition: CompiledExpression
    reason_code: str
    severity: Severity
    weight: int
    message: str

    @property
    def entity_type(self) -> str:
        return ENTITY_OF_GROUP[self.group]


@dataclass(frozen=True)
class FraudRuleSet:
    version: str
    params: dict[str, Any]
    data_dictionary: dict[str, dict[str, Any]]
    reason_codes: dict[str, str]
    rules: tuple[FraudRule, ...]

    def level(self, score: int) -> str | None:
        """Skor fraud -> tingkat (TINGGI/SEDANG/RENDAH), None bila 0."""
        for name, minimum in sorted(self.params["tingkat"].items(), key=lambda kv: -kv[1]):
            if score >= minimum:
                return name
        return None


def load_fraud_rules(path: str | Path) -> FraudRuleSet:
    with open(path, encoding="utf-8") as fh:
        return parse_fraud_rules(yaml.safe_load(fh))


def parse_fraud_rules(doc: Any) -> FraudRuleSet:
    errors: list[str] = []
    if not isinstance(doc, dict):
        raise RuleValidationError(["isi file bukan mapping YAML"])
    for key in ("version", "kamus_data", "kode_alasan", "aturan"):
        if key not in doc:
            errors.append(f"bagian '{key}' tidak ada")
    if errors:
        raise RuleValidationError(errors)
    params = {**DEFAULT_PARAMS, **(doc.get("parameter") or {})}
    kamus = doc["kamus_data"] or {}
    codes = doc["kode_alasan"] or {}
    for path in kamus:
        if path.split(".", 1)[0] not in FRAUD_GROUPS:
            errors.append(f"kamus_data: field '{path}' harus diawali salah satu dari: {', '.join(FRAUD_GROUPS)}")
    seen: set[str] = set()
    rules: list[FraudRule] = []
    for raw in doc["aturan"] or []:
        if not isinstance(raw, dict):
            errors.append("aturan: setiap aturan harus berupa mapping")
            continue
        rid = str(raw.get("id", "<tanpa id>"))
        missing = [k for k in ("id", "nama", "entitas", "kondisi", "kode_alasan", "keparahan", "bobot", "pesan") if k not in raw]
        if missing:
            errors.append(f"aturan {rid}: kunci wajib tidak ada: {', '.join(missing)}")
            continue
        if rid in seen:
            errors.append(f"aturan {rid}: id aturan duplikat")
        seen.add(rid)
        group = str(raw["entitas"])
        if group not in FRAUD_GROUPS:
            errors.append(f"aturan {rid}: entitas '{group}' tidak dikenal (pilihan: {', '.join(FRAUD_GROUPS)})")
            continue
        try:
            cond = compile_expression(raw["kondisi"], (group,))
        except ExpressionError as exc:
            errors.append(f"aturan {rid}: kondisi tidak valid: {exc}")
            continue
        for f in list(cond.fields) + message_fields(str(raw["pesan"])):
            if f not in kamus:
                errors.append(f"aturan {rid}: field '{f}' tidak ada di kamus data")
            elif not f.startswith(group + "."):
                errors.append(f"aturan {rid}: field '{f}' bukan milik entitas '{group}'")
        if raw["kode_alasan"] not in codes:
            errors.append(f"aturan {rid}: kode_alasan '{raw['kode_alasan']}' tidak terdaftar")
        try:
            sev = Severity(raw["keparahan"])
        except ValueError:
            errors.append(f"aturan {rid}: keparahan '{raw['keparahan']}' tidak dikenal")
            continue
        weight = raw["bobot"]
        if not isinstance(weight, int) or not 0 <= weight <= 100:
            errors.append(f"aturan {rid}: bobot harus bilangan bulat 0-100")
            continue
        rules.append(FraudRule(rid, str(raw["nama"]), group, cond, raw["kode_alasan"], sev, weight,
                               " ".join(str(raw["pesan"]).split())))
    if errors:
        raise RuleValidationError(errors)
    return FraudRuleSet(str(doc["version"]), params, kamus, codes, tuple(rules))


# ----------------------------------------------------------------------------- data


@dataclass(frozen=True)
class ClaimRecord:
    """Satu klaim dalam data analitik fraud (dari riwayat impor atau klaim platform)."""

    claim_number: str
    member_id: str
    hospital: str
    admission_date: dt.date
    discharge_date: dt.date
    billed_amount: int
    icd10: str | None = None
    doctor: str | None = None
    lab_panels: int | None = None
    member_name: str | None = None
    address: str | None = None
    bank_account: str | None = None
    referral_from: str | None = None
    source: str = "HISTORY"

    @property
    def los_days(self) -> int:
        return max((self.discharge_date - self.admission_date).days, 1)

    @property
    def cost_per_day(self) -> float:
        return self.billed_amount / self.los_days

    @property
    def labs_per_day(self) -> float | None:
        return None if self.lab_panels is None else self.lab_panels / self.los_days

    @property
    def dx_group(self) -> str:
        return (self.icd10 or "?")[:3].upper()

    @property
    def surname(self) -> str | None:
        parts = (self.member_name or "").split()
        return parts[-1].lower() if len(parts) > 1 else None


def normalize_address(text: str | None) -> str | None:
    if not text:
        return None
    t = re.sub(r"[^\w\s]", " ", text.lower())
    t = re.sub(r"\b(jalan|jln)\b", "jl", t)
    t = re.sub(r"\b(nomor|no)\b", "no", t)
    return " ".join(t.split()) or None


def loop_key(hospitals: list[str]) -> str:
    i = hospitals.index(min(hospitals))
    ordered = hospitals[i:] + hospitals[:i]
    return " -> ".join(ordered + [ordered[0]])


@dataclass
class Signal:
    rule_id: str
    reason_code: str
    severity: str
    weight: int
    entity_type: str
    entity_key: str
    entity_label: str
    message: str
    claim_numbers: list[str]
    evidence: dict[str, Any]


@dataclass
class EntityScore:
    entity_type: str
    entity_key: str
    entity_label: str
    score: int
    level: str | None
    rule_ids: list[str]
    claims: int


@dataclass
class FraudReport:
    ruleset_version: str
    record_count: int
    signals: list[Signal]
    entities: list[EntityScore]
    skipped: list[dict] = field(default_factory=list)   # aturan yang dilewati karena data kosong

    def claim_score(self, claim_number: str) -> int:
        return min(100, sum(s.weight for s in self.signals if claim_number in s.claim_numbers))


class _Facts:
    def __init__(self, values: dict[str, Any]):
        self.values = values

    def get_field(self, path: str) -> Any:
        return self.values.get(path)


def _display(values: dict[str, Any]) -> _Facts:
    """Nilai untuk pesan: pecahan ditulis dengan koma desimal (7,3 hari)."""
    def fmt(v: Any) -> Any:
        if isinstance(v, float) and not v.is_integer():
            return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return v
    return _Facts({k: fmt(v) for k, v in values.items()})


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def _claim_row(c: ClaimRecord, value: Any = None) -> dict:
    return {"claim_number": c.claim_number, "member_id": c.member_id, "hospital": c.hospital, "doctor": c.doctor,
            "icd10": c.icd10, "admission_date": c.admission_date.isoformat(), "discharge_date": c.discharge_date.isoformat(),
            "los_days": c.los_days, "billed_amount": c.billed_amount, "lab_panels": c.lab_panels,
            "referral_from": c.referral_from, "value": value}


# ----------------------------------------------------------------------------- statistik sejawat

_METRICS = {  # nama -> (fungsi nilai klaim, label, satuan)
    "los": (lambda c: float(c.los_days), "Lama rawat", "hari"),
    "cost": (lambda c: c.cost_per_day, "Biaya per hari rawat", "rupiah"),
    "lab": (lambda c: c.labs_per_day, "Pemeriksaan lab per hari rawat", "kali"),
}
_MEAN_FIELD = {"los": "los_mean", "cost": "cost_day_mean", "lab": "lab_day_mean"}


def _dx_medians(records: list[ClaimRecord]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for metric, (fn, _l, _u) in _METRICS.items():
        by_dx: dict[str, list[float]] = defaultdict(list)
        for c in records:
            v = fn(c)
            if v is not None:
                by_dx[c.dx_group].append(v)
        out[metric] = {dx: statistics.median(vs) for dx, vs in by_dx.items() if vs}
    return out


def _peer_profiles(records: list[ClaimRecord], key_fn, medians, min_claims: int) -> dict[str, dict[str, Any]]:
    """Profil per entitas (RS / dokter): rata-rata, indeks, dan z-score terhadap sejawat."""
    groups: dict[str, list[ClaimRecord]] = defaultdict(list)
    for c in records:
        k = key_fn(c)
        if k:
            groups[k].append(c)
    prof: dict[str, dict[str, Any]] = {}
    for k, claims in groups.items():
        p: dict[str, Any] = {"claims": len(claims), "_claims": claims}
        for metric, (fn, _l, _u) in _METRICS.items():
            vals = [(fn(c), medians[metric].get(c.dx_group)) for c in claims]
            vals = [(v, m) for v, m in vals if v is not None and m]
            p[f"_{metric}_sum"] = sum(v for v, _ in vals)
            p[f"_{metric}_n"] = len(vals)
            p[_MEAN_FIELD[metric]] = (p[f"_{metric}_sum"] / len(vals)) if vals else None
            p[f"{metric}_index"] = statistics.fmean(v / m for v, m in vals) if vals else None
        prof[k] = p
    eligible = [k for k, p in prof.items() if p["claims"] >= min_claims]
    for k, p in prof.items():
        for metric in _METRICS:
            others = [prof[o] for o in eligible if o != k and prof[o][f"{metric}_index"] is not None]
            idx = p[f"{metric}_index"]
            peer_n = sum(o[f"_{metric}_n"] for o in others)
            p[f"peer_{_MEAN_FIELD[metric]}"] = (sum(o[f"_{metric}_sum"] for o in others) / peer_n) if peer_n else None
            if idx is None or len(others) < 3:
                p[f"{metric}_z"] = None
                continue
            ref = [o[f"{metric}_index"] for o in others]
            sd = max(statistics.pstdev(ref), 0.03)   # lantai agar sejawat yang sangat seragam tidak membuat z meledak
            p[f"{metric}_z"] = (idx - statistics.fmean(ref)) / sd
    return prof


def _profile_values(group: str, name: str, p: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    v: dict[str, Any] = {f"{group}.name": name, f"{group}.claims": p["claims"], **extra}
    for metric in _METRICS:
        mean_f = _MEAN_FIELD[metric]
        nd = 0 if metric == "cost" else 1
        mean, peer = p[mean_f], p[f"peer_{mean_f}"]
        v[f"{group}.{mean_f}"] = (int(round(mean)) if nd == 0 else _r(mean, 1)) if mean is not None else None
        v[f"{group}.peer_{mean_f}"] = (int(round(peer)) if nd == 0 else _r(peer, 1)) if peer is not None else None
        v[f"{group}.{metric}_index"] = _r(p[f"{metric}_index"])
        v[f"{group}.{metric}_z"] = _r(p[f"{metric}_z"], 1)
    return v


# ----------------------------------------------------------------------------- analisis


class _Builder:
    def __init__(self, records: list[ClaimRecord], ruleset: FraudRuleSet):
        self.records = records
        self.rs = ruleset
        self.params = ruleset.params
        self.signals: list[Signal] = []
        self.skipped: list[dict] = []
        self.by_number = {c.claim_number: c for c in records}

    def run_rules(self, group: str, key: str, label: str, values: dict[str, Any], claims: list[str],
                  evidence_fn) -> None:
        facts = _Facts(values)
        for rule in self.rs.rules:
            if rule.group != group:
                continue
            try:
                hit = evaluate(rule.condition, facts)
            except MissingData:
                continue
            if not hit:
                continue
            evidence = evidence_fn(rule)
            evidence["metrics"] = {k.split(".", 1)[1]: v for k, v in values.items()}
            self.signals.append(Signal(
                rule_id=rule.id, reason_code=rule.reason_code, severity=rule.severity.value, weight=rule.weight,
                entity_type=rule.entity_type, entity_key=key, entity_label=label,
                message=render_message(rule.message, _display(values)), claim_numbers=sorted(set(claims)), evidence=evidence,
            ))

    # ---- RS dan dokter
    def peers(self) -> None:
        medians = _dx_medians(self.records)
        min_claims = int(self.params["min_klaim_sejawat"])
        limit = int(self.params["maks_klaim_bukti"])
        hospitals = _peer_profiles(self.records, lambda c: c.hospital, medians, min_claims)
        doctors = _peer_profiles(self.records, lambda c: c.doctor, medians, min_claims)

        def comparison(p: dict[str, Any], group: str, metric: str) -> list[dict]:
            fn, label, unit = _METRICS[metric]
            mean_f = _MEAN_FIELD[metric]
            return [{"label": label, "unit": unit, "value": _r(p[mean_f]), "peer": _r(p[f"peer_{mean_f}"]),
                     "index": _r(p[f"{metric}_index"]), "z": _r(p[f"{metric}_z"], 1),
                     "peer_group": "RS lain" if group == "rs" else "dokter lain"}]

        def evidence(p, group, rule: FraudRule, entity_name: str) -> dict:
            metric = {"LOS_OUTLIER": "los", "COST_OUTLIER": "cost", "LAB_OVERUSE": "lab"}.get(rule.reason_code, "los")
            fn = _METRICS[metric][0]
            ranked = sorted(p["_claims"], key=lambda c: -((fn(c) or 0) / (medians[metric].get(c.dx_group) or 1)))
            peers_tbl = hospitals if group == "rs" else doctors
            distribution = sorted(
                ({"name": k, "claims": q["claims"], "index": _r(q[f"{metric}_index"]), "z": _r(q[f"{metric}_z"], 1),
                  "is_subject": k == entity_name}
                 for k, q in peers_tbl.items() if q["claims"] >= min_claims and q[f"{metric}_index"] is not None),
                key=lambda d: -(d["index"] or 0))
            return {
                "kind": "peer",
                "metric": metric,
                "comparison": comparison(p, group, metric),
                "claims": [_claim_row(c, _r(fn(c))) for c in ranked[:limit]],
                "peer_distribution": distribution,
                "graph": self.provider_graph(group, entity_name, p["_claims"]),
            }

        for name, p in sorted(hospitals.items()):
            vals = _profile_values("rs", name, p, {})
            self.run_rules("rs", name, name, vals, [c.claim_number for c in p["_claims"]],
                           lambda rule, p=p, name=name: evidence(p, "rs", rule, name))
        for name, p in sorted(doctors.items()):
            home = Counter(c.hospital for c in p["_claims"]).most_common(1)[0][0]
            vals = _profile_values("dokter", name, p, {"dokter.hospital": home})
            self.run_rules("dokter", name, f"{name} ({home})", vals, [c.claim_number for c in p["_claims"]],
                           lambda rule, p=p, name=name: evidence(p, "dokter", rule, name))

    def provider_graph(self, group: str, name: str, claims: list[ClaimRecord]) -> dict:
        """Graf kecil RS - dokter (dan rujukan) untuk sinyal statistik."""
        nodes: dict[str, dict] = {}
        edges: Counter = Counter()
        for c in claims:
            h, d = f"hospital:{c.hospital}", f"doctor:{c.doctor}" if c.doctor else None
            nodes[h] = {"id": h, "label": c.hospital, "type": "HOSPITAL", "subject": group == "rs" and c.hospital == name}
            if d:
                nodes[d] = {"id": d, "label": c.doctor, "type": "DOCTOR", "subject": group == "dokter" and c.doctor == name}
                edges[(d, h, "merawat di")] += 1
        return {"nodes": list(nodes.values()),
                "edges": [{"source": s, "target": t, "label": f"{lbl} ({n} klaim)", "count": n, "directed": False}
                          for (s, t, lbl), n in edges.items()]}

    # ---- relasi: rekening, alamat, rujukan
    def relations(self) -> None:
        import networkx as nx

        g = nx.Graph()
        members: dict[str, list[ClaimRecord]] = defaultdict(list)
        for c in self.records:
            members[c.member_id].append(c)
        for mid, claims in members.items():
            m = f"member:{mid}"
            g.add_node(m, type="MEMBER", label=f"{mid} {claims[0].member_name or ''}".strip())
            for c in claims:
                h = f"hospital:{c.hospital}"
                g.add_node(h, type="HOSPITAL", label=c.hospital)
                if g.has_edge(m, h):
                    g[m][h]["claims"].append(c.claim_number)
                else:
                    g.add_edge(m, h, rel="dirawat di", claims=[c.claim_number])
                if c.bank_account:
                    a = f"account:{c.bank_account}"
                    g.add_node(a, type="BANK_ACCOUNT", label=c.bank_account)
                    g.add_edge(m, a, rel="rekening")
                addr = normalize_address(c.address)
                if addr:
                    ad = f"address:{addr}"
                    g.add_node(ad, type="ADDRESS", label=c.address)
                    g.add_edge(m, ad, rel="alamat")
        self.graph = g

        for node, data in list(g.nodes(data=True)):
            if data["type"] not in ("BANK_ACCOUNT", "ADDRESS"):
                continue
            mids = [n.split(":", 1)[1] for n in g.neighbors(node) if n.startswith("member:")]
            claims = [c for mid in mids for c in members[mid]]
            surnames = {c.surname for c in claims if c.surname}
            if data["type"] == "BANK_ACCOUNT":
                group, key = "rekening", data["label"]
                addresses = {normalize_address(c.address) for c in claims if c.address}
                values = {"rekening.id": key, "rekening.members": len(mids), "rekening.surnames": len(surnames),
                          "rekening.addresses": len(addresses), "rekening.claims": len(claims)}
            else:
                group, key = "alamat", node.split(":", 1)[1]
                top = Counter(c.hospital for c in claims).most_common(1)
                values = {"alamat.text": data["label"], "alamat.members": len(mids), "alamat.surnames": len(surnames),
                          "alamat.claims": len(claims), "alamat.top_hospital": top[0][0] if top else None,
                          "alamat.top_hospital_share": _r(top[0][1] / len(claims)) if top else None}
            self.run_rules(group, key, data["label"], values, [c.claim_number for c in claims],
                           lambda rule, node=node, claims=claims: self.relation_evidence(node, claims))

        self.referrals()

    def relation_evidence(self, center: str, claims: list[ClaimRecord]) -> dict:
        g = self.graph
        keep = {center}
        for m in g.neighbors(center):
            keep.add(m)
            for n in g.neighbors(m):     # RS, rekening, dan alamat lain milik peserta yang sama
                keep.add(n)
        sub = g.subgraph(keep)
        limit = int(self.params["maks_klaim_bukti"])
        relations = [{"from": g.nodes[m]["label"], "to": g.nodes[center]["label"], "label": g[m][center]["rel"]}
                     for m in g.neighbors(center)]
        return {"kind": "relation", "relations": relations,
                "claims": [_claim_row(c) for c in sorted(claims, key=lambda c: c.admission_date)[:limit * 2]],
                "graph": _graph_json(sub, center)}

    def referrals(self) -> None:
        import networkx as nx

        counts: Counter = Counter()
        claims_on: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
        for c in self.records:
            if c.referral_from and c.referral_from != c.hospital:
                counts[(c.referral_from, c.hospital)] += 1
                claims_on[(c.referral_from, c.hospital)].append(c)
        minimum = int(self.params["min_rujukan_per_arah"])
        dg = nx.DiGraph()
        for (src, dst), n in counts.items():
            if n >= minimum:
                dg.add_edge(src, dst, count=n)
        seen: set[str] = set()
        for cycle in nx.simple_cycles(dg):
            if len(cycle) < 2:
                continue
            key = loop_key(list(cycle))
            if key in seen:
                continue
            seen.add(key)
            path_edges = list(zip(cycle, cycle[1:] + cycle[:1]))
            claims = [c for e in path_edges for c in claims_on[e]]
            values = {"rujukan.path": key, "rujukan.length": len(cycle), "rujukan.claims": len(claims),
                      "rujukan.min_edge": min(counts[e] for e in path_edges)}

            def ev(rule, path_edges=path_edges, claims=claims, cycle=cycle):
                nodes = [{"id": f"hospital:{h}", "label": h, "type": "HOSPITAL", "subject": True} for h in cycle]
                edges = [{"source": f"hospital:{s}", "target": f"hospital:{t}", "label": f"merujuk {counts[(s, t)]}x",
                          "count": counts[(s, t)], "directed": True} for s, t in path_edges]
                return {"kind": "relation",
                        "relations": [{"from": s, "to": t, "label": f"merujuk {counts[(s, t)]} pasien"} for s, t in path_edges],
                        "claims": [_claim_row(c) for c in sorted(claims, key=lambda c: c.admission_date)],
                        "graph": {"nodes": nodes, "edges": edges}}

            self.run_rules("rujukan", key, key, values, [c.claim_number for c in claims], ev)

    # ---- peserta: klaim beruntun dan tumpang tindih
    def members(self) -> None:
        window = int(self.params["jendela_klaim_beruntun_hari"])
        by_member: dict[str, list[ClaimRecord]] = defaultdict(list)
        for c in self.records:
            by_member[c.member_id].append(c)
        for mid, claims in by_member.items():
            if len(claims) < 2:
                continue
            claims = sorted(claims, key=lambda c: (c.admission_date, c.claim_number))
            best = max(sum(1 for o in claims if c.admission_date <= o.admission_date < c.admission_date + dt.timedelta(days=window))
                       for c in claims)
            gaps = [(b.admission_date - a.discharge_date).days for a, b in zip(claims, claims[1:])]
            overlaps = [(a, b) for i, a in enumerate(claims) for b in claims[i + 1:]
                        if b.admission_date < a.discharge_date and a.admission_date < b.discharge_date]
            values = {"peserta.id": mid, "peserta.claims": len(claims), "peserta.claims_in_window": best,
                      "peserta.window_days": window, "peserta.min_gap_days": min(gaps),
                      "peserta.overlaps": len(overlaps), "peserta.hospitals": len({c.hospital for c in claims})}
            label = f"{mid} {claims[0].member_name or ''}".strip()

            def ev(rule, claims=claims, overlaps=overlaps, mid=mid):
                m = f"member:{mid}"
                nodes = {m: {"id": m, "label": mid, "type": "MEMBER", "subject": True}}
                edges = []
                for c in claims:
                    h = f"hospital:{c.hospital}"
                    nodes[h] = {"id": h, "label": c.hospital, "type": "HOSPITAL", "subject": False}
                    edges.append({"source": m, "target": h, "directed": False, "count": 1,
                                  "label": f"{c.admission_date:%d/%m} - {c.discharge_date:%d/%m}"})
                if rule.reason_code == "OVERLAPPING_STAYS":
                    rel = [{"from": a.claim_number, "to": b.claim_number,
                            "label": f"tumpang tindih: {a.hospital} {a.admission_date}..{a.discharge_date} dan "
                                     f"{b.hospital} {b.admission_date}..{b.discharge_date}"} for a, b in overlaps]
                else:   # klaim beruntun: jarak pulang -> masuk berikutnya
                    rel = [{"from": a.claim_number, "to": b.claim_number,
                            "label": f"pulang {a.discharge_date} dari {a.hospital}, masuk lagi {b.admission_date} "
                                     f"di {b.hospital} ({(b.admission_date - a.discharge_date).days} hari)"}
                           for a, b in zip(claims, claims[1:])]
                return {"kind": "timeline", "relations": rel, "claims": [_claim_row(c) for c in claims],
                        "graph": {"nodes": list(nodes.values()), "edges": edges}}

            involved = [c.claim_number for c in claims]
            self.run_rules("peserta", mid, label, values, involved, ev)


def _graph_json(g, center: str) -> dict:
    return {
        "nodes": [{"id": n, "label": d.get("label", n), "type": d.get("type"), "subject": n == center}
                  for n, d in g.nodes(data=True)],
        "edges": [{"source": s, "target": t, "label": d.get("rel", ""), "count": len(d.get("claims", [])) or 1,
                   "directed": False} for s, t, d in g.edges(data=True)],
    }


def analyze(records: Iterable[ClaimRecord], ruleset: FraudRuleSet) -> FraudReport:
    """Jalankan seluruh analisis fraud atas data klaim. Deterministik untuk masukan yang sama."""
    recs = sorted(records, key=lambda c: c.claim_number)
    b = _Builder(recs, ruleset)
    if recs:
        b.peers()
        b.relations()
        b.members()
    sev_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
    b.signals.sort(key=lambda s: (sev_rank.get(s.severity, 9), -s.weight, s.rule_id, s.entity_key))

    agg: dict[tuple[str, str], EntityScore] = {}
    for s in b.signals:
        e = agg.setdefault((s.entity_type, s.entity_key),
                           EntityScore(s.entity_type, s.entity_key, s.entity_label, 0, None, [], len(s.claim_numbers)))
        e.score = min(100, e.score + s.weight)
        e.rule_ids.append(s.rule_id)
        e.claims = max(e.claims, len(s.claim_numbers))
    for e in agg.values():
        e.level = ruleset.level(e.score)
    entities = sorted(agg.values(), key=lambda e: (-e.score, e.entity_type, e.entity_key))
    return FraudReport(ruleset.version, len(recs), b.signals, entities, b.skipped)


# ----------------------------------------------------------------------------- impor CSV

HISTORY_COLUMNS = ["nomor_klaim", "id_peserta", "nama_peserta", "alamat_peserta", "rekening_bank", "rumah_sakit", "dokter",
                   "rujukan_dari", "icd10", "tanggal_masuk", "tanggal_keluar", "total_tagihan", "jumlah_pemeriksaan_lab"]
REQUIRED_HISTORY_COLUMNS = ("nomor_klaim", "id_peserta", "rumah_sakit", "tanggal_masuk", "tanggal_keluar", "total_tagihan")


class RowError(ValueError):
    pass


def _opt(row: dict, key: str) -> str | None:
    v = row.get(key)
    v = str(v).strip() if v is not None else ""
    return v or None


def record_from_row(row: dict) -> ClaimRecord:
    """Satu baris riwayat_klaim.csv -> ClaimRecord. Melempar RowError dengan pesan berbahasa Indonesia."""
    missing = [k for k in REQUIRED_HISTORY_COLUMNS if not _opt(row, k)]
    if missing:
        raise RowError(f"kolom wajib kosong: {', '.join(missing)}")
    try:
        adm = dt.date.fromisoformat(_opt(row, "tanggal_masuk"))
        dis = dt.date.fromisoformat(_opt(row, "tanggal_keluar"))
    except ValueError as exc:
        raise RowError("tanggal harus berformat YYYY-MM-DD") from exc
    if dis < adm:
        raise RowError("tanggal_keluar sebelum tanggal_masuk")
    try:
        billed = int(float(_opt(row, "total_tagihan").replace(".", "").replace(",", "."))) \
            if "," in _opt(row, "total_tagihan") else int(float(_opt(row, "total_tagihan")))
        labs = _opt(row, "jumlah_pemeriksaan_lab")
        lab_panels = int(float(labs)) if labs is not None else None
    except ValueError as exc:
        raise RowError("total_tagihan / jumlah_pemeriksaan_lab harus angka") from exc
    if billed < 0 or (lab_panels is not None and lab_panels < 0):
        raise RowError("angka tidak boleh negatif")
    return ClaimRecord(
        claim_number=_opt(row, "nomor_klaim"), member_id=_opt(row, "id_peserta"), hospital=_opt(row, "rumah_sakit"),
        admission_date=adm, discharge_date=dis, billed_amount=billed, icd10=_opt(row, "icd10"), doctor=_opt(row, "dokter"),
        lab_panels=lab_panels, member_name=_opt(row, "nama_peserta"), address=_opt(row, "alamat_peserta"),
        bank_account=_opt(row, "rekening_bank"), referral_from=_opt(row, "rujukan_dari"),
    )
