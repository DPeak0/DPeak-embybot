"""
求片管理 JSON API
GET    /admin/api/requests             列表（支持 status 过滤、分页）
GET    /admin/api/requests/stats       各状态数量统计
POST   /admin/api/requests/sync_status 手动刷新真实状态
GET    /admin/api/requests/{id}/hdhive 查询当前影片在影巢的资源结果
POST   /admin/api/requests/{id}/approve   审批通过 → processing（不通知用户）
POST   /admin/api/requests/{id}/complete  标记入库 → completed（通知用户）
POST   /admin/api/requests/{id}/reject    拒绝     → rejected（通知用户）
PUT    /admin/api/requests/{id}           修改状态/管理员备注（所有状态可用）
DELETE /admin/api/requests/{id}           删除申请
POST   /admin/api/requests/batch          批量操作（approve/complete/reject/delete）
"""
import asyncio
import http.client
import json
import threading
import urllib.parse
import urllib.request
from typing import List

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bot import bot, config, LOGGER
from bot.integrations.hdhive_openapi import HDHiveClient, HDHiveOpenAPIError
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_miniapp import (
    sql_get_all_requests,
    sql_get_request_by_id,
    sql_update_request_status,
    sql_update_request,
    sql_delete_request,
    sql_get_requests_stats,
)
from bot.web.miniapp_notify import (
    sync_pending_requests_by_tmdb_ids,
    sync_all_incomplete_requests,
    send_request_completed_notification,
)
from .auth import require_admin

router = APIRouter()


class CMSIntegrationError(Exception):
    def __init__(self, stage: str, message: str, *, status_code=None, response_data=None):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.status_code = status_code
        self.response_data = response_data or {}


def _normalize_hdhive_query(req):
    media_type = str(getattr(req, "media_type", "") or "").strip().lower()
    tmdb_id = str(getattr(req, "tmdb_id", "") or "").strip()

    if media_type in {"show", "series"}:
        media_type = "tv"
    elif media_type in {"film", "movies"}:
        media_type = "movie"

    return media_type, tmdb_id


def _normalize_hdhive_items(payload):
    data = payload.get("data")
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if isinstance(data.get("items"), list):
            items = data.get("items") or []
        elif isinstance(data.get("resources"), list):
            items = data.get("resources") or []
        else:
            items = [data]
    else:
        items = []

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or item.get("original_title") or item.get("slug") or "-"
        route = "tv" if (item.get("type") or item.get("media_type")) == "tv" else "movie"
        tmdb_id = item.get("tmdb_id")
        detail_url = item.get("media_url") or None
        if not detail_url and tmdb_id:
            base_url = (getattr(config, "hdhive_base_url", "") or "https://hdhive.com").rstrip("/")
            detail_url = f"{base_url}/{route}/{tmdb_id}"
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        normalized.append({
            "title": title,
            "original_title": item.get("original_title") or "",
            "type": item.get("type") or item.get("media_type") or "",
            "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
            "tmdb_id": str(tmdb_id) if tmdb_id is not None else "",
            "imdb_id": item.get("imdb_id") or "",
            "slug": item.get("slug") or "",
            "pan_type": item.get("pan_type") or "",
            "share_size": item.get("share_size") or "",
            "video_resolution": item.get("video_resolution") or [],
            "source": item.get("source") or [],
            "subtitle_language": item.get("subtitle_language") or [],
            "subtitle_type": item.get("subtitle_type") or [],
            "remark": item.get("remark") or "",
            "unlock_points": item.get("unlock_points"),
            "is_unlocked": bool(item.get("is_unlocked")),
            "is_official": bool(item.get("is_official")),
            "validate_status": item.get("validate_status"),
            "validate_message": item.get("validate_message") or "",
            "created_at": item.get("created_at") or "",
            "share_num": item.get("share_num"),
            "unlocked_users_count": item.get("unlocked_users_count"),
            "douban_rating": item.get("douban_rating"),
            "imdb_rating": item.get("imdb_rating"),
            "tmdb_rating": item.get("tmdb_rating"),
            "poster_path": item.get("poster_path") or "",
            "overview": item.get("overview") or "",
            "detail_url": detail_url,
            "media_url": item.get("media_url") or "",
            "media_slug": item.get("media_slug") or "",
            "user_nickname": user.get("nickname") or "",
            "user_avatar_url": user.get("avatar_url") or "",
        })
    return normalized


