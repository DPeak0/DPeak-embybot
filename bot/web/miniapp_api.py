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
import asyncio
import hashlib
import hmac
import json
import random
import re
import time
import unicodedata
from calendar import monthrange
from datetime import datetime, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, parse_qsl, quote
from typing import Dict, Optional, Tuple

import aiohttp
from cacheout import Cache
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from bot import bot_token, emby_url, emby_api, sakura_b, LOGGER, _open, config
from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
from bot.sql_helper.sql_audit import get_user_checkin_logs, log_audit
from bot.sql_helper.sql_miniapp import (
    sql_add_request, sql_get_requests_by_tg, sql_get_requests_status_map,
    sql_get_request_by_id, sql_count_requests_in_period,
)
from bot.web.miniapp_notify import (
    bulk_check_in_emby_by_tmdb,
    check_in_emby_by_tmdb,
    sync_pending_requests_by_tmdb_ids,
)

router = APIRouter(prefix="/miniapp", tags=["MiniApp"])

TMDB_BASE = "https://api.tmdb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w300"
TMDB_SEARCH_TTL = 600
TMDB_TRENDING_TTL = 1800
TMDB_MIN_QUERY_LENGTH = 2
TMDB_IMAGE_TTL = 604800
_tmdb_cache: Dict[str, Tuple[float, dict]] = {}
_tmdb_image_cache = Cache(maxsize=512, ttl=TMDB_IMAGE_TTL)
_TEMPLATE_DIR = Path(__file__).with_name("templates")
_STATIC_HTML_CACHE_CONTROL = "public, max-age=300"


@lru_cache(maxsize=8)
def _read_template_cached(filename: str) -> str:
    return (_TEMPLATE_DIR / filename).read_text(encoding="utf-8")


def _render_static_html(filename: str, *, cache_control: Optional[str] = None, use_cache: bool = True) -> HTMLResponse:
    return HTMLResponse(
        content=_read_template_cached(filename) if use_cache else (_TEMPLATE_DIR / filename).read_text(encoding="utf-8"),
        headers={"Cache-Control": cache_control or _STATIC_HTML_CACHE_CONTROL},
    )

# ── HTML 页面 ──────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def serve_miniapp():
    return _render_static_html("miniapp.html")


@router.get("/checkin_app", response_class=HTMLResponse)
async def serve_checkin_miniapp():
    """独立签到 MiniApp 页面"""
    return _render_static_html("checkin_miniapp.html", cache_control="no-store", use_cache=False)


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


def _get_request_quota_info(e, tg_id: int) -> dict:
    quota_map = {
        'a': getattr(_open, 'request_quota_a', 999),
        'b': getattr(_open, 'request_quota_b', 10),
        'e': getattr(_open, 'request_quota_e', 5),
    }
    quota = int(quota_map.get(e.lv, getattr(_open, 'request_quota_e', 5)) or 0)
    reset_days = int(getattr(_open, 'request_quota_days', 30) or 30)
    used = sql_count_requests_in_period(tg_id, reset_days) if quota > 0 else 0
    remaining = max(quota - used, 0) if quota > 0 else 0
    request_credit_cost = max(int(getattr(_open, 'request_credit_cost', 0) or 0), 0)
    return {
        "request_quota": quota,
        "request_quota_used": used,
        "request_quota_remaining": remaining,
        "request_quota_reset_days": reset_days,
        "request_credit_cost": request_credit_cost,
    }


def _build_auth_payload(tg_user: dict, e) -> dict:
    lv_map = {"a": "白名单", "b": "普通用户", "e": "公益用户", "c": "已封禁", "d": "未注册"}
    ex_str = e.ex.strftime("%Y-%m-%d") if e.ex else "无期限"
    days_left = (e.ex - __import__('datetime').datetime.now()).days if e.ex else None
    quota_info = _get_request_quota_info(e, int(tg_user.get("id") or 0))
    return {
        "ok": True,
        "tg_id": tg_user.get("id"),
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
        **quota_info,
    }


