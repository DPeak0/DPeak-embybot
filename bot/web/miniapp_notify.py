"""
miniapp_notify.py
在 Emby 媒体入库 webhook 触发时，检查是否有匹配的求片申请并通知用户。
由 bot/bot/web/api/webhook/media.py 中的 handle_media_webhook 调用。
"""
import asyncio
import io
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
from bot import LOGGER, bot, emby_url, emby_api
from bot.func_helper.emby import emby
from bot.sql_helper.sql_miniapp import (
    sql_get_incomplete_requests,
    sql_get_incomplete_requests_by_tmdb_ids,
    sql_get_pending_requests,
    sql_get_pending_requests_by_tmdb_ids,
    sql_mark_request_completed,
)


async def check_in_emby_by_tmdb(tmdb_id: str, session: aiohttp.ClientSession = None) -> bool:
    """调用 Emby Items API 检查指定 TMDB ID 的影片是否已入库"""
    if not tmdb_id or not emby_url or not emby_api:
        return False
    url = f"{emby_url.rstrip('/')}/emby/Items"
    params = {
        "AnyProviderIdEquals": f"tmdb.{tmdb_id}",
        "IncludeItemTypes": "Movie,Series",
        "Recursive": "true",
        "Limit": "1",
        "api_key": emby_api,
    }

    async def _request(client: aiohttp.ClientSession) -> bool:
        try:
            async with client.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return data.get("TotalRecordCount", 0) > 0
        except Exception as e:
            LOGGER.warning(f"【MiniApp】Emby 入库检查失败 tmdb_id={tmdb_id}: {e}")
            return False

    if session is not None:
        return await _request(session)

    async with aiohttp.ClientSession() as temp_session:
        return await _request(temp_session)