def _query_hdhive_resources_sync(media_type: str, tmdb_id: str):
    client = HDHiveClient(
        (getattr(config, "hdhive_base_url", "") or "https://hdhive.com").rstrip("/"),
        getattr(config, "hdhive_api_key", "") or "",
    )
    return client.query_resources(media_type, tmdb_id)


def _unlock_hdhive_resource_sync(slug: str):
    client = HDHiveClient(
        (getattr(config, "hdhive_base_url", "") or "https://hdhive.com").rstrip("/"),
        getattr(config, "hdhive_api_key", "") or "",
    )
    return client.unlock_resource(slug)


async def _query_hdhive_resources(media_type: str, tmdb_id: str):
    return await asyncio.to_thread(_query_hdhive_resources_sync, media_type, tmdb_id)


async def _unlock_hdhive_resource(slug: str):
    return await asyncio.to_thread(_unlock_hdhive_resource_sync, slug)


def _cms_request(method: str, path: str, body=None):
    base_url = (getattr(config, "cms_base_url", "") or "").rstrip("/")
    token = (getattr(config, "cms_api_token", "") or "").strip()
    if not base_url:
        raise ValueError("cms_base_url is required")
    if not token:
        raise ValueError("cms_api_token is required")

    url = f"{base_url}{path}"
    payload = None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "python-requests/2.31.0",
    }
    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise CMSIntegrationError("cms_request", raw or exc.reason, status_code=exc.code) from exc
        raise CMSIntegrationError(
            "cms_request",
            str(data.get("msg") or data.get("message") or exc.reason),
            status_code=exc.code,
            response_data=data,
        ) from exc
    except TimeoutError as exc:
        raise CMSIntegrationError("cms_request", "The read operation timed out") from exc
    except http.client.RemoteDisconnected as exc:
        raise CMSIntegrationError("cms_request", "Remote end closed connection without response") from exc

    code = data.get("code")
    if code not in (200, "200", None):
        raise CMSIntegrationError(
            "cms_request",
            str(data.get("msg") or data.get("message") or "CMS 请求失败"),
            response_data=data,
        )
    return data


def _cms_add_share_download(shared_url: str):
    token = (getattr(config, "cms_api_token", "") or "").strip()
    try:
        return _cms_request("POST", "/api/cloud/add_share_down_by_token", {"url": shared_url, "token": token})
    except CMSIntegrationError as exc:
        exc.stage = "cms_transfer"
        raise


def _cms_submit_share_background(shared_url: str):
    try:
        result = _cms_add_share_download(shared_url)
        LOGGER.info(f"【Admin】CMS后台转存提交完成: {result}")
    except Exception as exc:
        LOGGER.warning(f"【Admin】CMS后台转存提交异常: {exc}")


def _build_hdhive_error(exc):
    payload = getattr(exc, "response_data", {}) or {}
    headers = getattr(exc, "headers", {}) or {}
    return {
        "ok": False,
        "msg": (
            getattr(exc, "description", "")
            or payload.get("detail")
            or payload.get("title")
            or getattr(exc, "message", "")
            or "影巢查询失败"
        ),
        "error_code": getattr(exc, "code", "unknown"),
        "status_code": getattr(exc, "status_code", None),
        "limit_scope": payload.get("limit_scope"),
        "retry_after_seconds": payload.get("retry_after_seconds"),
        "retry_after": headers.get("Retry-After"),
        "error_name": payload.get("error_name"),
        "ray_id": payload.get("ray_id"),
        "cloudflare_error": bool(payload.get("cloudflare_error")),
        "owner_action_required": bool(payload.get("owner_action_required")),
    }


def _build_cms_error(exc):
    payload = getattr(exc, "response_data", {}) or {}
    return {
        "ok": False,
        "msg": getattr(exc, "message", "") or payload.get("msg") or payload.get("message") or "CMS 转存失败",
        "stage": getattr(exc, "stage", "cms"),
        "status_code": getattr(exc, "status_code", None),
        "cms_code": payload.get("code"),
    }


