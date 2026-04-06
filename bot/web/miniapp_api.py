"""
MiniApp FastAPI 路由
- GET  /miniapp/            返回 miniapp.html 页面
- POST /miniapp/auth        验证 Telegram initData，返回用户信息
- GET  /miniapp/profile     返回当前用户 Emby 账号信息
- GET  /miniapp/my_stats    返回 Emby 播放统计（播放次数/沉浸时长/均次/最爱影片）
- GET  /miniapp/search      TMDB 搜索
- GET  /miniapp/trending    TMDB 热门内容
- GET  /miniapp/my_status   返回该用户所有申请的 {tmdb_id: status} 字典
- GET  /miniapp/requests    用户求片列表
- POST /miniapp/requests    提交求片
"""
import hashlib
import hmac
import json
import os
import random
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote, parse_qsl

import aiohttp
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from bot import bot_token, tmdb_api_key, emby_url, emby_api, sakura_b, LOGGER, _open
from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_miniapp import (
    sql_add_request, sql_get_requests_by_tg, sql_get_requests_status_map,
    sql_get_request_by_id, sql_count_requests_in_period,
)
from bot.web.miniapp_notify import check_in_emby_by_tmdb

router = APIRouter(prefix="/miniapp", tags=["MiniApp"])

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w300"

# ── HTML 页面 ──────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "miniapp.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/checkin_app", response_class=HTMLResponse)
async def serve_checkin_miniapp():
    """独立签到 MiniApp 页面"""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "checkin_miniapp.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ── initData 验签 ──────────────────────────────────────────────────────────────

def verify_telegram_init_data(init_data: str) -> dict:
    try:
        params = dict(parse_qsl(init_data, strict_parsing=False))
        received_hash = params.pop("hash", None)
        if not received_hash:
            raise HTTPException(status_code=401, detail="Missing hash in initData")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            raise HTTPException(status_code=403, detail="Invalid initData signature")
        return json.loads(unquote(params.get("user", "{}")))
    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"【MiniApp】initData 验签异常: {e}")
        raise HTTPException(status_code=400, detail="Failed to parse initData")


def _get_tg_user(request: Request) -> dict:
    init_data = request.headers.get("X-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing X-Init-Data header")
    return verify_telegram_init_data(init_data)


# ── 用户认证 & 画像 ────────────────────────────────────────────────────────────