async def bulk_check_in_emby_by_tmdb(tmdb_ids: list[str], concurrency: int = 6) -> dict[str, bool]:
    """批量检查 TMDB 条目是否已在 Emby 入库，复用同一个会话并限制并发。"""
    unique_tmdb_ids = []
    seen = set()
    for tmdb_id in tmdb_ids or []:
        key = str(tmdb_id or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_tmdb_ids.append(key)

    if not unique_tmdb_ids or not emby_url or not emby_api:
        return {}

    semaphore = asyncio.Semaphore(max(int(concurrency or 1), 1))

    async with aiohttp.ClientSession() as session:
        async def _probe(tmdb_id: str):
            async with semaphore:
                return tmdb_id, await check_in_emby_by_tmdb(tmdb_id, session=session)

        pairs = await asyncio.gather(*[_probe(tmdb_id) for tmdb_id in unique_tmdb_ids])
    return dict(pairs)


def _format_media_size(size_bytes) -> str:
    if not size_bytes:
        return ""
    size = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _format_media_bitrate(bitrate) -> str:
    if not bitrate:
        return ""
    bitrate = float(bitrate)
    if bitrate >= 1_000_000:
        return f"{bitrate / 1_000_000:.1f} Mbps"
    if bitrate >= 1_000:
        return f"{bitrate / 1_000:.0f} Kbps"
    return f"{int(bitrate)} bps"


def _format_resolution(width, height) -> str:
    if not width or not height:
        return ""
    label = ""
    try:
        h = int(height)
        if h >= 2160:
            label = "4K"
        elif h >= 1440:
            label = "2K"
        elif h >= 1080:
            label = "1080p"
        elif h >= 720:
            label = "720p"
    except Exception:
        label = ""
    base = f"{int(width)}x{int(height)}"
    return f"{base} ({label})" if label else base


def _normalize_title(text: str) -> str:
    return _normalize(text or "")


def _extract_media_brief(item: dict | None) -> list[str]:
    if not item:
        return []
    sources = item.get("MediaSources") or []
    source = max(sources, key=lambda s: s.get("Size") or 0, default={})
    streams = source.get("MediaStreams") or item.get("MediaStreams") or []
    video_stream = next((s for s in streams if s.get("Type") == "Video"), {})

    width = video_stream.get("Width") or source.get("Width")
    height = video_stream.get("Height") or source.get("Height")
    size_text = _format_media_size(source.get("Size"))
    resolution_text = _format_resolution(width, height)
    bitrate_text = _format_media_bitrate(source.get("Bitrate") or video_stream.get("BitRate"))

    info_parts = []
    if size_text:
        info_parts.append(f"大小 {size_text}")
    if resolution_text:
        info_parts.append(f"分辨率 {resolution_text}")
    if bitrate_text:
        info_parts.append(f"码率 {bitrate_text}")
    return info_parts


async def _emby_get_json(path: str, *, params: dict | None = None, session: aiohttp.ClientSession = None) -> dict | None:
    if not emby_url or not emby_api:
        return None
    url = f"{emby_url.rstrip('/')}{path}"
    query = dict(params or {})
    query["api_key"] = emby_api

    async def _request(client: aiohttp.ClientSession):
        async with client.get(url, params=query, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    try:
        if session is not None:
            return await _request(session)
        async with aiohttp.ClientSession() as temp_session:
            return await _request(temp_session)
    except Exception as e:
        LOGGER.warning(f"【MiniApp通知】拉取 Emby 媒体详情失败 path={path}: {e}")
        return None


async def _fetch_emby_item_by_id(item_id: str, session: aiohttp.ClientSession = None) -> dict | None:
    if not item_id:
        return None
    return await _emby_get_json(
        f"/emby/Items/{item_id}",
        params={"Fields": "ProductionYear,OriginalTitle,ProviderIds,MediaSources,MediaStreams"},
        session=session,
    )


def _choose_best_search_item(items: list[dict], title: str = "", media_type: str = "") -> dict | None:
    if not items:
        return None
    normalized_title = _normalize_title(title)
    normalized_type = str(media_type or "").strip().lower()

    def _score(item: dict) -> tuple[int, int]:
        item_type = str(item.get("Type") or "").lower()
        score = 0
        if normalized_type == "movie" and item_type == "movie":
            score += 3
        elif normalized_type in {"tv", "series", "show"} and item_type == "series":
            score += 3
        item_names = [
            _normalize_title(item.get("Name", "")),
            _normalize_title(item.get("OriginalTitle", "")),
        ]
        if normalized_title and normalized_title in item_names:
            score += 5
        elif normalized_title and any(normalized_title in candidate or candidate in normalized_title for candidate in item_names if candidate):
            score += 2
        return score, int(item.get("ProductionYear") or 0)

    return max(items, key=_score)


async def _fetch_emby_item_by_tmdb(tmdb_id: str, media_type: str = "", title: str = "", session: aiohttp.ClientSession = None) -> dict | None:
    if not tmdb_id:
        return None
    include_types = "Movie,Series"
    if media_type == "movie":
        include_types = "Movie"
    elif media_type in {"tv", "series", "show"}:
        include_types = "Series"

    payload = await _emby_get_json(
        "/emby/Items",
        params={
            "AnyProviderIdEquals": f"tmdb.{tmdb_id}",
            "IncludeItemTypes": include_types,
            "Recursive": "true",
            "Limit": "10",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Fields": "ProductionYear,OriginalTitle,ProviderIds,MediaSources,MediaStreams",
        },
        session=session,
    )
    items = (payload or {}).get("Items") or []
    return _choose_best_search_item(items, title=title, media_type=media_type)


async def _search_emby_item_by_title(title: str, media_type: str = "", session: aiohttp.ClientSession = None) -> dict | None:
    if not title:
        return None
    include_types = "Movie,Series"
    if media_type == "movie":
        include_types = "Movie"
    elif media_type in {"tv", "series", "show"}:
        include_types = "Series"

    payload = await _emby_get_json(
        "/emby/Items",
        params={
            "SearchTerm": title,
            "IncludeItemTypes": include_types,
            "Recursive": "true",
            "Limit": "8",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Fields": "ProductionYear,OriginalTitle,ProviderIds,MediaSources,MediaStreams",
        },
        session=session,
    )
    items = (payload or {}).get("Items") or []
    return _choose_best_search_item(items, title=title, media_type=media_type)


async def _resolve_emby_media_item(*, tmdb_id: str = "", media_type: str = "", title: str = "", emby_item: dict | None = None) -> dict | None:
    async with aiohttp.ClientSession() as session:
        item_id = str((emby_item or {}).get("Id") or "").strip()
        if item_id:
            full_item = await _fetch_emby_item_by_id(item_id, session=session)
            if full_item:
                return full_item
        if tmdb_id:
            item = await _fetch_emby_item_by_tmdb(tmdb_id, media_type=media_type, title=title, session=session)
            if item:
                return item
        if title:
            item = await _search_emby_item_by_title(title, media_type=media_type, session=session)
            if item:
                return item
    return emby_item


async def _fetch_tmdb_poster_bytes(poster_url: str) -> bytes | None:
    if not poster_url:
        return None

    image_url = ""
    if poster_url.startswith("http"):
        image_url = poster_url
    else:
        parsed = urlparse(poster_url)
        query = parse_qs(parsed.query)
        poster_path = unquote((query.get("path") or [""])[0])
        width = str((query.get("w") or ["500"])[0] or "500")
        if poster_path.startswith("/"):
            image_url = f"https://image.tmdb.org/t/p/w{width}{poster_path}"

    if not image_url:
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception as e:
        LOGGER.warning(f"【MiniApp通知】拉取 TMDB 海报失败: {e}")
        return None


def _build_request_completed_caption(title: str, year: str = "", info_parts: list[str] | None = None, note: str = "") -> str:
    lines = ["🎉 **已入库**"]
    title_line = f"**《{title}》**"
    if year:
        title_line += f" ({year})"
    lines.append(title_line)
    if info_parts:
        lines.append(" · ".join(info_parts))
    lines.append("已添加至 Emby，可直接前往观看。")
    if note:
        lines.append(f"备注：{note}")
    return "\n".join(lines)


async def send_request_completed_notification(
    *,
    chat_id: int,
    title: str,
    year: str = "",
    media_type: str = "",
    tmdb_id: str = "",
    note: str = "",
    poster_url: str = "",
    emby_item: dict | None = None,
) -> bool:
    media_item = await _resolve_emby_media_item(
        tmdb_id=str(tmdb_id or "").strip(),
        media_type=str(media_type or "").strip().lower(),
        title=title,
        emby_item=emby_item,
    )
    display_title = title or (media_item or {}).get("Name") or "影片"
    display_year = str(year or (media_item or {}).get("ProductionYear") or "").strip()
    caption = _build_request_completed_caption(
        display_title,
        year=display_year,
        info_parts=_extract_media_brief(media_item),
        note=note,
    )

    image_payload = None
    item_id = str((media_item or {}).get("Id") or "").strip()
    if item_id:
        ok, image_payload = await emby.primary(item_id, width=480, height=720, quality=88)
        if not ok:
            image_payload = None
    if not image_payload and poster_url:
        image_payload = await _fetch_tmdb_poster_bytes(poster_url)

    try:
        if image_payload:
            photo = io.BytesIO(image_payload)
            photo.name = "media.jpg"
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
        else:
            await bot.send_message(chat_id=chat_id, text=caption)
        return True
    except Exception as e:
        LOGGER.error(f"【MiniApp通知】发送通知给 {chat_id} 失败: {e}")
        return False


async def _notify_request_completed(req, emby_item: dict | None = None) -> bool:
    try:
        return await send_request_completed_notification(
            chat_id=req.tg,
            title=req.title or "",
            year=req.year or "",
            media_type=req.media_type or "",
            tmdb_id=req.tmdb_id or "",
            note=req.note or "",
            poster_url=req.poster or "",
            emby_item=emby_item,
        )
    except Exception as e:
        LOGGER.error(f"【MiniApp通知】发送通知给 {req.tg} 失败: {e}")
        return False


async def sync_pending_requests_by_tmdb_ids(tmdb_ids: list[str], notify: bool = True) -> int:
    """按 TMDB ID 实时同步待处理申请，发现已入库则自动转为 completed。"""
    pending = sql_get_incomplete_requests_by_tmdb_ids(tmdb_ids)
    if not pending:
        return 0

    groups: dict[str, list] = {}
    for req in pending:
        if req.tmdb_id:
            groups.setdefault(str(req.tmdb_id), []).append(req)

    synced = 0
    notified = 0
    library_map = await bulk_check_in_emby_by_tmdb(list(groups.keys()))
    for tmdb_id, reqs in groups.items():
        in_library = library_map.get(tmdb_id, False)
        if not in_library:
            continue
        emby_item = await _fetch_emby_item_by_tmdb(tmdb_id, media_type=(reqs[0].media_type or ""), title=(reqs[0].title or ""))
        for req in reqs:
            if sql_mark_request_completed(req.id):
                synced += 1
                if notify and await _notify_request_completed(req, emby_item=emby_item):
                    notified += 1

    if synced:
        LOGGER.info(f"【MiniApp同步】按TMDB同步完成，更新 {synced} 条申请，通知 {notified} 条")
    return synced


async def sync_all_incomplete_requests(notify: bool = True) -> int:
    """全量同步所有未完成申请，确保后台统计和各页面都反映 Emby 真实状态。"""
    pending = sql_get_incomplete_requests()
    if not pending:
        return 0
    tmdb_ids = list({str(req.tmdb_id) for req in pending if req.tmdb_id})
    if not tmdb_ids:
        return 0
    return await sync_pending_requests_by_tmdb_ids(tmdb_ids, notify=notify)


async def check_all_pending_in_emby():
    """定时检查所有未完成申请，若已入库则标记完成并通知用户"""
    try:
        synced = await sync_all_incomplete_requests(notify=True)
        LOGGER.info(f"【MiniApp定时检查】完成，本轮同步 {synced} 条申请")
    except Exception as e:
        LOGGER.error(f"【MiniApp定时检查】执行失败: {e}")


def _normalize(text: str) -> str:
    """简单标准化标题：小写 + 去除常见标点"""
    import re
    return re.sub(r"[\s\-:：·•.。，,!！?？'\"()（）《》]", "", text).lower()


async def check_requests_on_new_media(item_name: str, orig_name: str = "", tmdb_id: str = "", emby_item: dict | None = None):
    """
    新媒体入库时调用。
    item_name: Emby 返回的媒体名称
    orig_name: 原始语言名称（可选）
    tmdb_id: TMDB ID（可选，若 Emby webhook 携带则优先精确匹配）
    """
    try:
        pending = sql_get_incomplete_requests()
        if not pending:
            return

        norm_name = _normalize(item_name)
        norm_orig = _normalize(orig_name) if orig_name else ""

        for req in pending:
            matched = False

            # 优先用 TMDB ID 精确匹配
            if tmdb_id and req.tmdb_id and tmdb_id == req.tmdb_id:
                matched = True
            else:
                # 标题模糊匹配
                req_norm = _normalize(req.title or "")
                req_orig_norm = _normalize(req.orig_title or "")
                if req_norm and (req_norm in norm_name or norm_name in req_norm):
                    matched = True
                elif req_orig_norm and norm_orig and (req_orig_norm in norm_orig or norm_orig in req_orig_norm):
                    matched = True

            if matched:
                sql_mark_request_completed(req.id)
                try:
                    if await _notify_request_completed(req, emby_item=emby_item):
                        LOGGER.info(f"【MiniApp通知】已通知用户 {req.tg}：《{req.title}》 已入库")
                except Exception as e:
                    LOGGER.error(f"【MiniApp通知】发送通知给 {req.tg} 失败: {e}")
    except Exception as e:
        LOGGER.error(f"【MiniApp通知】检查求片申请失败: {e}")
