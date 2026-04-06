"""
注册码/邀请码管理 JSON API
GET  /admin/api/codes/stats          统计数据
GET  /admin/api/codes                分页列表（过滤/搜索）
POST /admin/api/codes/create         生成新码
POST /admin/api/codes/delete         按 code 列表删除
POST /admin/api/codes/delete_filter  按条件批量删除未使用码
GET  /admin/api/codes/export         导出 CSV
"""
import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from bot import LOGGER
from bot.func_helper.utils import cr_link_one, rn_link_one
from bot.sql_helper import Session
from bot.sql_helper.sql_code import (
    sql_count_code,
    sql_list_codes,
    sql_delete_codes_by_list,
    sql_delete_unused_by_days,
    sql_delete_all_unused,
    Code,
)
from bot.sql_helper.sql_emby import Emby
from bot.sql_helper.sql_audit import log_audit
from .auth import require_admin

router = APIRouter()

_TYPE_NAME = {
    "register_b": "普通注册码",
    "register_e": "公益注册码",
    "renew":      "续期码",
}
_LV_NAME = {"b": "普通", "e": "公益"}
_DAYS_NAME = {30: "月卡(30天)", 90: "季卡(90天)", 180: "半年卡(180天)", 365: "年卡(365天)"}


def _get_admin_tg(admin: dict) -> int:
    """根据 admin session 中的 Emby user_id 查找对应的 TG ID"""
    emby_id = admin.get("user_id", "")
    if not emby_id:
        return 0
    try:
        with Session() as session:
            row = session.query(Emby).filter(Emby.embyid == emby_id).first()
            return row.tg if row and row.tg else 0
    except Exception:
        return 0


# ── 统计 ──────────────────────────────────────────────────────────────────────

@router.get("/api/codes/stats")
async def code_stats(admin=Depends(require_admin)):
    result = sql_count_code()
    if result is None:
        return JSONResponse({"error": "统计失败"}, status_code=500)
    used_count, tg_mon, tg_sea, tg_half, tg_year, unused_count, public_cnt, normal_cnt = result
    total = used_count + unused_count
    return JSONResponse({
        "total":      total,
        "used":       used_count,
        "unused":     unused_count,
        "public":     public_cnt,   # 公益码(lv=e) 未使用
        "normal":     normal_cnt,   # 普通码(lv=b) 未使用
        "by_days": {
            "30":  tg_mon,
            "90":  tg_sea,
            "180": tg_half,
            "365": tg_year,
        },
    })


# ── 列表 ──────────────────────────────────────────────────────────────────────

@router.get("/api/codes")
async def list_codes(
    q:          str = "",
    page:       int = 1,
    page_size:  int = 20,
    type:       str = "all",
    status:     str = "all",
    days:       int = None,
    creator_tg: int = None,
    used_by_tg: int = None,
    sort:       str = "created_at",
    order:      str = "desc",
    admin=Depends(require_admin),
):
    total, items = sql_list_codes(
        page=page, page_size=page_size,
        code_type=type, status=status,
        days=days, q=q,
        creator_tg=creator_tg, used_by_tg=used_by_tg,
        sort=sort, order=order,
    )
    return JSONResponse({
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     items,
    })


# ── 生成码 ─────────────────────────────────────────────────────────────────────

@router.post("/api/codes/create")
async def create_codes(request: Request, admin=Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "请求体解析失败"}, status_code=400)

    code_type = body.get("type", "")       # register_b / register_e / renew
    days_val  = body.get("days", 30)
    count     = body.get("count", 1)

    # 参数校验
    if code_type not in ("register_b", "register_e", "renew"):
        return JSONResponse({"ok": False, "msg": "type 参数无效"}, status_code=400)
    try:
        days_val = int(days_val)
        count    = int(count)
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "msg": "days/count 必须为整数"}, status_code=400)
    if days_val not in (30, 90, 180, 365):
        return JSONResponse({"ok": False, "msg": "days 只能为 30/90/180/365"}, status_code=400)
    if count < 1 or count > 200:
        return JSONResponse({"ok": False, "msg": "count 范围 1~200"}, status_code=400)

    times_str = str(days_val)
    # 查询管理员对应的 TG ID
    admin_tg = _get_admin_tg(admin)
    if code_type == "renew":
        links, code_list = await rn_link_one(tg=admin_tg, times=times_str, count=count, days=days_val, method="code")
    else:
        lv = "b" if code_type == "register_b" else "e"
        links, code_list = await cr_link_one(tg=admin_tg, times=times_str, count=count, days=days_val, method="code", lv=lv)

    if code_list is None:
        return JSONResponse({"ok": False, "msg": "生成失败，请重试"}, status_code=500)

    type_label = _TYPE_NAME.get(code_type, code_type)
    log_audit(
        category="code", action="create", source="web",
        operator_name=admin.get("username"),
        detail=f"Web管理员生成{type_label} {count} 个，{days_val}天\n码列表：\n" + "\n".join(code_list),
    )
    LOGGER.info(f"【Admin】{admin.get('username')} 通过Web生成 {count} 个{type_label}({days_val}天)")
    return JSONResponse({"ok": True, "count": len(code_list), "codes": code_list})


