"""
miniapp_notify.py
在 Emby 媒体入库 webhook 触发时，检查是否有匹配的求片申请并通知用户。
由 bot/bot/web/api/webhook/media.py 中的 handle_media_webhook 调用。
"""
import aiohttp
from bot import LOGGER, bot, emby_url, emby_api
from bot.sql_helper.sql_miniapp import sql_get_pending_requests, sql_mark_request_completed


async def check_in_emby_by_tmdb(tmdb_id: str) -> bool:
    """调用 Emby Items API 检查指定 TMDB ID 的影片是否已入库"""
    if not tmdb_id or not emby_url or not emby_api:
        return False
    try:
        url = f"{emby_url.rstrip('/')}/emby/Items"
        params = {
            "AnyProviderIdEquals": f"tmdb.{tmdb_id}",
            "IncludeItemTypes": "Movie,Series",
            "Recursive": "true",
            "Limit": "1",
            "api_key": emby_api,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return data.get("TotalRecordCount", 0) > 0
    except Exception as e:
        LOGGER.warning(f"【MiniApp】Emby 入库检查失败 tmdb_id={tmdb_id}: {e}")
        return False


async def check_all_pending_in_emby():
    """定时检查所有 pending/processing 申请，若已入库则标记完成并通知用户"""
    try:
        pending = sql_get_pending_requests()
        if not pending:
            return
        # 按 tmdb_id 分组，避免对同一 tmdb_id 重复请求 Emby
        groups: dict = {}
        for req in pending:
            if req.tmdb_id:
                groups.setdefault(req.tmdb_id, []).append(req)

        notified = 0
        for tmdb_id, reqs in groups.items():
            in_library = await check_in_emby_by_tmdb(tmdb_id)
            if not in_library:
                continue
            for req in reqs:
                sql_mark_request_completed(req.id)
                try:
                    await bot.send_message(
                        chat_id=req.tg,
                        text=(
                            f"🎉 **好消息！您申请的影片已入库**\n\n"
                            f"📽️ 《{req.title}》\n"
                            f"已添加至 Emby 媒体库，快去观看吧！"
                        )
                    )
                    notified += 1
                except Exception as e:
                    LOGGER.error(f"【MiniApp定时检查】通知用户 {req.tg} 失败: {e}")

        LOGGER.info(f"【MiniApp定时检查】完成，检查 {len(groups)} 部影片，通知 {notified} 条申请")
    except Exception as e:
        LOGGER.error(f"【MiniApp定时检查】执行失败: {e}")


def _normalize(text: str) -> str:
    """简单标准化标题：小写 + 去除常见标点"""
    import re
    return re.sub(r"[\s\-:：·•.。，,!！?？'\"()（）《》]", "", text).lower()


async def check_requests_on_new_media(item_name: str, orig_name: str = "", tmdb_id: str = ""):
    """
    新媒体入库时调用。
    item_name: Emby 返回的媒体名称
    orig_name: 原始语言名称（可选）
    tmdb_id: TMDB ID（可选，若 Emby webhook 携带则优先精确匹配）
    """
    try:
        pending = sql_get_pending_requests()
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
                    await bot.send_message(
                        chat_id=req.tg,
                        text=(
                            f"🎉 **好消息！您申请的影片已入库**\n\n"
                            f"📽️ 《{req.title}》\n"
                            f"已添加至 Emby 媒体库，快去观看吧！"
                        )
                    )
                    LOGGER.info(f"【MiniApp通知】已通知用户 {req.tg}：《{req.title}》 已入库")
                except Exception as e:
                    LOGGER.error(f"【MiniApp通知】发送通知给 {req.tg} 失败: {e}")
    except Exception as e:
        LOGGER.error(f"【MiniApp通知】检查求片申请失败: {e}")
