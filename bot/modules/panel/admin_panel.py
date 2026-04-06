"""
 admin 面板
 功能暂定 开关注册，生成注册码，查看注册码情况，邀请注册排名情况
"""
import asyncio

from pyrogram import filters

from bot import bot, _open, save_config, bot_photo, LOGGER, bot_name, admins, owner, config
from bot.func_helper.filters import admins_on_filter
from bot.schemas import ExDate
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_code import sql_count_code, sql_count_p_code, sql_delete_all_unused, sql_delete_unused_by_days
from bot.sql_helper.sql_emby import sql_count_emby, sql_count_emby_by_lv
from bot.func_helper.fix_bottons import gm_ikb_content, open_menu_ikb, gog_rester_ikb, back_open_menu_ikb, \
    back_free_ikb, re_cr_link_ikb, close_it_ikb, ch_link_ikb, date_ikb, cr_paginate, cr_renew_ikb, invite_lv_ikb, checkin_lv_ikb, cr_link_type_ikb, all_user_limit_ikb
from bot.func_helper.msg_utils import callAnswer, editMessage, sendPhoto, callListen, deleteMessage, sendMessage
from bot.func_helper.utils import open_check, cr_link_one,rn_link_one


@bot.on_callback_query(filters.regex('manage') & admins_on_filter)
async def gm_ikb(_, call):
    await callAnswer(call, '✔️ manage面板')
    is_owner = call.from_user.id == owner
    stat, all_user, tem, timing = await open_check()
    stat = "True" if stat else "False"
    timing = 'Turn off' if timing == 0 else str(timing) + ' min'
    tg, emby, white = sql_count_emby()
    lv_counts = sql_count_emby_by_lv()
    cnt_b = lv_counts.get('b', 0)
    cnt_e = lv_counts.get('e', 0)
    lim_b = f'/{_open.all_user_b}' if getattr(_open, 'all_user_b', 0) > 0 else ''
    lim_e = f'/{_open.all_user_e}' if getattr(_open, 'all_user_e', 0) > 0 else ''
    lim_a = f'/{_open.all_user_a}' if getattr(_open, 'all_user_a', 0) > 0 else ''
    gm_text = (
        f'⚙️ 欢迎您，亲爱的管理员 {call.from_user.first_name}\n\n'
        f'· ®️ 注册状态 | **{stat}**\n'
        f'· ⏳ 定时注册 | **{timing}**\n'
        f'· 🎫 总注册限制 | **{all_user}**\n'
        f'· 🎟️ 已注册 | **{emby}**（🔵普通 {cnt_b}{lim_b} · 🟢公益 {cnt_e}{lim_e} · ♾白名单 {white}{lim_a}）\n'
        f'· 🤖 bot使用人数 | {tg}'
    )
    await editMessage(call, gm_text, buttons=gm_ikb_content(is_owner))


# 开关注册
@bot.on_callback_query(filters.regex('open-menu') & admins_on_filter)
async def open_menu(_, call):
    await callAnswer(call, '®️ register面板')
    # [开关，注册总数，定时注册] 此间只对emby表中tg用户进行统计
    stat, all_user, tem, timing = await open_check()
    tg, emby, white = sql_count_emby()
    openstats = '✅' if stat else '❎'  # 三元运算
    timingstats = '❎' if timing == 0 else '✅'
    text = f'⚙ **注册状态设置**：\n\n- 自由注册即定量方式，定时注册既定时又定量，将自动转发消息至群组，再次点击按钮可提前结束并报告。\n' \
           f'- **注册总人数限制 {all_user}**'
    await editMessage(call, text, buttons=open_menu_ikb(openstats, timingstats))
    if tem != emby:
        _open.tem = emby
        save_config()