def _build_checkin_auth_payload(tg_user: dict, e) -> dict:
    lv_map = {"a": "白名单", "b": "普通用户", "e": "公益用户", "c": "已封禁", "d": "未注册"}
    return {
        "ok": True,
        "tg_id": tg_user.get("id"),
        "tg_name": tg_user.get("first_name", ""),
        "emby_name": e.name,
        "level": e.lv,
        "level_name": lv_map.get(e.lv, e.lv),
        "has_account": bool(e.embyid),
    }


def _now_local() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def _parse_checkin_reward_from_detail(detail: str) -> int:
    match = re.search(r"\+(\d+)", str(detail or ""))
    return int(match.group(1)) if match else 0


def _parse_checkin_total_from_detail(detail: str) -> int:
    match = re.search(r"累计\s*(\d+)", str(detail or ""))
    return int(match.group(1)) if match else 0


def _calc_checkin_streak(check_dates: list[str], today_str: str) -> int:
    date_set = set(check_dates or [])
    if not date_set:
        return 0
    cursor = datetime.strptime(today_str, "%Y-%m-%d").date()
    if today_str not in date_set:
        cursor = cursor - timedelta(days=1)
    streak = 0
    while cursor.strftime("%Y-%m-%d") in date_set:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def _calc_max_checkin_streak(check_dates: list[str]) -> int:
    unique_dates = sorted(set(date_str for date_str in (check_dates or []) if date_str))
    if not unique_dates:
        return 0
    dates = [datetime.strptime(date_str, "%Y-%m-%d").date() for date_str in unique_dates]
    max_streak = 1
    streak = 1
    for idx in range(1, len(dates)):
        if (dates[idx] - dates[idx - 1]).days == 1:
            streak += 1
        else:
            max_streak = max(max_streak, streak)
            streak = 1
    return max(max_streak, streak)


