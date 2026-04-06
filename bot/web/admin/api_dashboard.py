"""
服务器状态 JSON API
GET /admin/api/dashboard    返回 Emby 服务器统计数据 + Bot DB 统计
"""
import aiohttp
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from bot import emby_url, emby_api, LOGGER
from bot.sql_helper.sql_emby import sql_count_emby, sql_count_emby_by_lv
from bot.func_helper.emby import emby
from .auth import require_admin

router = APIRouter()


@router.get("/api/dashboard")
async def get_dashboard(admin=Depends(require_admin)):
    # ── Bot DB 统计 ──────────────────────────────────────────────────────────
    tg_count, embyid_count, lv_a_count = sql_count_emby()
    lv_counts = sql_count_emby_by_lv()

    # ── Emby 媒体库统计 ──────────────────────────────────────────────────────
    media = {"movie": 0, "series": 0, "episode": 0, "song": 0}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{emby_url.rstrip('/')}/emby/Items/Counts?api_key={emby_api}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    media["movie"]   = data.get("MovieCount", 0)
                    media["series"]  = data.get("SeriesCount", 0)
                    media["episode"] = data.get("EpisodeCount", 0)
                    media["song"]    = data.get("SongCount", 0)
    except Exception as e:
        LOGGER.warning(f"【Admin】获取媒体统计失败: {e}")

    # ── Emby 活跃流 ──────────────────────────────────────────────────────────
    playing_count = await emby.get_current_playing_count()

    return JSONResponse({
        "db": {
            "total_users":  tg_count      or 0,
            "emby_bound":   embyid_count  or 0,
            "whitelist":    lv_counts.get("a", 0),
            "normal":       lv_counts.get("b", 0),
            "public":       lv_counts.get("e", 0),
            "banned":       lv_counts.get("c", 0),
            "unregistered": lv_counts.get("d", 0),
        },
        "media": media,
        "active_streams": max(playing_count, 0),
    })
