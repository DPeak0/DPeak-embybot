"""
check_miniapp_requests.py
定时检查 pending/processing 求片申请是否已在 Emby 入库。
"""
from bot.web.miniapp_notify import check_all_pending_in_emby


async def check_miniapp_requests():
    await check_all_pending_in_emby()