@bot.on_callback_query(filters.regex('open_stat') & admins_on_filter)
async def open_stats(_, call):
    stat, all_user, tem, timing = await open_check()
    if timing != 0:
        return await callAnswer(call, "🔴 目前正在运行定时注册。\n无法调用，请再次点击，【定时注册】关闭状态", True)

    tg, emby, white = sql_count_emby()
    if stat:
        _open.stat = False
        save_config()
        await callAnswer(call, "🟢【自由注册】\n\n已结束", True)
        sur = all_user - tem
        text = f'🫧 管理员 {call.from_user.first_name} 已关闭 **自由注册**\n\n' \
               f'🎫 总注册限制 | {all_user}\n🎟️ 已注册人数 | {tem}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await asyncio.gather(sendPhoto(call, photo=bot_photo, caption=text, send=True),
                             editMessage(call, text, buttons=back_free_ikb))
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 关闭了自由注册")
        log_audit(category="settings", action="close_register", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"关闭自由注册，当前已注册={tem}，总限制={all_user}")
    elif not stat:
        _open.stat = True
        save_config()
        await callAnswer(call, "🟡【自由注册】\n\n已开启", True)
        sur = all_user - tem  # for i in group可以多个群组用，但是现在不做
        text = f'🫧 管理员 {call.from_user.first_name} 已开启 **自由注册**\n\n' \
               f'🎫 总注册限制 | {all_user}\n🎟️ 已注册人数 | {tem}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await asyncio.gather(sendPhoto(call, photo=bot_photo, caption=text, buttons=gog_rester_ikb(), send=True),
                             editMessage(call, text=text, buttons=back_free_ikb))
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 开启了自由注册，总人数限制 {all_user}")
        log_audit(category="settings", action="open_register", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"开启自由注册，总限制={all_user}")


change_for_timing_task = None


@bot.on_callback_query(filters.regex('open_timing') & admins_on_filter)
async def open_timing(_, call):
    global change_for_timing_task
    if _open.timing == 0:
        await callAnswer(call, '⭕ 定时设置')
        await editMessage(call,
                          "🦄【定时注册】 \n\n- 请在 120s 内发送 [定时时长] [总人数]\n"
                          "- 形如：`30 50` 即30min，总人数限制50\n"
                          "- 如需要关闭定时注册，再次点击【定时注册】\n"
                          "- 设置好之后将发送置顶消息注意权限\n- 退出 /cancel")

        txt = await callListen(call, 120, buttons=back_open_menu_ikb)
        if txt is False:
            return

        await txt.delete()
        if txt.text == '/cancel':
            return await open_menu(_, call)

        try:
            new_timing, new_all_user = txt.text.split()
            _open.timing = int(new_timing)
            _open.all_user = int(new_all_user)
            _open.stat = True
            save_config()
        except ValueError:
            await editMessage(call, "🚫 请检查数字填写是否正确。\n`[时长min] [总人数]`", buttons=back_open_menu_ikb)
        else:
            tg, emby, white = sql_count_emby()
            sur = _open.all_user - emby
            await asyncio.gather(sendPhoto(call, photo=bot_photo,
                                           caption=f'🫧 管理员 {call.from_user.first_name} 已开启 **定时注册**\n\n'
                                                   f'⏳ 可持续时间 | **{_open.timing}** min\n'
                                                   f'🎫 总注册限制 | {_open.all_user}\n🎟️ 已注册人数 | {emby}\n'
                                                   f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}',
                                           buttons=gog_rester_ikb(), send=True),
                                 editMessage(call,
                                             f"®️ 好，已设置**定时注册 {_open.timing} min 总限额 {_open.all_user}**",
                                             buttons=back_free_ikb))
            LOGGER.info(
                f"【admin】-定时注册：管理员 {call.from_user.first_name} 开启了定时注册 {_open.timing} min，人数限制 {sur}")
            log_audit(category="settings", action="open_timing_register", source="bot",
                      operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                      detail=f"开启定时注册，时长={_open.timing}min，总限制={_open.all_user}")
            # 创建一个异步任务并保存为变量，并给它一个名字
            change_for_timing_task = asyncio.create_task(
                change_for_timing(_open.timing, call.from_user.id, call), name='change_for_timing')

    else:
        try:
            # 遍历所有的异步任务，找到'change_for_timing'，取消
            for task in asyncio.all_tasks():
                if task.get_name() == 'change_for_timing':
                    change_for_timing_task = task
                    break
            change_for_timing_task.cancel()
        except AttributeError:
            pass
        else:
            await callAnswer(call, "Ⓜ️【定时任务运行终止】\n\n**已为您停止**", True)
            await open_menu(_, call)


async def change_for_timing(timing, tgid, call):
    a = _open.tem
    timing = timing * 60
    try:
        await asyncio.sleep(timing)
    except asyncio.CancelledError:
        pass
    finally:
        _open.timing = 0
        _open.stat = False
        save_config()
        b = _open.tem - a
        s = _open.all_user - _open.tem
        text = f'⏳** 注册结束**：\n\n🍉 目前席位：{_open.tem}\n🥝 新增席位：{b}\n🍋 剩余席位：{s}'
        send = await sendPhoto(call, photo=bot_photo, caption=text, timer=300, send=True)
        send1 = await send.forward(tgid)
        LOGGER.info(f'【admin】-定时注册：运行结束，本次注册 目前席位：{_open.tem}  新增席位:{b}  剩余席位：{s}')
        await deleteMessage(send1, 30)


