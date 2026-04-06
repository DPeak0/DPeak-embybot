"""
定时检测账户有无过期
"""
from datetime import timedelta, datetime

from pyrogram.errors import FloodWait
from sqlalchemy import and_
from asyncio import sleep
from bot import bot, group, LOGGER, _open, config
from bot.func_helper.emby import emby
from bot.func_helper.utils import tem_deluser
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_emby import Emby, get_all_emby, sql_update_emby
from bot.sql_helper.sql_emby2 import get_all_emby2, Emby2, sql_update_emby2


async def check_expired():
    # ── 公益用户(e)：到期时尝试自动续期 ──────────────────────────────────────
    rst = get_all_emby(and_(Emby.ex < datetime.now(), Emby.lv == 'e'))
    if rst is None:
        LOGGER.info('【到期检测】- 等级 e 无到期用户，跳过')
    else:
        ext = (datetime.now() + timedelta(days=30))
        for r in rst:
            if r.us >= 30:
                b = r.us - 30
                if sql_update_emby(Emby.tg == r.tg, ex=ext, us=b):
                    log_audit(category="account", action="auto_renew", source="scheduler",
                              target_tg=r.tg, target_name=r.name,
                              before_val="e/expired", after_val=f"e/{ext.strftime('%Y-%m-%d')}",
                              detail=f"公益用户自动续期30天（用券），剩余天数={b}")
                    text = f'【到期检测】\n#id{r.tg} 续期账户 [{r.name}](tg://user?id={r.tg})\n' \
                           f'在当前时间自动续期30天\n' \
                           f'📅实时到期：{ext.strftime("%Y-%m-%d %H:%M:%S")}'
                    LOGGER.info(text)
                else:
                    text = f'【到期检测】\n#id{r.tg} 续期账户 [{r.name}](tg://user?id={r.tg})\n' \
                           f'自动续期失败，请联系闺蜜（管理）'
                    LOGGER.error(text)
                try:
                    await bot.send_message(r.tg, text)
                except FloodWait as f:
                    LOGGER.warning(str(f))
                    await sleep(f.value * 1.2)
                    await bot.send_message(r.tg, text)
                except Exception as e:
                    LOGGER.error(e)

            elif _open.exchange and r.iv >= _open.exchange_cost:
                b = r.iv - _open.exchange_cost
                if sql_update_emby(Emby.tg == r.tg, ex=ext, iv=b):
                    log_audit(category="account", action="auto_renew", source="scheduler",
                              target_tg=r.tg, target_name=r.name,
                              before_val="e/expired", after_val=f"e/{ext.strftime('%Y-%m-%d')}",
                              detail=f"公益用户自动续期30天（积分），扣除={_open.exchange_cost}，剩余={b}")
                    text = f'【到期检测】\n#id{r.tg} 续期账户 [{r.name}](tg://user?id={r.tg})\n' \
                           f'在当前时间自动续期30天\n' \
                           f'📅实时到期: {ext.strftime("%Y-%m-%d %H:%M:%S")}'
                    LOGGER.info(text)
                else:
                    text = f'【到期检测】\n#id{r.tg} 续期账户 [{r.name}](tg://user?id={r.tg})\n续期失败，请联系闺蜜（管理）'
                    LOGGER.error(text)
                try:
                    await bot.send_message(r.tg, text)
                except FloodWait as f:
                    LOGGER.warning(str(f))
                    await sleep(f.value * 1.2)
                    await bot.send_message(r.tg, text)
                except Exception as e:
                    LOGGER.error(e)

            else:
                if await emby.emby_change_policy(emby_id=r.embyid, disable=True):
                    dead_day = r.ex + timedelta(days=config.freeze_days)
                    if sql_update_emby(Emby.tg == r.tg, lv='c'):
                        log_audit(category="account", action="auto_ban", source="scheduler",
                                  target_tg=r.tg, target_name=r.name,
                                  before_val="e", after_val="c",
                                  detail=f"公益用户到期无法续期，自动封禁，封存至 {dead_day.strftime('%Y-%m-%d')}")
                        text = f'【到期检测】\n#id{r.tg} 到期禁用 [{r.name}](tg://user?id={r.tg})\n将为您封存至 {dead_day.strftime("%Y-%m-%d")}，请及时续期'
                        LOGGER.info(text)
                    else:
                        text = f'【到期检测】\n#id{r.tg} 到期禁用 [{r.name}](tg://user?id={r.tg}) 已禁用，数据库写入失败'
                        LOGGER.warning(text)
                else:
                    text = f'【到期检测】\n#id{r.tg} 到期禁用 [{r.name}](tg://user?id={r.tg}) embyapi操作失败'
                    LOGGER.error(text)
                try:
                    send = await bot.send_message(r.tg, text)
                    await send.forward(group[0])
                except FloodWait as f:
                    LOGGER.warning(str(f))
                    await sleep(f.value * 1.2)
                    send = await bot.send_message(r.tg, text)
                    await send.forward(group[0])
                except Exception as e:
                    LOGGER.error(e)

    # ── 普通用户(b)：到期直接封禁，无自动续期 ────────────────────────────────
    rst_b = get_all_emby(and_(Emby.ex < datetime.now(), Emby.lv == 'b'))
    if rst_b is None:
        LOGGER.info('【到期检测】- 等级 b 无到期用户，跳过')
    else:
        for r in rst_b:
            if await emby.emby_change_policy(emby_id=r.embyid, disable=True):
                dead_day = r.ex + timedelta(days=config.freeze_days)
                if sql_update_emby(Emby.tg == r.tg, lv='c'):
                    log_audit(category="account", action="auto_ban", source="scheduler",
                              target_tg=r.tg, target_name=r.name,
                              before_val="b", after_val="c",
                              detail=f"普通用户到期自动封禁，封存至 {dead_day.strftime('%Y-%m-%d')}")
                    text = f'【到期检测】\n#id{r.tg} 普通用户到期禁用 [{r.name}](tg://user?id={r.tg})\n将为您封存至 {dead_day.strftime("%Y-%m-%d")}，请使用续期码续期'
                    LOGGER.info(text)
                else:
                    text = f'【到期检测】\n#id{r.tg} 到期禁用 [{r.name}](tg://user?id={r.tg}) 已禁用，数据库写入失败'
                    LOGGER.warning(text)
            else:
                text = f'【到期检测】\n#id{r.tg} 到期禁用 [{r.name}](tg://user?id={r.tg}) embyapi操作失败'
                LOGGER.error(text)
            try:
                send = await bot.send_message(r.tg, text)
                await send.forward(group[0])
            except FloodWait as f:
                LOGGER.warning(str(f))
                await sleep(f.value * 1.2)
                send = await bot.send_message(r.tg, text)
                await send.forward(group[0])
            except Exception as e:
                LOGGER.error(e)

    # ── 已封禁(c)：公益用户尝试自动解封，普通用户直接进入删号流程 ────────────
    rsc = get_all_emby(and_(Emby.ex < datetime.now(), Emby.lv == 'c'))
    if rsc is None:
        return LOGGER.info('【到期检测】- 等级 c 无到期用户，跳过')
    ext = (datetime.now() + timedelta(days=30))
    for c in rsc:
        # 仅公益用户（base_lv='e'）支持自动续期解封
        is_public_user = c.base_lv == 'e'

        if is_public_user and c.us >= 30:
            c_us = c.us - 30
            if await emby.emby_change_policy(emby_id=c.embyid, disable=False):
                if sql_update_emby(Emby.tg == c.tg, lv='e', ex=ext, us=c_us):
                    text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg})\n' \
                           f'在当前时间自动续期30天\n📅实时到期: {ext.strftime("%Y-%m-%d %H:%M:%S")}'
                    LOGGER.info(text)
                else:
                    text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg}) 数据库写入失败，请联系管理'
                    LOGGER.warning(text)
            else:
                text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg}) embyapi操作失败'
                LOGGER.error(text)
            try:
                await bot.send_message(c.tg, text)
            except FloodWait as f:
                LOGGER.warning(str(f))
                await sleep(f.value * 1.2)
                await bot.send_message(c.tg, text)
            except Exception as e:
                LOGGER.error(e)

        elif is_public_user and _open.exchange and c.iv >= _open.exchange_cost:
            c_iv = c.iv - _open.exchange_cost
            if await emby.emby_change_policy(emby_id=c.embyid, disable=False):
                if sql_update_emby(Emby.tg == c.tg, lv='e', ex=ext, iv=c_iv):
                    text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg})\n在当前时间自动续期30天\n📅实时到期：{ext.strftime("%Y-%m-%d %H:%M:%S")}'
                    LOGGER.info(text)
                else:
                    text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg}) 已禁用，数据库写入失败，请联系管理'
                    LOGGER.warning(text)
            else:
                text = f'【到期检测】\n#id{c.tg} 解封账户 [{c.name}](tg://user?id={c.tg}) embyapi操作失败，请联系管理'
                LOGGER.error(text)
            try:
                await bot.send_message(c.tg, text)
            except FloodWait as f:
                LOGGER.warning(str(f))
                await sleep(f.value * 1.2)
                await bot.send_message(c.tg, text)
            except Exception as e:
                LOGGER.error(e)

        else:
            # 冻存期到期 → 删号
            delete_day = c.ex + timedelta(days=config.freeze_days)
            if datetime.now() < delete_day:
                continue
            if await emby.emby_del(emby_id=c.embyid):
                sql_update_emby(Emby.embyid == c.embyid, embyid=None, name=None, pwd=None, pwd2=None, lv='d', base_lv=None, cr=None, ex=None)
                tem_deluser()
                log_audit(category="account", action="auto_delete", source="scheduler",
                          target_tg=c.tg, target_name=c.name,
                          before_val="c", after_val="d",
                          detail=f"账号封存超 {config.freeze_days} 天，自动删号")
                text = f'【到期检测】\n#id{c.tg} 删除账户 [{c.name}](tg://user?id={c.tg})\n已到期 {config.freeze_days} 天，执行清除任务。期待下次与你相遇'
                LOGGER.info(text)
            else:
                text = f'【到期检测】\n#id{c.tg} #删除账户 [{c.name}](tg://user?id={c.tg})\n到期删除失败，请检查以免无法进行后续使用'
                LOGGER.warning(text)
            try:
                send = await bot.send_message(c.tg, text)
                await send.forward(group[0])
            except FloodWait as f:
                LOGGER.warning(str(f))
                await sleep(f.value * 1.2)
                send = await bot.send_message(c.tg, text)
                await send.forward(group[0])
            except Exception as e:
                LOGGER.error(e)

    rseired = get_all_emby2(and_(Emby2.lv == 'b', Emby2.expired == 0, Emby2.ex < datetime.now()))
    if rseired is None:
        return LOGGER.info(f'【封禁检测】- emby2 无数据，跳过')
    for e in rseired:
        print(e.embyid)
        if await emby.emby_change_policy(emby_id=e.embyid, disable=True):
            if sql_update_emby2(Emby2.embyid == e.embyid, expired=1, lv='c'):
                text = f"【封禁检测】- 到期封印非TG账户 [{e.name}](google.com?q={e.embyid}) Done！"
                LOGGER.info(text)
            else:
                text = f'【封禁检测】- 到期封印非TG账户：`{e.name}` 数据库更改失败'
        else:
            text = f'【封禁检测】- 到期封印非TG账户：`{e.name}` embyapi操作失败，请手动处理'
        try:
            await bot.send_message(group[0], text)
        except FloodWait as f:
            LOGGER.warning(str(f))
            await sleep(f.value * 1.2)
            await bot.send_message(group[0], text)
        except Exception as e:
            LOGGER.error(e)
