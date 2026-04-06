"""
求片管理 JSON API
GET    /admin/api/requests             列表（支持 status 过滤、分页）
GET    /admin/api/requests/stats       各状态数量统计
POST   /admin/api/requests/{id}/approve   审批通过 → processing（不通知用户）
POST   /admin/api/requests/{id}/complete  标记入库 → completed（通知用户）
POST   /admin/api/requests/{id}/reject    拒绝     → rejected（通知用户）
PUT    /admin/api/requests/{id}           修改状态/管理员备注（所有状态可用）
DELETE /admin/api/requests/{id}           删除申请
POST   /admin/api/requests/batch          批量操作（approve/complete/reject/delete）
"""
from typing import List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bot import bot, LOGGER
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_miniapp import (
    sql_get_all_requests,
    sql_get_request_by_id,
    sql_update_request_status,
    sql_update_request,
    sql_delete_request,
    sql_get_requests_stats,
)
from .auth import require_admin

router = APIRouter()


@router.get("/api/requests/stats")
async def requests_stats(admin=Depends(require_admin)):
    """返回各状态数量统计"""
    return JSONResponse(sql_get_requests_stats())


@router.get("/api/requests")
async def list_requests(
    status: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    admin=Depends(require_admin),
):
    data = sql_get_all_requests(
        status=status or None,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return JSONResponse(data)


@router.post("/api/requests/{request_id}/approve")
async def approve_request(request_id: int, request: Request, admin=Depends(require_admin)):
    """审批通过：status → processing（仅改状态，不通知用户）"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    note = body.get("note", "")

    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    updated = sql_update_request_status(request_id, "processing", note or None)
    if not updated:
        return JSONResponse({"ok": False, "msg": "更新失败"}, status_code=500)

    log_audit(category="request", action="approve", source="web",
              operator_name=admin.get("username"), target_tg=req.tg,
              detail=f"审批求片申请 id={request_id} 《{req.title}》 → 处理中")
    return JSONResponse({"ok": True, "msg": "已审批通过（处理中）"})


@router.post("/api/requests/{request_id}/complete")
async def complete_request(request_id: int, request: Request, admin=Depends(require_admin)):
    """手动标记已入库：status → completed，通知用户可以观看"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    note = body.get("note", "")

    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    updated = sql_update_request_status(request_id, "completed", note or None)
    if not updated:
        return JSONResponse({"ok": False, "msg": "更新失败"}, status_code=500)

    try:
        msg = (
            f"🎉 **好消息！您申请的影片已入库！**\n\n"
            f"📽️ 《{req.title}》\n"
        )
        if note:
            msg += f"\n\n管理员备注：{note}"
        await bot.send_message(chat_id=req.tg, text=msg)
    except Exception as e:
        LOGGER.warning(f"【Admin】通知用户 {req.tg} 失败: {e}")

    log_audit(category="request", action="complete", source="web",
              operator_name=admin.get("username"), target_tg=req.tg,
              detail=f"标记求片已入库 id={request_id} 《{req.title}》")
    return JSONResponse({"ok": True, "msg": "已标记入库并通知用户"})


@router.post("/api/requests/{request_id}/reject")
async def reject_request(request_id: int, request: Request, admin=Depends(require_admin)):
    """拒绝：status → rejected，通知用户"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    note = body.get("note", "")

    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    updated = sql_update_request_status(request_id, "rejected", note or None)
    if not updated:
        return JSONResponse({"ok": False, "msg": "更新失败"}, status_code=500)

    try:
        msg = (
            f"❌ **您申请的影片暂时无法入库**\n\n"
            f"📽️ 《{req.title}》\n"
            f"如有疑问请联系管理员。"
        )
        if note:
            msg += f"\n\n管理员备注：{note}"
        await bot.send_message(chat_id=req.tg, text=msg)
    except Exception as e:
        LOGGER.warning(f"【Admin】通知用户 {req.tg} 失败: {e}")

    log_audit(category="request", action="reject", source="web",
              operator_name=admin.get("username"), target_tg=req.tg,
              detail=f"拒绝求片申请 id={request_id} 《{req.title}》")
    return JSONResponse({"ok": True, "msg": "已拒绝并通知用户"})


@router.put("/api/requests/{request_id}")
async def edit_request(request_id: int, request: Request, admin=Depends(require_admin)):
    """编辑申请：可修改状态和管理员备注（所有状态均可操作）"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    new_status = body.get("status") or None
    new_note = body.get("note")

    valid_statuses = {"pending", "processing", "completed", "rejected"}
    if new_status and new_status not in valid_statuses:
        return JSONResponse({"ok": False, "msg": "无效的状态值"}, status_code=400)

    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    updated = sql_update_request(request_id, status=new_status, note=new_note)
    if not updated:
        return JSONResponse({"ok": False, "msg": "更新失败"}, status_code=500)

    log_audit(category="request", action="edit", source="web",
              operator_name=admin.get("username"),
              detail=f"编辑求片申请 id={request_id} status={new_status}")
    return JSONResponse({"ok": True, "msg": "修改成功"})


@router.delete("/api/requests/{request_id}")
async def delete_request(request_id: int, admin=Depends(require_admin)):
    """删除求片申请"""
    ok = sql_delete_request(request_id)
    if not ok:
        return JSONResponse({"ok": False, "msg": "申请不存在或删除失败"}, status_code=404)
    log_audit(category="request", action="delete", source="web",
              operator_name=admin.get("username"),
              detail=f"删除求片申请 id={request_id}")
    return JSONResponse({"ok": True, "msg": "已删除"})


# ── 批量操作 ──────────────────────────────────────────────────────────────────

class BatchBody(BaseModel):
    ids: List[int]
    action: str          # approve | complete | reject | delete
    note: str = ""


@router.post("/api/requests/batch")
async def batch_requests(body: BatchBody, admin=Depends(require_admin)):
    """批量操作：对多条申请执行相同动作"""
    valid_actions = {"approve", "complete", "reject", "delete"}
    if body.action not in valid_actions:
        return JSONResponse({"ok": False, "msg": "无效操作"}, status_code=400)
    if not body.ids:
        return JSONResponse({"ok": False, "msg": "未选择任何记录"}, status_code=400)

    action_status = {"approve": "processing", "complete": "completed", "reject": "rejected"}
    ok_count = 0

    for req_id in body.ids:
        req = sql_get_request_by_id(req_id)
        if not req:
            continue

        if body.action == "delete":
            if sql_delete_request(req_id):
                ok_count += 1

        else:
            new_status = action_status[body.action]
            updated = sql_update_request_status(req_id, new_status, body.note or None)
            if not updated:
                continue
            ok_count += 1

            # 仅 complete 和 reject 通知用户
            if body.action == "complete":
                try:
                    msg = (
                        f"🎉 **好消息！您申请的影片已入库！**\n\n"
                        f"📽️ 《{req.title}》\n"
                    )
                    if body.note:
                        msg += f"\n\n管理员备注：{body.note}"
                    await bot.send_message(chat_id=req.tg, text=msg)
                except Exception as e:
                    LOGGER.warning(f"【Admin批量】通知用户 {req.tg} 失败: {e}")

            elif body.action == "reject":
                try:
                    msg = (
                        f"❌ **您申请的影片暂时无法入库**\n\n"
                        f"📽️ 《{req.title}》\n如有疑问请联系管理员。"
                    )
                    if body.note:
                        msg += f"\n\n管理员备注：{body.note}"
                    await bot.send_message(chat_id=req.tg, text=msg)
                except Exception as e:
                    LOGGER.warning(f"【Admin批量】通知用户 {req.tg} 失败: {e}")

    log_audit(category="request", action=f"batch_{body.action}", source="web",
              operator_name=admin.get("username"),
              detail=f"批量{body.action} {ok_count}/{len(body.ids)} 条求片申请 ids={body.ids[:10]}")
    return JSONResponse({"ok": True, "msg": f"批量操作完成，成功 {ok_count}/{len(body.ids)} 条"})