@bot.on_callback_query(filters.regex('all_user_limit') & admins_on_filter)
async def open_all_user_l(_, call):
    await callAnswer(call, '⭕ 注册限制设置')
    lv_counts = sql_count_emby_by_lv()
    lim_b = getattr(_open, 'all_user_b', 0)
    lim_e = getattr(_open, 'all_user_e', 0)
    lim_a = getattr(_open, 'all_user_a', 0)
    text = (
        f'⭕ **注册人数分级限制**\n\n'
        f'· 📊 总注册限制 | **{_open.all_user}**（已注册 {_open.tem}）\n'
        f'· 🔵 普通用户 | 已注册 **{lv_counts.get("b",0)}** / 上限 **{"不限" if lim_b==0 else lim_b}**\n'
        f'· 🟢 公益用户 | 已注册 **{lv_counts.get("e",0)}** / 上限 **{"不限" if lim_e==0 else lim_e}**\n'
        f'· ♾ 白名单   | 已注册 **{lv_counts.get("a",0)}** / 上限 **{"不限" if lim_a==0 else lim_a}**\n\n'
        f'请选择要修改的限制项（0 = 不限制）：'
    )
    await editMessage(call, text, buttons=all_user_limit_ikb())


async def _set_lv_limit(call, attr: str, label: str):
    """通用：设置某等级人数上限"""
    await editMessage(call,
        f"🦄 请在 120s 内发送 **{label}** 人数上限\n（输入 0 表示不限制，取消 /cancel）",
        buttons=back_free_ikb)
    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    if txt.text == '/cancel':
        await txt.delete()
        return await open_all_user_l(_, call)
    try:
        await txt.delete()
        val = int(txt.text)
        if val < 0:
            raise ValueError
    except ValueError:
        return await editMessage(call, "❌ 请输入一个非负整数。", buttons=back_free_ikb)
    setattr(_open, attr, val)
    save_config()
    tip = "不限制" if val == 0 else str(val)
    await editMessage(call, f"✔️ 已设置 **{label}** 上限：**{tip}**", buttons=back_free_ikb)
    LOGGER.info(f"【admin】{call.from_user.first_name} 设置 {attr}={val}")
    log_audit(category="settings", action="update", source="bot",
              operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
              detail=f"设置 {label} 人数上限={tip}")


@bot.on_callback_query(filters.regex('^set_all_user_total$') & admins_on_filter)
async def set_all_user_total(_, call):
    await callAnswer(call, '📊 总人数限制')
    await editMessage(call,
        "🦄 请在 120s 内发送 **总注册人数限制**\n（总人数满自动关闭注册，取消 /cancel）",
        buttons=back_free_ikb)
    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    if txt.text == '/cancel':
        await txt.delete()
        return await open_all_user_l(_, call)
    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        return await editMessage(call, "❌ 请输入一个数字。", buttons=back_free_ikb)
    _open.all_user = a
    save_config()
    await editMessage(call, f"✔️ 已设置 **注册总人数限制：{a}**", buttons=back_free_ikb)
    LOGGER.info(f"【admin】{call.from_user.first_name} 调整总人数限制：{a}")
    log_audit(category="settings", action="update", source="bot",
              operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
              before_val=str(_open.all_user), after_val=str(a),
              detail=f"调整总注册人数限制={a}")


@bot.on_callback_query(filters.regex('^set_all_user_b$') & admins_on_filter)
async def set_all_user_b(_, call):
    await callAnswer(call, '🔵 普通用户上限')
    await _set_lv_limit(call, 'all_user_b', '🔵 普通用户')


@bot.on_callback_query(filters.regex('^set_all_user_e$') & admins_on_filter)
async def set_all_user_e(_, call):
    await callAnswer(call, '🟢 公益用户上限')
    await _set_lv_limit(call, 'all_user_e', '🟢 公益用户')


@bot.on_callback_query(filters.regex('^set_all_user_a$') & admins_on_filter)
async def set_all_user_a(_, call):
    await callAnswer(call, '♾ 白名单上限')
    await _set_lv_limit(call, 'all_user_a', '♾ 白名单')


