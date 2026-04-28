import asyncio

from bot import LOGGER
from bot.func_helper.scheduler import scheduler
from bot.web.miniapp_api import prewarm_tmdb_hot_cache


async def scheduled_prewarm_tmdb_cache():
    result = await prewarm_tmdb_hot_cache(force_refresh=True)
    if result.get("ok"):
        LOGGER.info(
            f"【Scheduler】TMDB热门缓存刷新完成，结果 {result.get('results', 0)} 条，海报 {result.get('warmed_images', 0)} 张"
        )
    else:
        LOGGER.warning(f"【Scheduler】TMDB热门缓存刷新跳过: {result.get('reason')}")


scheduler.add_job(
    scheduled_prewarm_tmdb_cache,
    "cron",
    hour="*/6",
    minute=15,
    id="prewarm_tmdb_hot_cache",
    replace_existing=True,
)

loop = asyncio.get_event_loop()
loop.call_later(20, lambda: loop.create_task(scheduled_prewarm_tmdb_cache()))
