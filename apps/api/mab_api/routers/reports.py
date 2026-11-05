"""U6: penampil log audit, jejak keputusan klaim, dan laporan bulanan (halaman Laporan & Audit)."""
from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import reporting
from mab_api.access import get_visible_claim, tenant_ids
from mab_api.audit import record
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.models import Insurer, Report, User
from mab_api.rbac import Perm, has_perm

router = APIRouter(tags=["laporan & audit"])

can_audit = require_perm(Perm.AUDIT_VIEW)
can_view = require_perm(Perm.REPORT_VIEW)
can_generate = require_perm(Perm.REPORT_GENERATE)


def _day(d: date | None, end: bool = False) -> datetime | None:
    if d is None:
        return None
    dt = datetime.combine(d, time.min, tzinfo=timezone.utc)
    return dt + timedelta(days=1) if end else dt


def _audit_filters(claim_id: str | None = None, claim_number: str | None = None, user: str | None = Query(default=None),
                   action: str | None = None, group: str | None = None, date_from: date | None = None,
                   date_to: date | None = None) -> dict:
    return {"claim_id": claim_id, "claim_number": claim_number, "user_query": user, "action": action, "group": group,
            "date_from": _day(date_from), "date_to": _day(date_to, end=True)}


@router.get("/audit/logs")
def audit_logs(filters: dict = Depends(_audit_filters), limit: int = Query(100, ge=1, le=500),
               offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(can_audit)) -> dict:
    """Log audit dalam cakupan pengguna, terbaru dulu. Tanggal `date_to` inklusif."""
    total, rows = reporting.query_audit(db, user, limit=limit, offset=offset, **filters)
    return {"total": total, "limit": limit, "offset": offset, "items": reporting.describe_rows(db, rows),
            "groups": reporting.ACTION_GROUPS}


