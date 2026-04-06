"""
对用户分数调整
score +-

对用户sakura_b币调整
coins +-
"""
import asyncio
from bot.schemas import MAX_INT_VALUE, MIN_INT_VALUE
from pyrogram import filters
from pyrogram.errors import BadRequest
from bot import bot, prefixes, LOGGER, sakura_b
from bot.func_helper.filters import admins_on_filter
from bot.func_helper.msg_utils import sendMessage, deleteMessage
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
from bot.func_helper.fix_bottons import group_f


async def get_user_input(msg):
    gm_name = msg.sender_chat.title if msg.sender_chat else f'管理员 [{msg.from_user.first_name}]({msg.from_user.id})'
    if msg.reply_to_message is None:
        try:
            uid = int(msg.command[1])
            b = int(msg.command[2])
            first = await bot.get_chat(uid)
        except (IndexError, KeyError, BadRequest, ValueError, AttributeError):
            await deleteMessage(msg)
            return None, None, None, gm_name
    else:
        try:
            first = msg.reply_to_message.from_user
            uid = first.id
            b = int(msg.command[1])
        except (IndexError, ValueError, AttributeError):
            await deleteMessage(msg)
            return None, None, None, gm_name
    return uid, b, first, gm_name


@bot.on_message(filters.command('score', prefixes=prefixes) & admins_on_filter)
async def score_user(_, msg):
    uid, b, first, gm_name = await get_user_input(msg)
    if not first:
        return await sendMessage(msg,
                                 "🔔 **使用格式：**[命令符]score [id] [加减分数]\n\n或回复某人[命令符]score [+/-分数] 请确认对象正确",
                                 timer=60)
    e = sql_get_emby(tg=uid)
    if not e:
        return await sendMessage(msg, f"数据库中没有[ta](tg://user?id={uid}) 。请先私聊我", buttons=group_f)

    us = e.us + b
    # 检查计算结果是否超出安全范围
    if us > MAX_INT_VALUE or us < MIN_INT_VALUE:
        return await sendMessage(msg, f"❌ 操作失败！计算结果超出安全范围（{MIN_INT_VALUE} 到 {MAX_INT_VALUE}）。", timer=60)
    
    if sql_update_emby(Emby.tg == uid, us=us):
        await asyncio.gather(sendMessage(msg,
                                         f"· 🎯 {gm_name} 调节了 [{first.first_name}](tg://user?id={uid}) 积分： {b}"
                                         f"\n· 🎟️ 实时积分: **{us}**"),
                             msg.delete())
        LOGGER.info(f"【admin】[积分]：{gm_name} 对 {first.first_name}-{uid}  {b}分  ")
        log_audit(category="credits", action="update", source="bot",
                  operator_tg=msg.from_user.id if msg.from_user else None,
                  operator_name=msg.from_user.first_name if msg.from_user else None,
                  target_tg=uid, target_name=first.first_name,
                  before_val=str(e.us), after_val=str(us),
                  detail=f"管理员调整注册资格天数 {'+' if b >= 0 else ''}{b} 天，当前={us}")
    else:
        await sendMessage(msg, '⚠️ 数据库操作失败，请检查')
        LOGGER.info(f"【admin】[积分]：{gm_name} 对 {first.first_name}-{uid} 数据操作失败")


@bot.on_message(filters.command('coins', prefixes=prefixes) & admins_on_filter)
async def coins_user(_, msg):
    uid, b, first, gm_name = await get_user_input(msg)
    if not first:
        return await sendMessage(msg,
                                 "🔔 **使用格式：**[命令符]coins [id] [+/-币]\n\n或回复某人[命令符]coins [+/-币] 请确认对象正确",
                                 timer=60)

    e = sql_get_emby(tg=uid)
    if not e:
        return await sendMessage(msg, f"数据库中没有[ta](tg://user?id={uid}) 。请先私聊我", buttons=group_f)

    # 加上判定send_chat
    us = e.iv + b
    # 检查计算结果是否超出安全范围
    if us > MAX_INT_VALUE or us < MIN_INT_VALUE:
        return await sendMessage(msg, f"❌ 操作失败！计算结果超出安全范围（{MIN_INT_VALUE} 到 {MAX_INT_VALUE}）。", timer=60)
    
    if sql_update_emby(Emby.tg == uid, iv=us):
        await asyncio.gather(sendMessage(msg,
                                         f"· 🎯 {gm_name} 调节了 [{first.first_name}](tg://user?id={uid}) {sakura_b}： {b}"
                                         f"\n· 🎟️ 实时{sakura_b}: **{us}**"),
                             msg.delete())
        LOGGER.info(
            f"【admin】[{sakura_b}]- {gm_name} 对 {first.first_name}-{uid}  {b}{sakura_b}")
        log_audit(category="credits", action="update", source="bot",
                  operator_tg=msg.from_user.id if msg.from_user else None,
                  operator_name=msg.from_user.first_name if msg.from_user else None,
                  target_tg=uid, target_name=first.first_name,
                  before_val=str(e.iv), after_val=str(us),
                  detail=f"管理员调整积分 {'+' if b >= 0 else ''}{b}，当前={us}")
    else:
        await sendMessage(msg, '⚠️ 数据库操作失败，请检查')
        LOGGER.info(f"【admin】[{sakura_b}]：{gm_name} 对 {first.first_name}-{uid} 数据操作失败")
