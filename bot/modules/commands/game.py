"""
/game 入口命令
触发修仙游戏主菜单
"""
from pyrogram import filters
from bot import bot, prefixes
from bot.modules.game.cultivation import show_game_menu


@bot.on_message(filters.command(['game', 'xiuxian'], prefixes=prefixes))
async def game_command(_, msg):
    """
    /game 或 /xiuxian — 呼出修仙游戏主菜单
    支持私聊和群聊
    """
    await show_game_menu(msg, msg.from_user.id, edit=False)
