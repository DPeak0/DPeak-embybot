"""
兑换注册码exchange
"""
from datetime import timedelta, datetime

from bot import bot, _open, LOGGER, bot_photo, ranks
from bot.func_helper.emby import emby
from bot.func_helper.fix_bottons import register_code_ikb
from bot.func_helper.msg_utils import sendMessage, sendPhoto
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_code import Code
from bot.sql_helper.sql_emby import sql_get_emby, Emby
from bot.sql_helper import Session


def is_renew_code(input_string):
    if "Renew" in input_string:
        return True
    else:
        return False


def parse_code_lv(register_code: str) -> str:
    """
    解析注册码中的等级字段
    新格式（4段）：DPEAK-e-30-Register_xxx → 'e'
    旧格式（3段）：DPEAK-30-Register_xxx → 'b'（向后兼容）
    """
    parts = register_code.split('-')
    if len(parts) >= 4 and parts[1] in ('b', 'e', 'a'):
        return parts[1]
    return 'b'  # 旧格式默认为普通用户


async def rgs_code(_, msg, register_code):
    if _open.stat:
        return await sendMessage(msg, "🤧 自由注册开启下无法使用注册码。")

    data = sql_get_emby(tg=msg.from_user.id)
    if not data:
        return await sendMessage(msg, "出错了，不确定您是否有资格使用，请先 /start")
    embyid = data.embyid
    ex = data.ex
    lv = data.lv
    if embyid:
        if not is_renew_code(register_code):
            return await sendMessage(msg, "🔔 很遗憾，您使用的是注册码，无法启用续期功能，请悉知", timer=60)
        with Session() as session:
            r = session.query(Code).filter(Code.code == register_code).with_for_update().first()
            if not r:
                return await sendMessage(msg, "⛔ **你输入了一个错误de续期码，请确认好重试。**", timer=60)
            re = session.query(Code).filter(Code.code == register_code, Code.used.is_(None)).with_for_update().update(
                {Code.used: msg.from_user.id, Code.usedtime: datetime.now()})
            session.commit()
            tg1 = r.tg
            us1 = r.us
            used = r.used
            if re == 0: return await sendMessage(msg,
                                                 f'此 `{register_code}` \n续期码已被使用,是[{used}](tg://user?id={used})的形状了喔')
            session.query(Code).filter(Code.code == register_code).with_for_update().update(
                {Code.used: msg.from_user.id, Code.usedtime: datetime.now()})
            first = await bot.get_chat(tg1)
            ex_new = datetime.now()
            if ex_new > ex:
                ex_new = ex_new + timedelta(days=us1)
                await emby.emby_change_policy(emby_id=embyid, disable=False)
                if lv == 'c':
                    # 解封时恢复到 base_lv（公益用户→e，普通用户→b）
                    restore_lv = data.base_lv if data.base_lv in ('b', 'e') else 'b'
                    session.query(Emby).filter(Emby.tg == msg.from_user.id).update({Emby.ex: ex_new, Emby.lv: restore_lv})
                else:
                    session.query(Emby).filter(Emby.tg == msg.from_user.id).update({Emby.ex: ex_new})
                await sendMessage(msg, f'🎊 少年郎，恭喜你，已收到 [{first.first_name}](tg://user?id={tg1}) 的{us1}天🎁\n'
                                       f'__已解封账户并延长到期时间至(以当前时间计)__\n到期时间：{ex_new.strftime("%Y-%m-%d %H:%M:%S")}')
            elif ex_new < ex:
                ex_new = data.ex + timedelta(days=us1)
                session.query(Emby).filter(Emby.tg == msg.from_user.id).update({Emby.ex: ex_new})
                await sendMessage(msg,
                                  f'🎊 少年郎，恭喜你，已收到 [{first.first_name}](tg://user?id={tg1}) 的{us1}天🎁\n到期时间：{ex_new}__')
            session.commit()
            new_code = register_code[:-7] + "░" * 7
            await sendMessage(msg,
                              f'· 🎟️ 续期码使用 - [{msg.from_user.first_name}](tg://user?id={msg.chat.id}) [{msg.from_user.id}] 使用了 {new_code}\n· 📅 实时到期 - {ex_new}',
                              send=True)
            LOGGER.info(f"【续期码】：{msg.from_user.first_name}[{msg.chat.id}] 使用了 {register_code}，到期时间：{ex_new}")
            log_audit(category="code", action="renew", source="bot",
                      target_tg=msg.from_user.id,
                      target_name=msg.from_user.first_name,
                      detail=f"使用续期码 {register_code}，新到期：{ex_new}")

    else:
        if is_renew_code(register_code):
            return await sendMessage(msg, "🔔 很遗憾，您使用的是续期码，无法启用注册功能，请悉知", timer=60)
        if data.us > 0:
            return await sendMessage(msg, "已有注册资格，请先使用【创建账户】注册，勿重复使用其他注册码。")
        with Session() as session:
            r = session.query(Code).filter(Code.code == register_code).with_for_update().first()
            if not r:
                return await sendMessage(msg, "⛔ **你输入了一个错误de注册码，请确认好重试。**")
            code_prefix = register_code.split('-')[0]
            # 判断此注册码使用者为管理员赠送的tg, 如果不是则拒绝使用
            if code_prefix not in ranks.logo and code_prefix != str(msg.from_user.id):
                return await sendMessage(msg, '🤺 你也想和bot击剑吗 ?', timer=60)
            re = session.query(Code).filter(Code.code == register_code, Code.used.is_(None)).with_for_update().update(
                {Code.used: msg.from_user.id, Code.usedtime: datetime.now()})
            session.commit()
            tg1 = r.tg
            us1 = r.us
            used = r.used
            if re == 0: return await sendMessage(msg,
                                                 f'此 `{register_code}` \n注册码已被使用,是 [{used}](tg://user?id={used}) 的形状了喔')
            first = await bot.get_chat(tg1)
            x = data.us + us1
            # 解析注册码等级并设置用户基础等级
            code_lv = parse_code_lv(register_code)
            session.query(Emby).filter(Emby.tg == msg.from_user.id).update({
                Emby.us: x,
                Emby.lv: code_lv,
                Emby.base_lv: code_lv,
            })
            session.commit()
            await sendPhoto(msg, photo=bot_photo,
                            caption=f'🎊 少年郎，恭喜你，已经收到了 [{first.first_name}](tg://user?id={tg1}) 发送的邀请注册资格\n\n请选择你的选项~',
                            buttons=register_code_ikb)
            new_code = register_code[:-7] + "░" * 7
            await sendMessage(msg,
                              f'· 🎟️ 注册码使用 - [{msg.from_user.first_name}](tg://user?id={msg.chat.id}) [{msg.from_user.id}] 使用了 {new_code}',
                              send=True)
            LOGGER.info(
                f"【注册码】：{msg.from_user.first_name}[{msg.chat.id}] 使用了 {register_code} - {us1} - lv={code_lv}")
            log_audit(category="code", action="register", source="bot",
                      target_tg=msg.from_user.id,
                      target_name=msg.from_user.first_name,
                      after_val=code_lv,
                      detail=f"使用注册码 {register_code}，等级={code_lv}，有效天数={us1}")