def _resolve_checkin_month(month_value: str = "") -> tuple[int, int]:
    now = _now_local()
    raw = str(month_value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        year = int(raw[:4])
        month = int(raw[5:7])
        if 1 <= month <= 12:
            return year, month
    return now.year, now.month


def _build_checkin_overview_payload(tg_id: int, month_value: str = "") -> dict:
    now = _now_local()
    today_str = now.strftime("%Y-%m-%d")
    year, month = _resolve_checkin_month(month_value)
    days_in_month = monthrange(year, month)[1]
    records = get_user_checkin_logs(target_tg=tg_id, days=3650, limit=5000)

    normalized_records = []
    recent_dates = []
    monthly_dates = []
    monthly_reward = 0
    for row in records:
        created_at = row.get("created_at", "")
        date_str = created_at[:10] if created_at else ""
        reward = _parse_checkin_reward_from_detail(row.get("detail", ""))
        total = _parse_checkin_total_from_detail(row.get("detail", ""))
        item = {
            "date": date_str,
            "time": created_at[11:16] if len(created_at) >= 16 else "",
            "reward": reward,
            "total": total,
            "source": row.get("source", ""),
            "created_at": created_at,
        }
        normalized_records.append(item)
        if date_str:
            recent_dates.append(date_str)
        if date_str.startswith(f"{year:04d}-{month:02d}"):
            monthly_dates.append(date_str)
            monthly_reward += reward

    unique_recent_dates = sorted(set(recent_dates))
    unique_monthly_dates = sorted(set(monthly_dates))
    today_day = now.day
    checked_days = [int(date_str[-2:]) for date_str in unique_monthly_dates]
    checked_count = len(checked_days)
    month_completion = int(round((checked_count / days_in_month) * 100)) if days_in_month else 0
    current_streak = _calc_checkin_streak(unique_recent_dates, today_str)
    max_monthly_streak = _calc_max_checkin_streak(unique_monthly_dates)
    monthly_records = [item for item in normalized_records if item["date"].startswith(f"{year:04d}-{month:02d}")]

    return {
        "month": f"{year:04d}-{month:02d}",
        "month_label": f"{year}年{month}月",
        "today": today_str,
        "checked_days": checked_days,
        "stats": {
            "checked_count": checked_count,
            "missed_count": max(today_day - checked_count, 0),
            "remaining_days": max(days_in_month - today_day, 0),
            "current_streak": current_streak,
            "max_streak": max_monthly_streak,
            "reward_total": monthly_reward,
            "completion_rate": min(max(month_completion, 0), 100),
        },
        "records": monthly_records,
    }


def _build_checkin_status_payload(e) -> dict:
    enabled = bool(getattr(_open, 'checkin', False))
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    checked = bool(e.ch and e.ch.strftime("%Y-%m-%d") >= today)
    reward_range = getattr(_open, 'checkin_reward', [1, 10])
    return {
        "enabled": enabled,
        "checked": checked,
        "credits": e.iv or 0,
        "unit": sakura_b or "pts",
        "reward_min": reward_range[0] if isinstance(reward_range, list) else 1,
        "reward_max": reward_range[1] if isinstance(reward_range, list) else 10,
    }


def _get_tmdb_api_key() -> str:
    return (getattr(config, "tmdb_api_key", "") or "").strip()


def _normalize_tmdb_query(query: str) -> str:
    text = unicodedata.normalize("NFKC", str(query or ""))
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def _split_tmdb_query_year(query: str) -> Tuple[str, str]:
    normalized = _normalize_tmdb_query(query)
    if not normalized:
        return "", ""
    match = re.search(r"(?:^|[\s\[(（【-])((?:19|20)\d{2})[\])）】\s-]*$", normalized)
    if not match:
        return normalized, ""
    year = match.group(1)
    title = normalized[:match.start(1)]
    title = re.sub(r"[\s\[(（【-]+$", "", title).strip()
    return title or normalized, year


def _build_tmdb_search_context(query: str) -> dict:
    normalized = _normalize_tmdb_query(query)
    title, year = _split_tmdb_query_year(normalized)
    compact_title = re.sub(r"[\s\-_:：·•'\"`.,，!！?？/\\|+~()\[\]{}<>《》【】]+", "", title).lower()
    cache_title = compact_title or re.sub(r"\s+", "", normalized).lower()
    cache_key = f"{cache_title}:y{year or '0'}"
    request_query = f"{title} {year}".strip() if year else title
    request_query = re.sub(r"\s+", " ", request_query).strip()
    return {
        "normalized_query": normalized,
        "normalized_title": title,
        "normalized_year": year,
        "cache_key": cache_key,
        "request_query": request_query,
    }


def _tmdb_cache_get(cache_key: str, *, allow_stale: bool = False) -> Optional[dict]:
    cached = _tmdb_cache.get(cache_key)
    if not cached:
        return None
    expires_at, data = cached
    if allow_stale or expires_at > time.time():
        return data
    _tmdb_cache.pop(cache_key, None)
    return None


def _tmdb_cache_set(cache_key: str, data: dict, ttl: int) -> None:
    _tmdb_cache[cache_key] = (time.time() + max(ttl, 1), data)


async def _tmdb_get_json(path: str, params: dict, *, cache_key: str, ttl: int, force_refresh: bool = False) -> Optional[dict]:
    cached = None if force_refresh else _tmdb_cache_get(cache_key)
    if cached is not None:
        return cached

    stale = _tmdb_cache_get(cache_key, allow_stale=True)
    url = f"{TMDB_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return stale
                data = await resp.json()
                _tmdb_cache_set(cache_key, data, ttl)
                return data
    except Exception:
        return stale


def _tmdb_image_url(poster_path: str, width: int = 300) -> str:
    if not poster_path:
        return ""
    safe_width = min(max(int(width or 300), 92), 780)
    return f"/miniapp/tmdb_image?path={quote(str(poster_path), safe='')}&w={safe_width}"


async def _fetch_tmdb_image_bytes(poster_path: str, width: int = 300) -> Optional[Tuple[bytes, str]]:
    if not poster_path:
        return None
    safe_width = min(max(int(width or 300), 92), 780)
    cache_key = f"tmdb:image:{safe_width}:{poster_path}"
    cached = _tmdb_image_cache.get(cache_key)
    if cached:
        return cached

    url = f"https://image.tmdb.org/t/p/w{safe_width}{poster_path}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status != 200:
                    return None
                content = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                payload = (content, content_type)
                _tmdb_image_cache.set(cache_key, payload, ttl=TMDB_IMAGE_TTL)
                return payload
    except Exception as e:
        LOGGER.warning(f"【MiniApp】TMDB海报拉取失败 path={poster_path} w={safe_width}: {e}")
        return None


async def _prefetch_tmdb_images_from_results(data: dict, limit: int = 12, width: int = 300) -> int:
    poster_paths = []
    for item in (data or {}).get("results", [])[: max(limit, 0)]:
        poster_path = item.get("poster_path")
        if poster_path:
            poster_paths.append(str(poster_path))
    warmed = 0
    for poster_path in poster_paths:
        if await _fetch_tmdb_image_bytes(poster_path, width=width):
            warmed += 1
    return warmed


async def prewarm_tmdb_hot_cache(force_refresh: bool = True) -> dict:
    """预热热门内容缓存，并顺带预取部分海报，降低首屏命中 TMDB 的频率。"""
    tmdb_api_key = _get_tmdb_api_key()
    if not tmdb_api_key:
        return {"ok": False, "reason": "tmdb_api_key_missing"}
    params = {"api_key": tmdb_api_key, "language": "zh-CN"}
    cache_key = "tmdb:trending:all:week:zh-CN"
    data = await _tmdb_get_json("/trending/all/week", params, cache_key=cache_key, ttl=TMDB_TRENDING_TTL, force_refresh=force_refresh)
    if data is None:
        return {"ok": False, "reason": "tmdb_unreachable"}
    results = _format_tmdb_results(data)
    warmed_images = await _prefetch_tmdb_images_from_results(data, limit=12, width=300)
    LOGGER.info(f"【MiniApp】TMDB热门缓存预热完成，结果 {len(results)} 条，海报预热 {warmed_images} 张")
    return {"ok": True, "results": len(results), "warmed_images": warmed_images}


def _format_tmdb_results(data: dict, *, include_overview: bool = True) -> list:
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
            "poster": _tmdb_image_url(poster, 300) if poster else "",
            "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
            "overview": item.get("overview", "") if include_overview else "",
            "vote": round(item.get("vote_average", 0), 1),
        })
    return results