def _poster_url(poster_path: str) -> str:
    if not poster_path:
        return ""
    if poster_path.startswith("http://") or poster_path.startswith("https://"):
        return poster_path
    return f"/miniapp/tmdb_image?path={urllib.parse.quote(poster_path, safe='')}&w=300"


@router.get("/api/requests/{request_id}/hdhive")
async def lookup_request_hdhive(request_id: int, admin=Depends(require_admin)):
    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    media_type, tmdb_id = _normalize_hdhive_query(req)

    if not tmdb_id:
        return JSONResponse({
            "ok": False,
            "msg": "当前申请缺少 TMDB ID，无法联查影巢",
            "query_media_type": media_type,
            "query_tmdb_id": tmdb_id,
        }, status_code=400)

    if media_type not in {"movie", "tv"}:
        return JSONResponse({
            "ok": False,
            "msg": "当前申请的媒体类型无效，仅支持 movie / tv",
            "query_media_type": media_type,
            "query_tmdb_id": tmdb_id,
        }, status_code=400)

    try:
        payload = await _query_hdhive_resources(media_type, tmdb_id)
    except ImportError as exc:
        return JSONResponse({"ok": False, "msg": f"影巢 SDK 加载失败: {exc}"}, status_code=500)
    except Exception as exc:
        if isinstance(exc, HDHiveOpenAPIError):
            error_payload = _build_hdhive_error(exc)
            error_payload["query_media_type"] = media_type
            error_payload["query_tmdb_id"] = tmdb_id
            status_code = 429 if error_payload.get("status_code") == 429 else 200
            return JSONResponse(error_payload, status_code=status_code)
        LOGGER.warning(f"【Admin】影巢联查失败: media_type={media_type} tmdb_id={tmdb_id} error={exc}")
        return JSONResponse({"ok": False, "msg": f"影巢查询失败: {exc}"}, status_code=500)

    items = _normalize_hdhive_items(payload)
    for item in items:
        item["poster_url"] = _poster_url(item["poster_path"])

    return JSONResponse({
        "ok": True,
        "msg": "影巢查询成功" if items else "影巢暂无资源结果",
        "count": len(items),
        "total": (payload.get("meta") or {}).get("total", len(items)),
        "query_media_type": media_type,
        "query_tmdb_id": tmdb_id,
        "items": items,
        "raw": payload.get("data"),
        "meta": payload.get("meta"),
    })