@router.post("/auth")
async def miniapp_auth(request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户，请先在 Bot 中注册"})
    lv_map = {"a": "白名单", "b": "普通用户", "e": "公益用户", "c": "已封禁", "d": "未注册"}
    ex_str = e.ex.strftime("%Y-%m-%d") if e.ex else "无期限"
    days_left = (e.ex - __import__('datetime').datetime.now()).days if e.ex else None
    return JSONResponse({
        "ok": True,
        "tg_id": tg_id,
        "tg_name": tg_user.get("first_name", ""),
        "emby_name": e.name,
        "emby_id": e.embyid,
        "level": e.lv,
        "level_name": lv_map.get(e.lv, e.lv),
        "credits": e.iv or 0,
        "credits_unit": sakura_b or "pts",
        "expire": ex_str,
        "days_left": days_left,
        "has_account": bool(e.embyid),
    })


@router.get("/profile")
async def miniapp_profile(request: Request):
    return await miniapp_auth(request)


# ── TMDB 搜索 ──────────────────────────────────────────────────────────────────

@router.get("/search")
async def miniapp_search(q: str = "", request: Request = None):
    _get_tg_user(request)
    if not q.strip():
        return JSONResponse({"results": []})
    if not tmdb_api_key:
        return JSONResponse({"results": [], "error": "TMDB未配置"})
    url = f"{TMDB_BASE}/search/multi"
    params = {"api_key": tmdb_api_key, "query": q, "language": "zh-CN", "include_adult": "false", "page": 1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return JSONResponse({"results": [], "error": "TMDB请求失败"})
                data = await resp.json()
    except Exception:
        return JSONResponse({"results": [], "error": "TMDB网络不可达"})
    results = []
    for item in data.get("results", [])[:20]:
        media_type = item.get("media_type")
        if media_type not in ("movie", "tv"):
            continue
        poster = item.get("poster_path")
        results.append({
            "tmdb_id": str(item.get("id")),
            "media_type": media_type,
            "title": item.get("title") or item.get("name", ""),
            "orig_title": item.get("original_title") or item.get("original_name", ""),
            "poster": f"{TMDB_IMAGE_BASE}{poster}" if poster else "",
            "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
            "overview": item.get("overview", ""),
            "vote": round(item.get("vote_average", 0), 1),
        })
    return JSONResponse({"results": results})


@router.get("/trending")
async def miniapp_trending(request: Request):
    _get_tg_user(request)
    if not tmdb_api_key:
        raise HTTPException(status_code=503, detail="TMDB API key not configured")
    url = f"{TMDB_BASE}/trending/all/week"
    params = {"api_key": tmdb_api_key, "language": "zh-CN"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=502, detail="TMDB API error")
            data = await resp.json()
    results = []
    for item in data.get("results", [])[:20]:
        media_type = item.get("media_type")
        if media_type not in ("movie", "tv"):
            continue
        poster = item.get("poster_path")
        results.append({
            "tmdb_id": str(item.get("id")),
            "media_type": media_type,
            "title": item.get("title") or item.get("name", ""),
            "orig_title": item.get("original_title") or item.get("original_name", ""),
            "poster": f"{TMDB_IMAGE_BASE}{poster}" if poster else "",
            "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
            "vote": round(item.get("vote_average", 0), 1),
            "overview": item.get("overview", ""),
        })
    return JSONResponse({"results": results})


# ── 求片 ───────────────────────────────────────────────────────────────────────

class RequestBody(BaseModel):
    tmdb_id: str
    media_type: str
    title: str
    orig_title: str = ""
    poster: str = ""
    year: str = ""
    overview: str = ""
    vote: float = 0
    user_note: str = ""


class CheckLibraryBody(BaseModel):
    tmdb_ids: list


@router.get("/my_status")
async def miniapp_my_status(request: Request):
    """返回当前用户所有申请的 {tmdb_id: status} 字典，供前端初始化按钮状态"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    status_map = sql_get_requests_status_map(tg_id)
    return JSONResponse({"status_map": status_map})


@router.get("/requests")
async def miniapp_list_requests(request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    rows = sql_get_requests_by_tg(tg_id)
    return JSONResponse({"requests": rows})


@router.get("/requests/{request_id}")
async def miniapp_get_request(request_id: int, request: Request):
    """获取单条申请详情（含用户备注和管理员备注）"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    req = sql_get_request_by_id(request_id)
    if not req or req.tg != tg_id:
        raise HTTPException(status_code=404, detail="申请不存在")
    from bot.sql_helper.sql_miniapp import _request_to_dict
    return JSONResponse(_request_to_dict(req))


@router.post("/requests")
async def miniapp_submit_request(body: RequestBody, request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")

    e = sql_get_emby(tg=tg_id)
    if not e or not e.embyid:
        raise HTTPException(status_code=403, detail="请先在 Bot 中注册 Emby 账户")

    # 求片额度检查
    quota_map = {
        'a': getattr(_open, 'request_quota_a', 999),
        'b': getattr(_open, 'request_quota_b', 10),
        'e': getattr(_open, 'request_quota_e', 5),
    }
    quota = quota_map.get(e.lv, getattr(_open, 'request_quota_e', 5))
    if quota == 0:
        raise HTTPException(status_code=403, detail="您的账号等级暂不支持求片功能")
    reset_days = getattr(_open, 'request_quota_days', 30)
    count_in_period = sql_count_requests_in_period(tg_id, reset_days)
    if count_in_period >= quota:
        raise HTTPException(status_code=429, detail=f"求片额度已用完，每{reset_days}天最多求片{quota}部（已提交{count_in_period}部）")

    # 提交前先检查 Emby 媒体库，若已入库直接返回（适用于所有用户）
    if body.tmdb_id:
        already_in_library = await check_in_emby_by_tmdb(body.tmdb_id)
        if already_in_library:
            return JSONResponse({"ok": False, "status": "completed", "msg": "该影片已入库，可直接前往 Emby 观看 🎉"})

    result = sql_add_request(
        tg=tg_id,
        tmdb_id=body.tmdb_id,
        media_type=body.media_type,
        title=body.title,
        orig_title=body.orig_title,
        poster=body.poster,
        year=body.year,
        user_note=body.user_note,
    )

    if result == "completed":
        return JSONResponse({"ok": False, "status": "completed", "msg": "该影片已入库，可直接前往 Emby 观看 🎉"})
    if result is None:
        return JSONResponse({"ok": False, "status": "duplicate", "msg": "您已提交过该影片的申请，请勿重复提交"})
    return JSONResponse({"ok": True, "status": "pending", "msg": "申请已提交，审核通过后将通过 Bot 通知您", "id": result.id})


async def _query_emby_stats(emby_id: str) -> dict:
    """向 Emby PlaybackActivity 查询用户播放统计"""
    if not emby_url or not emby_api:
        return {}
    if not re.match(r'^[a-fA-F0-9\-]+$', emby_id):
        return {}
    api_url = f"{emby_url.rstrip('/')}/emby/user_usage_stats/submit_custom_query"
    # 总播放量 + 总时长 + 最早播放日期
    sql_summary = (
        f"SELECT COUNT(1) AS play_count, "
        f"SUM(CASE WHEN PlayDuration > PauseDuration THEN PlayDuration - PauseDuration ELSE PlayDuration END) AS total_seconds, "
        f"MIN(DateCreated) AS first_play "
        f"FROM PlaybackActivity WHERE UserId = '{emby_id}' AND PlayDuration > 0"
    )
    # 最多播放的一部作品
    sql_top = (
        f"SELECT ItemId, ItemName, ItemType, COUNT(1) AS cnt, "
        f"SUM(CASE WHEN PlayDuration > PauseDuration THEN PlayDuration - PauseDuration ELSE PlayDuration END) AS secs "
        f"FROM PlaybackActivity WHERE UserId = '{emby_id}' AND PlayDuration > 0 "
        f"GROUP BY ItemId, ItemName, ItemType ORDER BY cnt DESC, secs DESC LIMIT 1"
    )
    result = {}
    try:
        async with aiohttp.ClientSession() as session:
            # 查询汇总
            async with session.post(
                api_url,
                params={"api_key": emby_api},
                json={"CustomQueryString": sql_summary, "ReplaceUserId": False},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    rows = data.get("results", [])
                    if rows:
                        r = rows[0]
                        result["play_count"] = int(r[0] or 0)
                        total_sec = float(r[1] or 0)
                        result["total_hours"] = round(total_sec / 3600, 1)
                        result["avg_minutes"] = round(total_sec / max(int(r[0] or 1), 1) / 60, 1)
                        result["first_play"] = r[2] or ""
            # 查询最爱
            async with session.post(
                api_url,
                params={"api_key": emby_api},
                json={"CustomQueryString": sql_top, "ReplaceUserId": False},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    rows = data.get("results", [])
                    if rows:
                        r = rows[0]
                        item_id = r[0] or ""
                        poster_url = ""
                        if item_id and emby_url:
                            poster_url = f"{emby_url.rstrip('/')}/emby/Items/{item_id}/Images/Primary?maxHeight=300&api_key={emby_api}"
                        result["top_item"] = {
                            "id": item_id,
                            "name": r[1] or "",
                            "type": r[2] or "",
                            "play_count": int(r[3] or 0),
                            "hours": round(float(r[4] or 0) / 3600, 1),
                            "poster_url": poster_url,
                        }
    except Exception as e:
        LOGGER.warning(f"【MiniApp】查询Emby播放统计失败: {e}")
    return result


@router.get("/my_stats")
async def miniapp_my_stats(request: Request):
    """返回当前用户的 Emby 播放统计数据"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e or not e.embyid:
        return JSONResponse({"ok": True, "stats": None})
    stats = await _query_emby_stats(str(e.embyid))
    return JSONResponse({"ok": True, "stats": stats})


@router.post("/check_library")
async def miniapp_check_library(body: CheckLibraryBody, request: Request):
    """批量检查多个 TMDB ID 是否已在 Emby 入库，返回 {tmdb_id: bool}"""
    _get_tg_user(request)
    tmdb_ids = [str(i) for i in (body.tmdb_ids or []) if i][:30]  # 最多 30 个
    result = {}
    for tmdb_id in tmdb_ids:
        result[tmdb_id] = await check_in_emby_by_tmdb(tmdb_id)
    return JSONResponse({"library_map": result})


# ── 签到 ───────────────────────────────────────────────────────────────────────

@router.get("/checkin_status")
async def miniapp_checkin_status(request: Request):
    """查询当前用户今日签到状态"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"enabled": False, "checked": False})
    enabled = bool(getattr(_open, 'checkin', False))
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    checked = bool(e.ch and e.ch.strftime("%Y-%m-%d") >= today)
    reward_range = getattr(_open, 'checkin_reward', [1, 10])
    return JSONResponse({
        "enabled": enabled,
        "checked": checked,
        "credits": e.iv or 0,
        "unit": sakura_b or "pts",
        "reward_min": reward_range[0] if isinstance(reward_range, list) else 1,
        "reward_max": reward_range[1] if isinstance(reward_range, list) else 10,
    })


@router.post("/checkin")
async def miniapp_checkin(request: Request):
    """MiniApp 签到（前端滑动验证通过后调用）"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")

    if not getattr(_open, 'checkin', False):
        return JSONResponse({"ok": False, "msg": "签到功能未开启"})

    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户信息"})

    checkin_lv = getattr(_open, 'checkin_lv', None)
    if checkin_lv:
        from bot.func_helper.utils import lv_allowed
        if not lv_allowed(e.lv, checkin_lv):
            return JSONResponse({"ok": False, "msg": "您的账号等级暂无签到权限"})

    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    if e.ch and e.ch.strftime("%Y-%m-%d") >= today:
        return JSONResponse({"ok": False, "already": True, "msg": "今日已签到，明天再来吧 ⭕"})

    reward_range = getattr(_open, 'checkin_reward', [1, 10])
    if isinstance(reward_range, list) and len(reward_range) >= 2:
        reward = random.randint(int(reward_range[0]), int(reward_range[1]))
    else:
        reward = 5
    s = (e.iv or 0) + reward
    sql_update_emby(Emby.tg == tg_id, iv=s, ch=now)
    log_audit(
        category="credits", action="checkin", source="web",
        target_tg=tg_id,
        target_name=tg_user.get("first_name", ""),
        before_val=str(e.iv or 0), after_val=str(s),
        detail=f"MiniApp签到获得 +{reward}，累计 {s}",
    )
    unit = sakura_b or "pts"
    return JSONResponse({
        "ok": True,
        "reward": reward,
        "total": s,
        "unit": unit,
        "msg": f"签到成功！获得 +{reward} {unit} 🎉",
    })
