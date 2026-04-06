"""
用户管理 JSON API
GET  /admin/api/users/stats             统计数据（总数/活跃/7天到期/已封禁）
GET  /admin/api/users                   列表（关键字搜索、分页、类型过滤、排序）
POST /admin/api/users/{emby_id}/ban     封禁（DB + Emby 策略）
POST /admin/api/users/{emby_id}/unban   解封（DB + Emby 策略）
POST /admin/api/users/{emby_id}/update  编辑用户（密码/等级/到期/积分，同步 Emby）
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, and_

from bot import LOGGER
from bot.func_helper.emby import emby
from bot.sql_helper import Session
from bot.sql_helper.sql_emby import Emby, sql_update_emby
from bot.sql_helper.sql_audit import log_audit
from .auth import require_admin

router = APIRouter()

_LV_NAME = {"a": "白名单", "b": "普通用户", "e": "公益用户", "c": "已封禁", "d": "未注册"}


def _emby_to_dict(e: Emby) -> dict:
    return {
        "tg":         e.tg,
        "embyid":     e.embyid or "",
        "name":       e.name or "",
        "lv":         e.lv or "d",
        "lv_name":    _LV_NAME.get(e.lv or "d", e.lv),
        "base_lv":    e.base_lv or "",
        "credits":    e.iv or 0,
        "expire":     e.ex.strftime("%Y-%m-%d") if e.ex else "无期限",
        "expire_raw": e.ex.strftime("%Y-%m-%d") if e.ex else "",
        "created":    e.cr.strftime("%Y-%m-%d") if e.cr else "",
    }


# ── 统计 ─────────────────────────────────────────────────────────────────────

@router.get("/api/users/stats")
async def user_stats(admin=Depends(require_admin)):
    with Session() as session:
        try:
            total    = session.query(Emby).count()
            active   = session.query(Emby).filter(Emby.lv.in_(["a", "b", "e"])).count()
            soon     = datetime.now() + timedelta(days=7)
            expiring = session.query(Emby).filter(
                and_(Emby.lv.in_(["b", "e"]), Emby.ex != None,
                     Emby.ex <= soon, Emby.ex >= datetime.now())
            ).count()
            banned = session.query(Emby).filter(Emby.lv == "c").count()
            return JSONResponse({"total": total, "active": active,
                                 "expiring": expiring, "banned": banned})
        except Exception as e:
            LOGGER.error(f"【Admin】统计用户数据失败: {e}")
            return JSONResponse({"total": 0, "active": 0, "expiring": 0, "banned": 0})


# ── 列表 ─────────────────────────────────────────────────────────────────────

@router.get("/api/users")
async def list_users(
    q: str = "",
    page: int = 1,
    page_size: int = 20,
    type: str = "",
    sort: str = "created",
    order: str = "desc",
    admin=Depends(require_admin),
):
    _sort_map = {
        "expire":  Emby.ex,
        "credits": Emby.iv,
        "name":    Emby.name,
        "created": Emby.cr,
    }
    sort_col = _sort_map.get(sort, Emby.cr)

    with Session() as session:
        try:
            query = session.query(Emby)
            if q.strip():
                kw = f"%{q.strip()}%"
                query = query.filter(or_(Emby.name.ilike(kw), Emby.embyid.ilike(kw)))
            if type == "normal":
                query = query.filter(Emby.lv == "b")
            elif type == "public":
                query = query.filter(Emby.lv == "e")
            elif type == "whitelist":
                query = query.filter(Emby.lv == "a")
            elif type == "banned":
                query = query.filter(Emby.lv == "c")

            query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
            total = query.count()
            rows  = query.offset((page - 1) * page_size).limit(page_size).all()
            return JSONResponse({
                "total": total, "page": page, "page_size": page_size,
                "sort": sort, "order": order,
                "items": [_emby_to_dict(e) for e in rows],
            })
        except Exception as e:
            LOGGER.error(f"【Admin】查询用户列表失败: {e}")
            return JSONResponse({"total": 0, "page": page, "page_size": page_size, "items": []})


# ── 封禁 ─────────────────────────────────────────────────────────────────────

@router.post("/api/users/{emby_id}/ban")
async def ban_user(emby_id: str, admin=Depends(require_admin)):
    with Session() as session:
        row = session.query(Emby).filter(Emby.embyid == emby_id).first()
        if not row:
            return JSONResponse({"ok": False, "msg": "用户不存在"}, status_code=404)
        current_lv = row.lv

    save_base = current_lv if current_lv in ("a", "b", "e") else None
    kwargs = {"lv": "c"}
    if save_base:
        kwargs["base_lv"] = save_base

    # 同步 Emby 账号状态
    emby_ok = await emby.emby_change_policy(emby_id=emby_id, disable=True)
    if not emby_ok:
        LOGGER.warning(f"【Admin】Emby 封禁策略设置失败 embyid={emby_id}，仍写入 DB")

    if not sql_update_emby(Emby.embyid == emby_id, **kwargs):
        return JSONResponse({"ok": False, "msg": "数据库更新失败"}, status_code=500)

    log_audit(category="account", action="ban", source="web",
              operator_name=admin.get("username"),
              before_val=current_lv, after_val="c",
              detail=f"封禁用户 embyid={emby_id}，原等级={current_lv}")
    LOGGER.info(f"【Admin】{admin.get('username')} 封禁用户 embyid={emby_id}，base_lv={save_base}")
    return JSONResponse({"ok": True, "msg": "已封禁" + ("" if emby_ok else "（Emby 策略同步失败，已更新 DB）")})


# ── 解封 ─────────────────────────────────────────────────────────────────────

@router.post("/api/users/{emby_id}/unban")
async def unban_user(emby_id: str, admin=Depends(require_admin)):
    with Session() as session:
        row = session.query(Emby).filter(Emby.embyid == emby_id).first()
        if not row:
            return JSONResponse({"ok": False, "msg": "用户不存在"}, status_code=404)
        restore_lv = row.base_lv if row.base_lv in ("a", "b", "e") else "b"

    # 同步 Emby 账号状态
    emby_ok = await emby.emby_change_policy(emby_id=emby_id, disable=False)
    if not emby_ok:
        LOGGER.warning(f"【Admin】Emby 解封策略设置失败 embyid={emby_id}，仍写入 DB")

    if not sql_update_emby(Emby.embyid == emby_id, lv=restore_lv):
        return JSONResponse({"ok": False, "msg": "数据库更新失败"}, status_code=500)

    log_audit(category="account", action="unban", source="web",
              operator_name=admin.get("username"),
              before_val="c", after_val=restore_lv,
              detail=f"解封用户 embyid={emby_id}，恢复等级={restore_lv}")
    LOGGER.info(f"【Admin】{admin.get('username')} 解封用户 embyid={emby_id}，恢复等级={restore_lv}")
    return JSONResponse({"ok": True, "msg": f"已解封，等级恢复为 {_LV_NAME.get(restore_lv, restore_lv)}"})


# ── 编辑用户 ──────────────────────────────────────────────────────────────────

@router.post("/api/users/{emby_id}/update")
async def update_user(emby_id: str, request: Request, admin=Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "请求体解析失败"}, status_code=400)

    # 读取当前用户
    with Session() as session:
        row = session.query(Emby).filter(Emby.embyid == emby_id).first()
        if not row:
            return JSONResponse({"ok": False, "msg": "用户不存在"}, status_code=404)
        current_lv = row.lv

    db_kwargs = {}
    msgs = []
    need_disable = None   # None=不变, True=禁用, False=启用

    # 账号等级
    new_lv = body.get("lv")
    if new_lv and new_lv in ("a", "b", "c", "e") and new_lv != current_lv:
        db_kwargs["lv"] = new_lv
        if new_lv in ("a", "b", "e"):
            db_kwargs["base_lv"] = new_lv
            if current_lv == "c":
                need_disable = False  # 从封禁恢复 → 启用 Emby 账号
        elif new_lv == "c":
            if current_lv in ("a", "b", "e"):
                db_kwargs["base_lv"] = current_lv
            need_disable = True       # 改为封禁 → 禁用 Emby 账号
        msgs.append("等级")

    # 到期时间
    expire_raw = body.get("expire")
    if expire_raw is not None:
        if expire_raw == "" or expire_raw == "unlimited":
            db_kwargs["ex"] = None
            msgs.append("到期时间(无限)")
        else:
            try:
                db_kwargs["ex"] = datetime.strptime(expire_raw, "%Y-%m-%d")
                msgs.append("到期时间")
            except ValueError:
                return JSONResponse({"ok": False, "msg": "到期时间格式错误（YYYY-MM-DD）"}, status_code=400)

    # 积分
    if "credits" in body:
        try:
            db_kwargs["iv"] = int(body["credits"])
            msgs.append("积分")
        except (ValueError, TypeError):
            return JSONResponse({"ok": False, "msg": "积分必须为整数"}, status_code=400)

    # 同步 Emby 策略（等级变化时）
    if need_disable is not None:
        emby_ok = await emby.emby_change_policy(emby_id=emby_id, disable=need_disable)
        if not emby_ok:
            LOGGER.warning(f"【Admin】Emby 策略同步失败 embyid={emby_id} disable={need_disable}")

    # 写入 DB
    if db_kwargs:
        sql_update_emby(Emby.embyid == emby_id, **db_kwargs)

    # 密码重置（调用 Emby API）
    password = (body.get("password") or "").strip()
    if password:
        ok = await emby.emby_reset(emby_id, new_password=password)
        if not ok:
            return JSONResponse({"ok": False, "msg": "密码重置失败（Emby API 错误）"})
        msgs.append("密码")

    if not msgs:
        return JSONResponse({"ok": False, "msg": "没有修改任何字段"})

    LOGGER.info(f"【Admin】{admin.get('username')} 编辑用户 {emby_id}: {', '.join(msgs)}")
    log_audit(category="account", action="update", source="web",
              operator_name=admin.get("username"),
              detail=f"编辑用户 embyid={emby_id}，变更字段: {', '.join(msgs)}")
    return JSONResponse({"ok": True, "msg": f"已更新: {', '.join(msgs)}"})