@router.post("/api/requests/{request_id}/hdhive/transfer")
async def transfer_request_hdhive(request_id: int, request: Request, admin=Depends(require_admin)):
    req = sql_get_request_by_id(request_id)
    if not req:
        return JSONResponse({"ok": False, "msg": "申请不存在"}, status_code=404)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    slug = str(body.get("slug") or "").strip()
    if not slug:
        return JSONResponse({"ok": False, "msg": "缺少资源 slug，无法转存"}, status_code=400)

    try:
        unlock_payload = await _unlock_hdhive_resource(slug)
    except Exception as exc:
        if isinstance(exc, HDHiveOpenAPIError):
            error_payload = _build_hdhive_error(exc)
            error_payload["stage"] = "unlock"
            return JSONResponse(error_payload, status_code=200)
        LOGGER.warning(f"【Admin】影巢解锁失败: slug={slug} error={exc}")
        return JSONResponse({"ok": False, "msg": f"影巢解锁失败: {exc}", "stage": "unlock"}, status_code=500)

    unlock_data = unlock_payload.get("data") if isinstance(unlock_payload, dict) else {}
    if not isinstance(unlock_data, dict):
        unlock_data = {}
    cms_share_url = str(unlock_data.get("full_url") or "").strip()
    if not cms_share_url:
        base_url = str(unlock_data.get("url") or "").strip()
        access_code = str(unlock_data.get("access_code") or "").strip()
        if base_url and access_code:
            cms_share_url = f"{base_url} 访问码:{access_code}"
        else:
            cms_share_url = base_url

    if not cms_share_url:
        return JSONResponse({"ok": False, "msg": "影巢已解锁，但未返回可转存链接", "stage": "unlock"}, status_code=500)

    is_115_share = "115" in cms_share_url.lower() or "115cdn.com" in cms_share_url.lower()
    try:
        cms_transfer = await asyncio.to_thread(_cms_add_share_download, cms_share_url)
    except Exception as exc:
        if isinstance(exc, CMSIntegrationError):
            msg = str(getattr(exc, "message", "") or "")
            if is_115_share and ("timed out" in msg.lower() or "closed connection" in msg.lower()):
                threading.Thread(
                    target=_cms_submit_share_background,
                    args=(cms_share_url,),
                    daemon=True,
                ).start()
                return JSONResponse({
                    "ok": True,
                    "msg": "115 分享已提交到 CMS 后台处理，远端响应较慢，请稍后到 CMS 转存记录确认结果",
                    "stage": "cms_transfer_pending",
                    "unlock": {
                        "already_owned": bool(unlock_data.get("already_owned")),
                        "access_code": unlock_data.get("access_code"),
                        "url": unlock_data.get("url"),
                    },
                })
            error_payload = _build_cms_error(exc)
            return JSONResponse(error_payload, status_code=200)
        if isinstance(exc, ValueError):
            return JSONResponse({"ok": False, "msg": str(exc), "stage": "cms_config"}, status_code=200)
        LOGGER.warning(f"【Admin】CMS 转存失败: slug={slug} error={exc}")
        return JSONResponse({"ok": False, "msg": f"CMS 转存失败: {exc}", "stage": "cms"}, status_code=500)

    log_audit(
        category="request",
        action="hdhive_transfer",
        source="web",
        operator_name=admin.get("username"),
        target_tg=req.tg,
        detail=f"影巢资源转存到CMS id={request_id} slug={slug} title={req.title}",
    )
    return JSONResponse({
        "ok": True,
        "msg": "已提交 CMS 转存任务",
        "stage": "completed",
        "cms_transfer": cms_transfer,
        "unlock": {
            "already_owned": bool(unlock_data.get("already_owned")),
            "access_code": unlock_data.get("access_code"),
            "url": unlock_data.get("url"),
        },
    })


@router.get("/api/requests/stats")
async def requests_stats(admin=Depends(require_admin)):
    """返回各状态数量统计"""
    await sync_all_incomplete_requests()
    return JSONResponse(sql_get_requests_stats())


@router.post("/api/requests/sync_status")
async def sync_requests_status(admin=Depends(require_admin)):
    """手动触发一次真实状态同步，以 Emby 实际入库结果为准。"""
    synced = await sync_all_incomplete_requests()
    stats = sql_get_requests_stats()
    log_audit(
        category="request",
        action="sync_status",
        source="web",
        operator_name=admin.get("username"),
        detail=f"手动刷新求片真实状态，同步 {synced} 条申请",
    )
    return JSONResponse({
        "ok": True,
        "msg": f"已完成真实状态刷新，本次同步 {synced} 条申请",
        "synced": synced,
        "stats": stats,
    })


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
    pending_tmdb_ids = [
        str(item.get("tmdb_id") or "")
        for item in (data.get("items") or [])
        if item.get("status") in {"pending", "processing", "rejected"} and item.get("tmdb_id")
    ]
    if pending_tmdb_ids:
        synced = await sync_pending_requests_by_tmdb_ids(pending_tmdb_ids)
        if synced:
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
        await send_request_completed_notification(
            chat_id=req.tg,
            title=req.title or "",
            year=req.year or "",
            media_type=req.media_type or "",
            tmdb_id=req.tmdb_id or "",
            note=note,
            poster_url=req.poster or "",
        )
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

            # approve 不通知；complete / reject 才发送最终结果通知
            if body.action == "complete":
                try:
                    await send_request_completed_notification(
                        chat_id=req.tg,
                        title=req.title or "",
                        year=req.year or "",
                        media_type=req.media_type or "",
                        tmdb_id=req.tmdb_id or "",
                        note=body.note,
                        poster_url=req.poster or "",
                    )
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