@router.get("/audit/logs/xlsx")
def audit_logs_xlsx(request: Request, filters: dict = Depends(_audit_filters), db: Session = Depends(get_db),
                    user: User = Depends(can_audit)) -> Response:
    """Ekspor Excel log audit sesuai filter (maks. 5.000 baris)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    total, rows = reporting.query_audit(db, user, limit=5000, **filters)
    wb = Workbook()
    ws = wb.active
    ws.title = "Log audit"
    ws.append([f"Log audit · {reporting.DATA_LABEL} · {total} entri · diekspor {datetime.now(timezone.utc):%d-%m-%Y %H:%M} UTC"])
    cols = ["Waktu (UTC)", "Aksi", "Kode aksi", "Kelompok", "Pengguna", "Email", "Peran", "Klaim", "Dokumen",
            "Metode", "Path", "Status HTTP", "IP", "Rincian"]
    ws.append(cols)
    for c in range(1, len(cols) + 1):
        ws.cell(2, c).font = Font(bold=True)
    for r in reporting.describe_rows(db, rows):
        ws.append([reporting._utc(r["occurred_at"]).strftime("%Y-%m-%d %H:%M:%S"), r["label"], r["action"],
                   reporting.ACTION_GROUPS.get(r["group"]), r["user_name"], r["user_email"], r["user_role"],
                   r["claim_number"], r["document_name"], r["method"], r["path"], r["status_code"], r["ip_address"],
                   str(r["detail"]) if r["detail"] else None])
    buf = io.BytesIO()
    wb.save(buf)
    record(db, "AUDIT_LOG_EXPORTED", user_id=user.id, user_role=user.role, request=request,
           detail={"rows": len(rows), "filters": {k: str(v) for k, v in filters.items() if v}})
    db.commit()
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="log_audit.xlsx"'})


@router.get("/audit/claims/{claim_id}/trace")
def claim_trace(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_audit)) -> dict:
    """Jejak keputusan satu klaim dari unggah sampai keputusan akhir."""
    return reporting.claim_trace(db, get_visible_claim(db, user, claim_id))


@router.get("/audit/claims/{claim_id}/trace/pdf")
def claim_trace_pdf(claim_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(can_audit)) -> Response:
    claim = get_visible_claim(db, user, claim_id)
    pdf = reporting.trace_pdf(reporting.claim_trace(db, claim))
    record(db, "AUDIT_TRACE_EXPORTED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request)
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="jejak_{claim.claim_number}.pdf"'})


# ----------------------------------------------------------------------------- laporan bulanan

def _report_scopes(db: Session, user: User) -> tuple[bool, set[str]]:
    """(boleh laporan seluruh platform, tenant yang boleh)."""
    tenants = tenant_ids(db, user)
    if tenants is None:
        return True, set(db.scalars(select(Insurer.id)))
    return False, tenants


def _visible_report(db: Session, user: User, report_id: str) -> Report:
    rep = db.get(Report, report_id)
    platform, tenants = _report_scopes(db, user)
    if rep is None or (rep.insurer_id is None and not platform) or (rep.insurer_id and rep.insurer_id not in tenants):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak ditemukan")
    return rep


def _summary(rep: Report) -> dict:
    return {"id": rep.id, "kind": rep.kind, "period": rep.period, "insurer_id": rep.insurer_id,
            "insurer_name": rep.insurer.name if rep.insurer else None, "template_version": rep.template_version,
            "revision": rep.revision, "trigger": rep.trigger, "partial": rep.partial,
            "generated_at": rep.generated_at, "generated_by": rep.generated_by.full_name if rep.generated_by else None}


@router.get("/reports")
def list_reports(db: Session = Depends(get_db), user: User = Depends(can_view)) -> dict:
    platform, tenants = _report_scopes(db, user)
    q = select(Report).order_by(Report.period.desc(), Report.scope_key)
    reps = [r for r in db.scalars(q) if (r.insurer_id is None and platform) or (r.insurer_id in tenants)]
    insurers = [{"id": i.id, "name": i.name} for i in db.scalars(select(Insurer).order_by(Insurer.code)) if i.id in tenants]
    return {"items": [_summary(r) for r in reps], "insurers": insurers, "can_platform": platform,
            "can_generate": has_perm(user.role, Perm.REPORT_GENERATE),
            "template_version": reporting.TEMPLATE_VERSION, "template_note": reporting.TEMPLATE_NOTE,
            "next_scheduled": _next_run()}


def _next_run() -> str:
    now = datetime.now(timezone.utc)
    first = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    return first.isoformat()


class GenerateIn(BaseModel):
    period: str
    insurer_id: str | None = None  # kosong = seluruh platform (admin / auditor platform)


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def generate(body: GenerateIn, request: Request, db: Session = Depends(get_db), user: User = Depends(can_generate)) -> dict:
    """Buat (atau buat ulang) laporan bulanan satu periode. Periode berjalan ditandai sementara."""
    platform, tenants = _report_scopes(db, user)
    try:
        start, _ = reporting.parse_period(body.period)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if start > datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Periode belum dimulai")
    insurer_id = body.insurer_id
    if insurer_id is None and not platform:
        insurer_id = next(iter(tenants), None) if len(tenants) == 1 else None
        if insurer_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pilih asuransi")
    if insurer_id is not None and insurer_id not in tenants:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Asuransi tidak ditemukan")
    insurer = db.get(Insurer, insurer_id) if insurer_id else None
    rep = reporting.generate_report(db, insurer, body.period, trigger="MANUAL", user=user)
    record(db, "REPORT_GENERATED", user_id=user.id, user_role=user.role, request=request,
           detail={"report_id": rep.id, "period": rep.period, "scope": rep.scope_key, "revision": rep.revision,
                   "trigger": "MANUAL"})
    db.commit()
    return _summary(rep) | {"data": rep.data}


@router.post("/reports/run-schedule")
def run_schedule(request: Request, db: Session = Depends(get_db), user: User = Depends(require_perm(Perm.TENANT_ADMIN))) -> dict:
    """Jalankan penjadwal sekarang (admin). Membuat laporan bulan lalu yang belum ada."""
    made = reporting.run_schedule(db)
    db.commit()
    return {"created": [_summary(r) for r in made]}


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db), user: User = Depends(can_view)) -> dict:
    rep = _visible_report(db, user, report_id)
    return _summary(rep) | {"data": rep.data}


def _download(db: Session, user: User, request: Request, rep: Report, fmt: str) -> None:
    record(db, "REPORT_DOWNLOADED", user_id=user.id, user_role=user.role, request=request,
           detail={"report_id": rep.id, "period": rep.period, "scope": rep.scope_key, "format": fmt})
    db.commit()


def _filename(rep: Report, ext: str) -> str:
    scope = (rep.insurer.code if rep.insurer else "SEMUA").lower()
    return f"laporan_pojk36_{scope}_{rep.period}_r{rep.revision}.{ext}"


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(can_view)) -> Response:
    rep = _visible_report(db, user, report_id)
    data = reporting.report_pdf(rep)
    _download(db, user, request, rep, "pdf")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(rep, "pdf")}"'})


@router.get("/reports/{report_id}/xlsx")
def report_xlsx(report_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(can_view)) -> Response:
    rep = _visible_report(db, user, report_id)
    data = reporting.report_xlsx(rep)
    _download(db, user, request, rep, "xlsx")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_filename(rep, "xlsx")}"'})