# ── 按列表删除 ────────────────────────────────────────────────────────────────

@router.post("/api/codes/delete")
async def delete_codes(request: Request, admin=Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "请求体解析失败"}, status_code=400)

    code_list = body.get("codes", [])
    if not isinstance(code_list, list) or not code_list:
        return JSONResponse({"ok": False, "msg": "codes 不能为空"}, status_code=400)
    if len(code_list) > 500:
        return JSONResponse({"ok": False, "msg": "单次最多删除 500 条"}, status_code=400)

    count = sql_delete_codes_by_list(code_list)
    log_audit(
        category="code", action="delete", source="web",
        operator_name=admin.get("username"),
        detail=f"Web管理员删除 {count} 个注册/续期码（按列表）",
    )
    LOGGER.info(f"【Admin】{admin.get('username')} 删除 {count} 个码")
    return JSONResponse({"ok": True, "count": count})


# ── 按条件批量删除未使用码 ─────────────────────────────────────────────────────

@router.post("/api/codes/delete_filter")
async def delete_codes_filter(request: Request, admin=Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "请求体解析失败"}, status_code=400)

    days_list = body.get("days", [])   # [] 代表全部天数
    confirm   = body.get("confirm", False)
    if not confirm:
        return JSONResponse({"ok": False, "msg": "请确认操作（confirm=true）"}, status_code=400)

    if days_list:
        # 校验
        for d in days_list:
            if d not in (30, 90, 180, 365):
                return JSONResponse({"ok": False, "msg": f"无效天数: {d}"}, status_code=400)
        count = sql_delete_unused_by_days(days_list)
        days_label = "/".join(str(d) for d in days_list) + "天"
    else:
        count = sql_delete_all_unused()
        days_label = "全部"

    log_audit(
        category="code", action="delete", source="web",
        operator_name=admin.get("username"),
        detail=f"Web管理员批量删除未使用码（{days_label}），共 {count} 个",
    )
    LOGGER.info(f"【Admin】{admin.get('username')} 批量删除未使用码 {count} 个")
    return JSONResponse({"ok": True, "count": count})


# ── 自动补全建议 ──────────────────────────────────────────────────────────────

@router.get("/api/codes/suggest_creators")
async def suggest_creators(q: str = "", admin=Depends(require_admin)):
    """返回创建者TG ID 补全建议（最多20条）"""
    with Session() as session:
        rows = session.query(Code.tg).filter(Code.tg.isnot(None)).distinct().all()
        items = sorted(set(row[0] for row in rows if row[0]))
        q = q.strip()
        if q:
            items = [v for v in items if q in str(v)]
        return JSONResponse({"items": items[:20]})


@router.get("/api/codes/suggest_users")
async def suggest_users(q: str = "", admin=Depends(require_admin)):
    """返回使用者TG ID 补全建议（最多20条）"""
    with Session() as session:
        rows = session.query(Code.used).filter(Code.used.isnot(None)).distinct().all()
        items = sorted(set(row[0] for row in rows if row[0]))
        q = q.strip()
        if q:
            items = [v for v in items if q in str(v)]
        return JSONResponse({"items": items[:20]})


# ── 导出 CSV ──────────────────────────────────────────────────────────────────

@router.get("/api/codes/export")
async def export_codes(
    type:       str = "all",
    status:     str = "all",
    days:       int = None,
    q:          str = "",
    creator_tg: int = None,
    used_by_tg: int = None,
    admin=Depends(require_admin),
):
    total, items = sql_list_codes(
        page=1, page_size=99999,
        code_type=type, status=status,
        days=days, q=q,
        creator_tg=creator_tg, used_by_tg=used_by_tg,
        sort="created_at", order="desc",
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["码", "类型", "等级", "有效天数", "状态", "创建者TG", "使用者TG", "使用时间"])
    for item in items:
        type_label = "注册码" if item["type"] == "register" else ("续期码" if item["type"] == "renew" else "未知")
        lv_label   = _LV_NAME.get(item["lv"], item["lv"])
        writer.writerow([
            item["code"],
            type_label,
            lv_label,
            item["days"],
            "已使用" if item["status"] == "used" else "未使用",
            item["creator"] or "",
            item["used_by"] or "",
            item["used_time"] or "",
        ])

    output.seek(0)
    filename = f"codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