async def _get_trending_payload() -> dict:
    tmdb_api_key = _get_tmdb_api_key()
    if not tmdb_api_key:
        return {"results": [], "error": "TMDB未配置"}
    params = {"api_key": tmdb_api_key, "language": "zh-CN"}
    cache_key = "tmdb:trending:all:week:zh-CN"
    data = await _tmdb_get_json("/trending/all/week", params, cache_key=cache_key, ttl=TMDB_TRENDING_TTL)
    if data is None:
        return {"results": [], "error": "TMDB网络不可达"}
    return {"results": _format_tmdb_results(data)}


async def _load_request_status_map(tg_id: int, *, sync_pending: bool) -> dict:
    status_map = sql_get_requests_status_map(tg_id)
    if not sync_pending:
        return status_map
    pending_tmdb_ids = [tmdb_id for tmdb_id, status in status_map.items() if status in {"pending", "processing", "rejected"}]
    if pending_tmdb_ids:
        synced = await sync_pending_requests_by_tmdb_ids(pending_tmdb_ids)
        if synced:
            status_map = sql_get_requests_status_map(tg_id)
    return status_map


# ── 用户认证 & 画像 ────────────────────────────────────────────────────────────

@router.post("/auth")
async def miniapp_auth(request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户，请先在 Bot 中注册"})
    return JSONResponse(_build_auth_payload(tg_user, e))


@router.get("/profile")
async def miniapp_profile(request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户，请先在 Bot 中注册"})
    return JSONResponse(_build_auth_payload(tg_user, e))


@router.post("/bootstrap")
async def miniapp_bootstrap(request: Request):
    """首屏启动数据：合并用户资料、当前申请状态与热门内容，减少页面冷启动往返。"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户，请先在 Bot 中注册", "status_map": {}, "trending": []})

    status_map, trending_payload = await asyncio.gather(
        _load_request_status_map(tg_id, sync_pending=False),
        _get_trending_payload(),
    )
    payload = _build_auth_payload(tg_user, e)
    payload["status_map"] = status_map
    payload["trending"] = trending_payload.get("results", [])
    payload["trending_error"] = trending_payload.get("error", "")
    return JSONResponse(payload)


# ── TMDB 搜索 ──────────────────────────────────────────────────────────────────

@router.get("/search")
async def miniapp_search(q: str = "", request: Request = None):
    _get_tg_user(request)
    search_ctx = _build_tmdb_search_context(q)
    normalized_q = search_ctx["normalized_query"]
    if not normalized_q:
        return JSONResponse({"results": []})
    if len(search_ctx["normalized_title"] or normalized_q) < TMDB_MIN_QUERY_LENGTH:
        return JSONResponse({"results": [], "hint": f"请至少输入 {TMDB_MIN_QUERY_LENGTH} 个字符后再搜索"})
    tmdb_api_key = _get_tmdb_api_key()
    if not tmdb_api_key:
        return JSONResponse({"results": [], "error": "TMDB未配置"})
    params = {
        "api_key": tmdb_api_key,
        "query": search_ctx["request_query"],
        "language": "zh-CN",
        "include_adult": "false",
        "page": 1,
    }
    cache_key = f"tmdb:search:zh-CN:{search_ctx['cache_key']}"
    data = await _tmdb_get_json("/search/multi", params, cache_key=cache_key, ttl=TMDB_SEARCH_TTL)
    if data is None:
        return JSONResponse({"results": [], "error": "TMDB网络不可达"})
    return JSONResponse({"results": _format_tmdb_results(data)})


@router.get("/trending")
async def miniapp_trending(request: Request):
    _get_tg_user(request)
    payload = await _get_trending_payload()
    if payload.get("error") == "TMDB未配置":
        return JSONResponse({"results": [], "error": "TMDB未配置"})
    if payload.get("error") == "TMDB网络不可达":
        return JSONResponse({"results": [], "error": "TMDB网络不可达"})
    return JSONResponse(payload)


@router.get("/tmdb_image")
async def miniapp_tmdb_image(path: str = "", w: int = 300):
    """TMDB 海报代理缓存，避免前端每次直接请求 TMDB 图片域名。"""
    poster_path = str(path or "").strip()
    if not poster_path.startswith("/"):
        return Response(status_code=404)
    payload = await _fetch_tmdb_image_bytes(poster_path, width=w)
    if not payload:
        return Response(status_code=404)
    content, content_type = payload
    return Response(
        content=content,
        media_type=content_type or "image/jpeg",
        headers={"Cache-Control": f"public, max-age={TMDB_IMAGE_TTL}"},
    )


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
    status_map = await _load_request_status_map(tg_id, sync_pending=True)
    return JSONResponse({"status_map": status_map})


@router.get("/requests")
async def miniapp_list_requests(request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    rows = sql_get_requests_by_tg(tg_id)
    pending_tmdb_ids = [str(row.get("tmdb_id") or "") for row in rows if row.get("status") in {"pending", "processing", "rejected"} and row.get("tmdb_id")]
    if pending_tmdb_ids:
        synced = await sync_pending_requests_by_tmdb_ids(pending_tmdb_ids)
        if synced:
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
    if req.tmdb_id and req.status in {"pending", "processing", "rejected"}:
        synced = await sync_pending_requests_by_tmdb_ids([req.tmdb_id])
        if synced:
            req = sql_get_request_by_id(request_id)
    from bot.sql_helper.sql_miniapp import _request_to_dict
    return JSONResponse(_request_to_dict(req))


@router.post("/requests")
async def miniapp_submit_request(body: RequestBody, request: Request):
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")

    e = sql_get_emby(tg=tg_id)
    if not e or not e.embyid:
        raise HTTPException(status_code=403, detail="请先在 Bot 中注册 Emby 账户")

    quota_info = _get_request_quota_info(e, tg_id)
    quota = quota_info["request_quota"]
    if quota == 0:
        raise HTTPException(status_code=403, detail="您的账号等级暂不支持求片功能")
    reset_days = quota_info["request_quota_reset_days"]
    count_in_period = quota_info["request_quota_used"]
    if count_in_period >= quota:
        raise HTTPException(status_code=429, detail=f"求片额度已用完，每{reset_days}天最多求片{quota}部（已提交{count_in_period}部）")
    request_credit_cost = quota_info["request_credit_cost"]
    if request_credit_cost > 0 and (e.iv or 0) < request_credit_cost:
        raise HTTPException(status_code=403, detail=f"石子不足，当前求片需要消耗 {request_credit_cost} {sakura_b}")

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

    new_credits = e.iv or 0
    if request_credit_cost > 0:
        new_credits = max((e.iv or 0) - request_credit_cost, 0)
        sql_update_emby(Emby.tg == tg_id, iv=new_credits)
        log_audit(
            category="credits",
            action="miniapp_request",
            source="miniapp",
            operator_name=str(tg_id),
            target_tg=tg_id,
            before_val=str(e.iv or 0),
            after_val=str(new_credits),
            detail=f"MiniApp 求片消耗 {request_credit_cost}{sakura_b}：《{body.title}》",
        )

    return JSONResponse({
        "ok": True,
        "status": "pending",
        "msg": "申请已提交，处理结果将通过 Bot 通知您",
        "id": result.id,
        "request_quota_remaining": max(quota - count_in_period - 1, 0),
        "request_quota_used": count_in_period + 1,
        "request_quota": quota,
        "request_quota_reset_days": reset_days,
        "request_credit_cost": request_credit_cost,
        "credits": new_credits,
        "credits_unit": sakura_b or "pts",
    })


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

    async def _run_query(session: aiohttp.ClientSession, sql: str):
        async with session.post(
            api_url,
            params={"api_key": emby_api},
            json={"CustomQueryString": sql, "ReplaceUserId": False},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)
            return data.get("results", [])

    try:
        async with aiohttp.ClientSession() as session:
            summary_rows, top_rows = await asyncio.gather(
                _run_query(session, sql_summary),
                _run_query(session, sql_top),
            )
            if summary_rows:
                r = summary_rows[0]
                result["play_count"] = int(r[0] or 0)
                total_sec = float(r[1] or 0)
                result["total_hours"] = round(total_sec / 3600, 1)
                result["avg_minutes"] = round(total_sec / max(int(r[0] or 1), 1) / 60, 1)
                result["first_play"] = r[2] or ""
            if top_rows:
                r = top_rows[0]
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
    result = await bulk_check_in_emby_by_tmdb(tmdb_ids)
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
    return JSONResponse(_build_checkin_status_payload(e))


@router.get("/checkin_bootstrap")
@router.post("/checkin_bootstrap")
async def miniapp_checkin_bootstrap(request: Request):
    """签到页首屏启动数据：合并认证、状态与当月概览，减少冷启动往返。"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({
            "ok": False,
            "msg": "未找到账户信息",
            "auth": None,
            "status": {"enabled": False, "checked": False},
            "overview": None,
        })
    return JSONResponse({
        "ok": True,
        "auth": _build_checkin_auth_payload(tg_user, e),
        "status": _build_checkin_status_payload(e),
        "overview": _build_checkin_overview_payload(tg_id),
    })


@router.get("/checkin_overview")
async def miniapp_checkin_overview(request: Request, month: str = ""):
    """返回指定年月的签到日历统计与当月明细。"""
    tg_user = _get_tg_user(request)
    tg_id = tg_user.get("id")
    e = sql_get_emby(tg=tg_id)
    if not e:
        return JSONResponse({"ok": False, "msg": "未找到账户信息"})
    return JSONResponse({
        "ok": True,
        "overview": _build_checkin_overview_payload(tg_id, month),
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
        "overview": _build_checkin_overview_payload(tg_id),
    })
