"""
日志审计 API
GET  /admin/api/audit              分页查询（支持 category/source/keyword/date_from/date_to）
GET  /admin/api/audit/export/csv   导出 CSV
DELETE /admin/api/audit/cleanup    清理指定天数前的日志
"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from bot.sql_helper.sql_audit import delete_audit_logs_before, query_audit_logs, get_audit_operator_names
from .auth import require_admin

router = APIRouter()

_CATEGORY_NAMES = {
    "credits":  "积分变动",
    "code":     "注册/邀请码",
    "account":  "账号变动",
    "settings": "系统设置",
    "login":    "管理员登录",
    "request":  "求片审批",
    "bot_cmd":  "Bot 指令",
}


@router.get("/api/audit")
async def list_audit(
    category:    str = "",
    action:      str = "",
    source:      str = "",
    keyword:     str = "",
    operator_tg: int = Query(0, ge=0),
    target_tg:   int = Query(0, ge=0),
    date_from:   str = "",
    date_to:     str = "",
    page:        int = Query(1, ge=1),
    page_size:   int = Query(50, ge=1, le=200),
    admin=Depends(require_admin),
):
    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to, end_of_day=True)

    result = query_audit_logs(
        category=category or None,
        action=action or None,
        source=source or None,
        keyword=keyword or None,
        operator_tg=operator_tg or None,
        target_tg=target_tg or None,
        date_from=dt_from,
        date_to=dt_to,
        page=page,
        page_size=page_size,
    )
    return JSONResponse(result)


@router.get("/api/audit/export/csv")
async def export_audit_csv(
    category:    str = "",
    action:      str = "",
    source:      str = "",
    keyword:     str = "",
    operator_tg: int = Query(0, ge=0),
    target_tg:   int = Query(0, ge=0),
    date_from:   str = "",
    date_to:     str = "",
    admin=Depends(require_admin),
):
    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to, end_of_day=True)

    result = query_audit_logs(
        category=category or None,
        action=action or None,
        source=source or None,
        keyword=keyword or None,
        operator_tg=operator_tg or None,
        target_tg=target_tg or None,
        date_from=dt_from,
        date_to=dt_to,
        page=1,
        page_size=10000,
    )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "created_at", "category", "action", "source",
        "operator_tg", "operator_name", "target_tg", "target_name",
        "before_val", "after_val", "detail", "note", "ip",
    ])
    writer.writeheader()
    for row in result["items"]:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    filename = f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/audit/operators")
async def list_audit_operators(admin=Depends(require_admin)):
    """返回 config.admins 中配置的管理员列表（附带从审计日志中查到的昵称）"""
    from bot import config
    admin_ids = list(getattr(config, "admins", []) or [])
    # 也包含 owner（可能是 int 或 list）
    owner = getattr(config, "owner", None)
    if isinstance(owner, int) and owner and owner not in admin_ids:
        admin_ids.insert(0, owner)
    elif isinstance(owner, list):
        for oid in owner:
            if oid and oid not in admin_ids:
                admin_ids.insert(0, oid)

    names = get_audit_operator_names(admin_ids)
    operators = [
        {"tg": tg_id, "name": names.get(tg_id) or str(tg_id)}
        for tg_id in admin_ids
    ]
    return JSONResponse({"ok": True, "operators": operators})


@router.get("/api/audit/suggest_targets")
async def suggest_targets(q: str = "", admin=Depends(require_admin)):
    """返回操作目标补全建议（target_tg + target_name，最多20条）"""
    from bot.sql_helper.sql_audit import AuditLog
    from bot.sql_helper import Session as DbSession
    q_low = q.strip().lower()
    with DbSession() as session:
        rows = (
            session.query(AuditLog.target_tg, AuditLog.target_name)
            .filter(AuditLog.target_tg.isnot(None))
            .distinct()
            .all()
        )
        seen = set()
        items = []
        for tg, name in rows:
            if not tg or tg in seen:
                continue
            name_s = name or ""
            if not q_low or q_low in str(tg) or q_low in name_s.lower():
                items.append({"tg": tg, "name": name_s or str(tg)})
                seen.add(tg)
        items.sort(key=lambda x: x["tg"])
        return JSONResponse({"items": items[:20]})


@router.delete("/api/audit/cleanup")
async def cleanup_audit(days: int = Query(90, ge=1), admin=Depends(require_admin)):
    """删除 days 天前的日志"""
    from datetime import timedelta
    dt = datetime.now() - timedelta(days=days)
    n = delete_audit_logs_before(dt)
    return JSONResponse({"ok": True, "deleted": n, "before": dt.strftime("%Y-%m-%d")})


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_dt(s: str, end_of_day: bool = False):
    if not s:
        return None
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt
    except ValueError:
        return None