@bot.on_callback_query(filters.regex('open_us') & admins_on_filter)
async def open_us(_, call):
    await callAnswer(call, '🤖开放账号天数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送开放注册时账号的有效天数，本次修改不会对注册状态改动，如需要开注册请点击打开自由注册\n**注**：总人数满自动关闭注册 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        _open.open_us = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **开放注册时账号的有效天数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了开放注册时账号的有效天数：{a}")
        log_audit(category="settings", action="update", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"设置开放注册账号有效天数={a}")

# 生成注册链接
@bot.on_callback_query(filters.regex('^cr_link$') & admins_on_filter)
async def cr_link(_, call):
    await callAnswer(call, '✔️ 创建注册/续期码')
    await editMessage(
        call,
        '🎟️ **请选择要创建的码类型：**\n\n'
        '🟢 **公益注册码** - 用于抽奖/赠送（`DPEAK-e-天数-Register_xxx`）\n'
        '🔵 **普通注册码** - 付费用户专属（`DPEAK-b-天数-Register_xxx`）\n'
        '🎟️ **续期码** - 通用续期（`DPEAK-天数-Renew_xxx`）',
        buttons=cr_link_type_ikb()
    )


@bot.on_callback_query(filters.regex('^cr_link_type-') & admins_on_filter)
async def cr_link_type(_, call):
    code_type = call.data.split('-')[1]  # 'e', 'b', or 'renew'

    type_label = {'e': '公益注册码', 'b': '普通注册码', 'renew': '续期码'}.get(code_type, code_type)
    await callAnswer(call, f'✔️ 创建 {type_label}')
    send = await editMessage(
        call,
        f'🎟️ 创建 **{type_label}**\n\n'
        '请回复 [天数] [数量] [模式]\n\n'
        '**天数**：月30，季90，半年180，年365\n'
        '**模式**：link -深链接 | code -码\n'
        '**示例**：`30 1 link` 记作 30天一条深链接\n'
        '__取消本次操作，请 /cancel__'
    )
    if send is False:
        return

    content = await callListen(call, 120, buttons=re_cr_link_ikb)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await editMessage(call, '⭕ 您已经取消操作了。', buttons=re_cr_link_ikb)

    try:
        await content.delete()
        times, count, method = content.text.split()
        count = int(count)
        days = int(times)
        if method not in ('code', 'link'):
            return await editMessage(call, '⭕ 输入的method参数有误', buttons=re_cr_link_ikb)
    except (ValueError, IndexError):
        return await editMessage(call, '⚠️ 检查输入，有误。', buttons=re_cr_link_ikb)

    if code_type == 'renew':
        links, code_list = await rn_link_one(call.from_user.id, times, count, days, method)
        if links is None:
            return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
        links = f"🎯 {bot_name}已为您生成了 **{days}天** 续期码 {count} 个\n\n" + links
        chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
        for chunk in chunks:
            await sendMessage(content, chunk, buttons=close_it_ikb)
        await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天续期码', buttons=re_cr_link_ikb)
        LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天续期码")
        log_audit(category="code", action="create", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"生成续期码 {count} 个，{days}天，方式={method}\n码列表：\n" + '\n'.join(code_list))
    else:
        links, code_list = await cr_link_one(call.from_user.id, times, count, days, method, lv=code_type)
        if links is None:
            return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
        links = f"🎯 {bot_name}已为您生成了 **{days}天** {type_label} {count} 个\n\n" + links
        chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
        for chunk in chunks:
            await sendMessage(content, chunk, buttons=close_it_ikb)
        await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天{type_label}', buttons=re_cr_link_ikb)
        LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天{type_label}(lv={code_type})")
        log_audit(category="code", action="create", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"生成{type_label} {count} 个，{days}天，lv={code_type}，方式={method}\n码列表：\n" + '\n'.join(code_list))


# 检索
@bot.on_callback_query(filters.regex('ch_link') & admins_on_filter)
async def ch_link(_, call):
    is_owner = call.from_user.id == owner

    if not is_owner:
        # 非 owner 管理员：直接显示自己的码
        await callAnswer(call, '🔍 查看您的注册码')
        i = call.from_user.id
        a, b, c, d, f, e, pub_cnt, norm_cnt = sql_count_code(i)
        name = await bot.get_chat(i)
        text = (f'**🎫 [{name.first_name}-{i}](tg://user?id={i})：\n• 已使用 - {a}  | • 未使用 - {e}\n'
                f'• 月码 - {b}    | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}\n'
                f'• 公益码(未用) - {pub_cnt}  | • 普通码(未用) - {norm_cnt}**')
        ls = [
            [f"🔎 详情", f"ch_admin_link-{i}"],
            ["🚮 删除我的未使用码", "delete_codes"],
        ]
        keyboard = ch_link_ikb(ls)
        await editMessage(call, text, buttons=keyboard)
    else:
        # Owner：显示所有管理员汇总
        await callAnswer(call, '🔍 查看管理们注册码...时长会久一点', True)
        a, b, c, d, f, e, pub_cnt, norm_cnt = sql_count_code()
        text = (f'**🎫 常用code数据：\n• 已使用 - {a}  | • 未使用 - {e}\n'
                f'• 月码 - {b}   | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}\n'
                f'• 公益码(未用) - {pub_cnt}  | • 普通码(未用) - {norm_cnt}**')
        ls = []
        admins.append(owner)
        for i in admins:
            name = await bot.get_chat(i)
            a, b, c, d, f, e, pub_cnt, norm_cnt = sql_count_code(i)
            text += f'\n👮🏻`{name.first_name}`: 月/{b}，季/{c}，半年/{d}，年/{f}，已用/{a}，未用/{e}（公益/{pub_cnt}·普通/{norm_cnt}）'
            f_item = [f"🔎 {name.first_name}", f"ch_admin_link-{i}"]
            ls.append(f_item)
        ls.append(["🚮 删除未使用码", f"delete_codes"])
        admins.remove(owner)
        keyboard = ch_link_ikb(ls)
        text += '\n详情查询 👇'
        await editMessage(call, text, buttons=keyboard)

# 删除未使用码
@bot.on_callback_query(filters.regex('delete_codes') & admins_on_filter)
async def delete_unused_codes(_, call):
    await callAnswer(call, '⚠️ 请确认要删除码的类别')
    is_owner = call.from_user.id == owner
    user_id = None if is_owner else call.from_user.id
    scope_text = "所有人" if is_owner else "您自己"

    await editMessage(call,
        f"请回复要删除的未使用码天数类别（仅删除{scope_text}生成的码）\n"
        "多个天数用空格分隔，例如: `5 30 180`\n"
        "输入 `all` 删除所有未使用码\n"
        "取消请输入 /cancel")

    content = await callListen(call, 120)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await gm_ikb(_, call)

    try:
        if content.text.lower() == 'all':
            count = sql_delete_all_unused(user_id=user_id)
            text = f"已删除所有未使用码，共 {count} 个"
            log_audit(category="code", action="delete", source="bot",
                      operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                      detail=f"删除未使用注册/续期码（全部），操作范围={scope_text}，共 {count} 个")
        else:
            days = [int(x) for x in content.text.split()]
            count = sql_delete_unused_by_days(days, user_id=user_id)
            text = f"已删除指定天数的未使用码，共 {count} 个"
            log_audit(category="code", action="delete", source="bot",
                      operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                      detail=f"删除未使用注册/续期码（天数={days}），操作范围={scope_text}，共 {count} 个")
        await content.delete()
    except ValueError:
        text = "❌ 输入格式错误"

    ls = []
    ls.append(["🔄 继续删除", f"delete_codes"])
    keyboard = ch_link_ikb(ls)
    await editMessage(call, text, buttons=keyboard)


@bot.on_callback_query(filters.regex('ch_admin_link'))
async def ch_admin_link(client, call):
    i = int(call.data.split('-')[1])
    if call.from_user.id != owner and call.from_user.id != i:
        return await callAnswer(call, '🚫 你怎么偷窥别人呀! 你又不是owner', True)
    await callAnswer(call, f'💫 管理员 {i} 的注册码')
    a, b, c, d, f, e, pub_cnt, norm_cnt = sql_count_code(i)
    name = await client.get_chat(i)
    text = (f'**🎫 [{name.first_name}-{i}](tg://user?id={i})：\n• 已使用 - {a}  | • 未使用 - {e}\n'
            f'• 月码 - {b}    | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}\n'
            f'• 公益码(未用) - {pub_cnt}  | • 普通码(未用) - {norm_cnt}**')
    await editMessage(call, text, date_ikb(i))


@bot.on_callback_query(
    filters.regex('register_mon') | filters.regex('register_sea')
    | filters.regex('register_half') | filters.regex('register_year') | filters.regex('register_used') | filters.regex('register_unused'))
async def buy_mon(_, call):
    await call.answer('✅ 显示注册码')
    cd, times, u = call.data.split('_')
    n = getattr(ExDate(), times)
    a, i = sql_count_p_code(u, n)
    if a is None:
        x = '**空**'
    else:
        x = a[0]
    first = await bot.get_chat(u)
    keyboard = await cr_paginate(i, 1, n)
    await sendMessage(call, f'🔎当前 {first.first_name} - **{n}**天，检索出以下 **{i}**页：\n\n{x}', keyboard)


# 检索翻页
@bot.on_callback_query(filters.regex('pagination_keyboard'))
async def paginate_keyboard(_, call):
    j, mode = map(int, call.data.split(":")[1].split('_'))
    await callAnswer(call, f'好的，将为您翻到第 {j} 页')
    a, b = sql_count_p_code(call.from_user.id, mode)
    keyboard = await cr_paginate(b, j, mode)
    text = a[j-1]
    await editMessage(call, f'🔎当前模式- **{mode}**天，检索出以下 **{b}**页链接：\n\n{text}', keyboard)


@bot.on_callback_query(filters.regex('set_renew'))
async def set_renew(_, call):
    await callAnswer(call, '🚀 进入续期设置')
    try:
        method = call.data.split('-')[1]
        old_val = getattr(_open, method)
        new_val = not old_val
        setattr(_open, method, new_val)
        save_config()
        log_audit(category="settings", action="update", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  before_val=str(old_val), after_val=str(new_val),
                  detail=f"续期开关 {method} 切换")
    except IndexError:
        pass
    finally:
        await editMessage(call, text='⭕ **关于用户组的续期功能**\n\n选择点击下方按钮开关任意兑换功能',
                          buttons=cr_renew_ikb())
@bot.on_callback_query(filters.regex('set_freeze_days') & admins_on_filter)
async def set_freeze_days(_, call):
    await callAnswer(call, '⭕ 设置封存天数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送封存账号天数，\n**注**：用户到期后被禁用，再过指定天数后会被删除 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        config.freeze_days = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **封存账号天数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了封存账号天数：{a}")
        log_audit(category="settings", action="update", source="bot",
                  operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                  detail=f"设置封存账号天数={a}")

@bot.on_callback_query(filters.regex('set_invite_lv'))
async def invite_lv_set(_, call):
    try:
        method = call.data
        if method.startswith('set_invite_lv-'):
            # 当选择具体等级时
            level = method.split('-')[1]
            if level in ['a', 'b', 'e', 'c', 'd']:
                old_lv = _open.invite_lv
                _open.invite_lv = level
                save_config()
                await callAnswer(call, f'✅ 已设置邀请等级为 {level}', show_alert=True)
                log_audit(category="settings", action="update", source="bot",
                          operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                          before_val=old_lv, after_val=level,
                          detail=f"设置邀请等级={level}")
        await callAnswer(call, '🚀 进入邀请等级设置')
        # 当点击设置邀请等级按钮时
        await editMessage(call,
            "请选择邀请等级:\n\n"
            f"当前等级: {_open.invite_lv}\n\n"
            "🅰️ - 白名单可使用\n"
            "🅱️ - 普通用户及以上可使用\n"
            "🟢 - 公益用户及以上可使用\n"
            "©️ - 已禁用用户及以上可使用\n"
            "🅳️ - 所有用户可使用",
            buttons=invite_lv_ikb())
        return
    except IndexError:
        pass
@bot.on_callback_query(filters.regex('set_checkin_lv'))
async def checkin_lv_set(_, call):
    try:
        method = call.data
        if method.startswith('set_checkin_lv-'):
            # 当选择具体等级时
            level = method.split('-')[1]
            if level in ['a', 'b', 'e', 'c', 'd']:
                old_lv = _open.checkin_lv
                _open.checkin_lv = level
                save_config()
                await callAnswer(call, f'✅ 已设置签到等级为 {level}', show_alert=True)
                log_audit(category="settings", action="update", source="bot",
                          operator_tg=call.from_user.id, operator_name=call.from_user.first_name,
                          before_val=old_lv, after_val=level,
                          detail=f"设置签到等级={level}")
        await callAnswer(call, '🚀 进入签到等级设置')
        # 当点击设置签到等级按钮时
        await editMessage(call,
            "请选择签到等级:\n\n"
            f"当前等级: {_open.checkin_lv}\n\n"
            "🅰️ - 白名单可签到\n"
            "🅱️ - 普通用户及以上可签到\n"
            "🟢 - 公益用户及以上可签到\n"
            "©️ - 已禁用用户及以上可签到\n"
            "🅳️ - 所有用户可签到",
            buttons=checkin_lv_ikb())
        return
    except IndexError:
        pass
