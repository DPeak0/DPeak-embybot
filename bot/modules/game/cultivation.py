"""
修行系统（单人玩法）
- 每次修行消耗 1 点体力
- 触发随机事件（好/坏/中性）
- 获得经验 + 可能掉落道具
- 游戏主菜单渲染
- 游戏商城（从 DB 读取条目，支持 Admin 增删改查）

【回调格式】个人菜单类均以 _{user_id} 结尾，实现菜单归属验证
"""
import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from pyrogram import filters
from pyromod.helpers import ikb

from bot import bot, LOGGER, sakura_b
from bot.func_helper.filters import user_in_group_on_filter
from bot.func_helper.msg_utils import callAnswer, editMessage, sendMessage
from bot.func_helper.utils import lv_allowed
from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
from bot.sql_helper.sql_game import (
    sql_get_or_create_player, sql_update_game_player,
    sql_add_item, sql_get_inventory,
    sql_get_shop_entries, sql_get_shop_entry,
)
from bot.modules.game.game_data import (
    get_game_config, get_realm, REALM_MAX_IDX,
    get_weighted_event, get_rarity_display, RARITY_DISPLAY,
    game_rate_limit_check,
)
from bot.modules.game.game_engine import (
    calc_current_stamina, stamina_recover_at,
    calc_cultivation_exp, calc_max_hp, calc_player_stats,
    apply_realm_stats
)


# ─────────────────────────── 菜单超时系统 ────────────────────────────────────
# {user_id: (message, last_active_time)}
_menu_sessions: dict = {}
_MENU_TIMEOUT = 300  # 秒


def _touch_menu(user_id: int, msg):
    """记录/刷新菜单活跃时间"""
    _menu_sessions[user_id] = (msg, datetime.now())


def _clear_menu(user_id: int):
    """菜单关闭时清除记录"""
    _menu_sessions.pop(user_id, None)


async def _menu_timeout_loop():
    """后台任务：每30秒扫描超时菜单并自动关闭"""
    while True:
        await asyncio.sleep(30)
        now = datetime.now()
        expired = [uid for uid, (_, t) in list(_menu_sessions.items())
                   if (now - t).total_seconds() >= _MENU_TIMEOUT]
        for uid in expired:
            entry = _menu_sessions.pop(uid, None)
            if not entry:
                continue
            msg, _ = entry
            try:
                await msg.delete()
            except Exception:
                try:
                    await msg.edit("⏰ 菜单已因长时间未操作自动关闭。")
                except Exception:
                    pass


# 启动后台超时扫描（延迟到首次菜单打开时初始化，避免 loop 未就绪）
_menu_timeout_task = None


def _ensure_menu_timeout_task():
    global _menu_timeout_task
    if _menu_timeout_task is None or _menu_timeout_task.done():
        try:
            loop = asyncio.get_running_loop()
            _menu_timeout_task = loop.create_task(_menu_timeout_loop())
        except RuntimeError:
            # 没有运行中的 loop，跳过（下次调用时重试）
            pass


# ─────────────────────────── 辅助函数 ────────────────────────────────────────

async def _get_tg_display_name(tg_id: int) -> str:
    """获取 TG 用户显示名称（first_name），失败时回退到 ID 字符串"""
    try:
        user = await bot.get_users(tg_id)
        return user.first_name or str(tg_id)
    except Exception:
        return str(tg_id)


def _check_game_access(user_id: int):
    """
    检查用户是否有资格游玩
    :return: (emby_record_or_None, error_text) — 正常时 error_text=None
    """
    cfg = get_game_config()
    if not cfg.get("enabled", True):
        return None, "⚠️ 修仙游戏当前已关闭，感谢理解！"

    if cfg.get("game_open_to_all", False):
        # 任何 TG 用户均可游玩，emby 记录可能为 None
        e = sql_get_emby(tg=user_id)
        return e, None

    e = sql_get_emby(tg=user_id)
    if not e or not lv_allowed(e.lv, 'b'):
        return None, "⚠️ 您需要先注册账户才能踏上修仙之路！\n\n请私聊 Bot 发送 /start 创建账户。"
    return e, None


async def _check_menu_owner(call, uid: int) -> bool:
    """验证点击者是否是菜单所有者，否则提示并返回 False"""
    if call.from_user.id != uid:
        name = await _get_tg_display_name(uid)
        await callAnswer(call, f"请不要点击 {name} 的面板哦～", show_alert=True)
        return False
    if not game_rate_limit_check(uid):
        await callAnswer(call, "⚠️ 请不要频繁操作，稍后再试！", show_alert=True)
        return False
    return True


def _get_player_status_text(player, e, current_stamina: int, tg_name: str = "") -> str:
    """生成玩家状态文本"""
    cfg = get_game_config()
    max_stamina = cfg["max_stamina"]
    realm = get_realm(player.realm)
    realm_name = realm[1]
    max_exp = realm[2]
    atk, def_, _ = calc_player_stats(player)

    # HP bar
    hp_pct = player.hp / max(player.max_hp, 1)
    hp_bar_len = 10
    hp_filled = round(hp_pct * hp_bar_len)
    hp_bar = "█" * hp_filled + "░" * (hp_bar_len - hp_filled)

    # Stamina bar
    st_pct = current_stamina / max(max_stamina, 1)
    st_filled = round(st_pct * hp_bar_len)
    st_bar = "⚡" * st_filled + "─" * (hp_bar_len - st_filled)

    exp_text = f"{player.exp}/{max_exp}" if max_exp > 0 else f"{player.exp}/已到顶"
    break_ready = max_exp > 0 and player.exp >= max_exp

    text = (
        f"**⚔️ 修仙游戏**\n\n"
        f"**道友：** {tg_name or (e.name if e else '修仙者')}\n"
        f"**修为：** {realm_name}\n"
        f"**修炼进度：** {exp_text}"
    )
    if break_ready:
        text += " 🔥 **可以突破！**"
    text += (
        f"\n\n"
        f"**💖 生命：** `{player.hp}/{player.max_hp}` [{hp_bar}]\n"
        f"**⚡ 体力：** `{current_stamina}/{max_stamina}` [{st_bar}]\n"
        f"**⚔️ 攻击：** `{atk}`　　**🛡️ 防御：** `{def_}`\n"
    )
    return text


def _get_main_menu_buttons(player, current_stamina: int, break_ready: bool, user_id: int) -> list:
    """生成主菜单按钮（所有个人回调嵌入 user_id）"""
    uid = user_id

    row1 = [
        ("🏔️ 修行", f"game_cultivate_{uid}"),
    ]
    if break_ready:
        row1.append(("⚡ 突破", f"game_break_{uid}"))

    row2 = [
        ("🐲 团本", f"game_raid_list_{uid}"),
        ("🎒 背包", f"game_inv_{uid}"),
    ]
    row3 = [
        ("🛒 商城", f"game_shop_{uid}"),
        ("📊 排行", f"game_rank_{uid}"),
    ]
    row4 = [
        ("📖 规则", f"game_rules_{uid}"),
        ("❌ 关闭", f"game_close_{uid}"),
    ]

    return [row1, row2, row3, row4]


# ─────────────────────────── 主菜单 ──────────────────────────────────────────

async def show_game_menu(call_or_msg, user_id: int, edit: bool = True):
    """渲染或发送游戏主菜单"""
    e, err = _check_game_access(user_id)
    if err:
        if edit:
            return await editMessage(call_or_msg, err)
        else:
            return await sendMessage(call_or_msg, err)

    player = sql_get_or_create_player(user_id)

    # 死亡状态检测
    is_dead = getattr(player, 'is_dead', False)
    dead_at = getattr(player, 'dead_at', None)

    if is_dead and dead_at is not None:
        # 检查是否可以自动复活（12小时后）
        cfg = get_game_config()
        auto_revive_hours = cfg.get("death_auto_revive_hours", 12)
        elapsed = datetime.now() - dead_at
        if elapsed >= timedelta(hours=auto_revive_hours):
            # 自动复活
            await auto_revive_player(user_id)
            LOGGER.info(f"【游戏-自动复活】tg={user_id} 自动复活成功")
            player = sql_get_or_create_player(user_id)
            is_dead = False
        else:
            # 显示死亡状态页面
            return await _show_death_page(call_or_msg, user_id, player, dead_at, edit=edit)

    current_stamina = calc_current_stamina(player.stamina, player.stamina_at)

    # 刷新境界对应的基础属性
    realm = get_realm(player.realm)
    expected_max_hp = calc_max_hp(player)
    if player.max_hp != expected_max_hp or player.attack != realm[4] or player.defense != realm[5]:
        sql_update_game_player(user_id,
                               max_hp=expected_max_hp,
                               attack=realm[4],
                               defense=realm[5])
        player = sql_get_or_create_player(user_id)

    max_exp = realm[2]
    break_ready = max_exp > 0 and player.exp >= max_exp

    tg_name = await _get_tg_display_name(user_id)
    text = _get_player_status_text(player, e, current_stamina, tg_name=tg_name)
    buttons_data = _get_main_menu_buttons(player, current_stamina, break_ready, user_id)
    buttons = ikb(buttons_data)

    _ensure_menu_timeout_task()
    if edit:
        await editMessage(call_or_msg, text, buttons=buttons)
        # call_or_msg 是 CallbackQuery 时取 .message，否则直接用
        msg_obj = getattr(call_or_msg, 'message', call_or_msg)
    else:
        await sendMessage(call_or_msg, text, buttons=buttons)
        msg_obj = call_or_msg  # Message 对象
    _touch_menu(user_id, msg_obj)


async def _show_death_page(call_or_msg, user_id: int, player, dead_at, edit: bool = True):
    """渲染死亡状态页面"""
    cfg = get_game_config()
    realm = get_realm(player.realm)
    realm_name = realm[1]
    max_exp = realm[2]
    auto_revive_hours = cfg.get("death_auto_revive_hours", 12)
    revive_stone_cost = cfg.get("revive_stone_cost", 50)
    revive_exp_pct = cfg.get("revive_exp_pct", 50)

    # 复活所需修为 = 当前境界上限的 revive_exp_pct%
    need_exp = int(max_exp * revive_exp_pct / 100) if max_exp > 0 else 0

    # 计算剩余复活时间
    elapsed = datetime.now() - dead_at
    remaining_td = timedelta(hours=auto_revive_hours) - elapsed
    remain_total_seconds = max(0, int(remaining_td.total_seconds()))
    remain_h = remain_total_seconds // 3600
    remain_m = (remain_total_seconds % 3600) // 60

    exp_max_text = str(max_exp) if max_exp > 0 else "已满"

    # 死亡惩罚详情
    death_exp_lost = getattr(player, 'death_exp_lost', None) or 0
    death_dropped_item = getattr(player, 'death_dropped_item', None)
    penalty_lines = [f"扣除修为 {death_exp_lost}"]
    if death_dropped_item:
        penalty_lines.append(f"损失道具《{death_dropped_item}》")
    penalty_text = "　".join(penalty_lines)

    text = (
        f"**💀 道友已陨落...**\n\n"
        f"**当前境界：** {realm_name}\n"
        f"**修炼进度：** {player.exp}/{exp_max_text}\n\n"
        f"**死亡惩罚：** {penalty_text}\n\n"
        f"**复活方式：**\n"
        f"💎 支付 {revive_stone_cost} {sakura_b} 立即复活（满血）\n"
        f"⚗️ 消耗当前境界上限 {revive_exp_pct}% 的修炼进度复活（需有 {need_exp}，当前 {player.exp}）\n"
        f"⏰ {auto_revive_hours}小时后自动复活（剩余 {remain_h}h{remain_m}m）"
    )

    uid = user_id
    btns = []
    btns.append([(f"💎 石子复活（{revive_stone_cost}石）", f"game_revive_stone_{uid}")])

    # 修为复活按钮（根据 need_exp 是否满足决定是否灰显）
    if max_exp > 0 and player.exp >= need_exp:
        btns.append([("⚗️ 修炼进度复活", f"game_revive_exp_{uid}")])
    else:
        btns.append([("⚗️ 修炼进度复活（进度不足）", f"game_revive_exp_{uid}")])

    btns.append([("🏠 关闭", f"game_close_{uid}")])

    buttons = ikb(btns)
    if edit:
        await editMessage(call_or_msg, text, buttons=buttons)
    else:
        await sendMessage(call_or_msg, text, buttons=buttons)


async def auto_revive_player(uid: int):
    """自动复活玩家（无惩罚）"""
    from bot.modules.game.game_engine import revive_player
    revive_player(uid)
    LOGGER.info(f"【游戏-自动复活】tg={uid}")


# ─────────────────────────── 修行确认页 ──────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_cultivate_(\d+)$'))
async def on_cultivate(_, call):
    """修行确认页（二次确认）"""
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return

    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    player = sql_get_or_create_player(uid)

    # 检查死亡状态
    if getattr(player, 'is_dead', False):
        return await callAnswer(call, "💀 道友已陨落，无法修行！请先复活。", show_alert=True)

    cfg = get_game_config()
    current_stamina = calc_current_stamina(player.stamina, player.stamina_at)

    if current_stamina < 1:
        recover_time = stamina_recover_at(player.stamina, player.stamina_at)
        time_str = recover_time.strftime('%H:%M') if recover_time else "未知"
        return await callAnswer(
            call,
            f"⚡ 体力不足！\n当前体力：0/{cfg['max_stamina']}\n"
            f"恢复满体力时间约：{time_str}\n\n可前往商城购买体力补充。",
            show_alert=True
        )

    realm = get_realm(player.realm)
    max_exp = realm[2]
    exp_text = f"{player.exp}/{max_exp}" if max_exp > 0 else f"{player.exp}/已到顶"

    text = (
        f"**🏔️ 准备修行**\n\n"
        f"**当前境界：** {realm[1]}\n"
        f"**修炼进度：** {exp_text}\n"
        f"**当前体力：** {current_stamina}/{cfg['max_stamina']}\n\n"
        f"本次修行将消耗 **1 点体力**，随机触发事件并获得经验与道具。\n\n"
        f"是否开始修行？"
    )
    btns = ikb([
        [("🏔️ 开始修行", f"game_cultivate_start_{uid}"),
         ("🔙 退出修行", f"game_menu_{uid}")],
    ])
    await editMessage(call, text, buttons=btns)


# ─────────────────────────── 修行执行 ────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_cultivate_start_(\d+)$'))
async def on_cultivate_start(_, call):
    """执行修行（已二次确认）"""
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return

    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    player = sql_get_or_create_player(uid)

    # 检查死亡状态
    if getattr(player, 'is_dead', False):
        return await callAnswer(call, "💀 道友已陨落，无法修行！请先复活。", show_alert=True)

    cfg = get_game_config()
    current_stamina = calc_current_stamina(player.stamina, player.stamina_at)

    if current_stamina < 1:
        recover_time = stamina_recover_at(player.stamina, player.stamina_at)
        time_str = recover_time.strftime('%H:%M') if recover_time else "未知"
        return await callAnswer(
            call,
            f"⚡ 体力不足！\n当前体力：0/{cfg['max_stamina']}\n"
            f"恢复满体力时间约：{time_str}\n\n可前往商城购买体力补充。",
            show_alert=True
        )

    # 消耗 1 点体力
    new_stamina = current_stamina - 1
    now = datetime.now()
    sql_update_game_player(uid, stamina=new_stamina, stamina_at=now)

    # 随机事件
    event = get_weighted_event()
    event_name = event["name"]
    event_desc = event["desc"]

    # 计算经验（直接使用绝对值范围）
    realm = get_realm(player.realm)
    max_exp = realm[2]
    exp_min = event.get("exp_min", 50)
    exp_max = event.get("exp_max", 200)
    if max_exp > 0:
        exp_gained = random.randint(min(exp_min, exp_max), max(exp_min, exp_max))
    else:
        exp_gained = 0  # 顶级境界

    # 修炼进度限制
    at_cap = False
    if max_exp > 0:
        if exp_gained >= 0:
            if player.exp >= max_exp:
                exp_gained = 0
                at_cap = True
            elif player.exp + exp_gained > max_exp:
                exp_gained = max_exp - player.exp
        else:
            # 负经验：不低于 0
            exp_gained = max(exp_gained, -player.exp)

    new_exp = player.exp + exp_gained
    hp_change = event.get("hp_change_pct", 0)  # 绝对 HP 变化量（正=回复，负=损失）
    current_hp = player.hp
    current_max_hp = calc_max_hp(player)

    if hp_change != 0:
        if hp_change > 0:
            current_hp = min(current_max_hp, current_hp + hp_change)
        else:
            current_hp = max(0, current_hp + hp_change)  # hp_change 已为负数

    # 检查 HP 降为 0 时触发死亡
    if current_hp <= 0:
        from bot.modules.game.game_engine import trigger_player_death
        death_result = trigger_player_death(uid)
        exp_lost = death_result.get("exp_lost", 0)
        dropped_name = death_result.get("dropped_name")

        death_lines = [
            f"**💀 {event_name}**\n",
            event_desc,
            "",
            f"⚠️ **道友在修行中陨落了！**",
            f"💔 修炼进度损失：{exp_lost}",
        ]
        if dropped_name:
            death_lines.append(f"📦 **{dropped_name}** 从背包中掉落！")
        death_lines.append(f"\n⚡ 剩余体力：{new_stamina}/{cfg['max_stamina']}")
        death_lines.append("\n请前往主菜单查看复活选项。")

        text = "\n".join(death_lines)
        buttons = ikb([
            [("🏠 返回", f"game_menu_{uid}")],
        ])
        await editMessage(call, text, buttons=buttons)
        return

    # 物品掉落：先判断整体触发概率，再按品质权重随机品质，从该品质物品池抽取
    item_drops = []
    item_drop_rate = event.get("item_drop_rate", 0)
    item_drop_max  = max(1, event.get("item_drop_max", 1))
    if item_drop_rate > 0 and random.randint(1, 100) <= item_drop_rate:
        from bot.sql_helper.sql_game import sql_get_all_items
        # 按品质权重随机品质
        rarity_weights = {
            "common":    cfg.get("cultiv_rarity_w_common",    55),
            "uncommon":  cfg.get("cultiv_rarity_w_uncommon",  28),
            "rare":      cfg.get("cultiv_rarity_w_rare",      12),
            "epic":      cfg.get("cultiv_rarity_w_epic",       4),
            "legendary": cfg.get("cultiv_rarity_w_legendary",  1),
        }
        total_rw = sum(rarity_weights.values())
        chosen_rarity = "common"
        if total_rw > 0:
            r = random.uniform(0, total_rw)
            cum = 0.0
            for rar, w in rarity_weights.items():
                cum += w
                if r <= cum:
                    chosen_rarity = rar
                    break
        # 从该品质物品池随机抽取（最多 item_drop_max 件）
        all_items = sql_get_all_items()
        pool = [it for it in all_items if it.rarity == chosen_rarity]
        if pool:
            # 突破丹药：只保留当前境界所需的那种，过滤掉不匹配的
            from bot.modules.game.game_data import get_breakthrough_pill
            needed_pill_id, _ = get_breakthrough_pill(player.realm)
            filtered = []
            for it in pool:
                if it.item_type == 'breakthrough':
                    if needed_pill_id and it.item_id == needed_pill_id:
                        filtered.append(it)
                else:
                    filtered.append(it)
            if filtered:
                pool = filtered
            picks = random.sample(pool, min(item_drop_max, len(pool)))
            for item_cfg in picks:
                sql_add_item(uid, item_cfg.item_id, 1)
                rarity_disp = get_rarity_display(item_cfg.rarity)
                item_drops.append(f"  • {item_cfg.name} [{rarity_disp}]")

    # 更新数据库
    sql_update_game_player(uid, exp=new_exp, hp=current_hp, max_hp=current_max_hp)
    player = sql_get_or_create_player(uid)

    # 构建结果文本
    result_lines = [
        f"**🏔️ {event_name}**\n",
        event_desc,
        "",
    ]
    if at_cap:
        result_lines.append(f"⚠️ **修炼进度已达境界极限（{player.exp}/{max_exp}），请突破后继续修炼！**")
    elif exp_gained > 0:
        result_lines.append(f"✨ **修炼进度 +{exp_gained}**（当前：{new_exp}{'/' + str(max_exp) if max_exp else '（已顶层）'}）")
    elif exp_gained < 0:
        result_lines.append(f"📉 **修为受损 {exp_gained}**（当前：{new_exp}{'/' + str(max_exp) if max_exp else ''}）")
    else:
        result_lines.append(f"😶 **修炼毫无所获**（当前：{new_exp}{'/' + str(max_exp) if max_exp else ''}）")
    if hp_change > 0:
        result_lines.append(f"💖 **生命 +{hp_change}**（当前：{current_hp}/{current_max_hp}）")
    elif hp_change < 0:
        result_lines.append(f"💔 **受到伤害 {hp_change}**（当前：{current_hp}/{current_max_hp}）")

    if item_drops:
        result_lines.append(f"\n🎁 **获得物品：**\n" + "\n".join(item_drops))

    if max_exp > 0 and new_exp >= max_exp:
        result_lines.append("\n\n🔥 **修炼进度已至极限，可以尝试突破！**")

    result_lines.append(f"\n⚡ 剩余体力：{new_stamina}/{cfg['max_stamina']}")

    text = "\n".join(result_lines)
    # 继续修行返回二次确认页
    buttons = ikb([
        [("🔄 继续修行", f"game_cultivate_{uid}"), ("🏠 返回", f"game_menu_{uid}")],
    ])
    await editMessage(call, text, buttons=buttons)


# ─────────────────────────── 复活处理 ────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_revive_stone_(\d+)$'))
async def on_revive_stone(_, call):
    """石子复活"""
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return

    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    cfg = get_game_config()
    revive_stone_cost = cfg.get("revive_stone_cost", 50)

    e_real = sql_get_emby(tg=uid)
    if not e_real:
        return await callAnswer(call, "账户异常", show_alert=True)

    player = sql_get_or_create_player(uid)
    if not getattr(player, 'is_dead', False):
        return await callAnswer(call, "道友尚未陨落，无需复活。", show_alert=True)

    if e_real.iv < revive_stone_cost:
        return await callAnswer(
            call,
            f"💎 {sakura_b} 不足！\n需要 {revive_stone_cost}，当前 {e_real.iv}",
            show_alert=True
        )

    # 扣除石子
    from bot.sql_helper.sql_audit import log_audit
    new_iv = e_real.iv - revive_stone_cost
    sql_update_emby(Emby.tg == uid, iv=new_iv)
    log_audit(
        category="credits",
        action="game_revive",
        source="bot",
        target_tg=uid,
        target_name=e_real.name,
        before_val=str(e_real.iv),
        after_val=str(new_iv),
        detail=f"石子复活消耗 {revive_stone_cost} {sakura_b}"
    )

    # 复活
    from bot.modules.game.game_engine import revive_player
    revive_player(uid)

    await callAnswer(call, "✅ 复活成功！")
    await show_game_menu(call, uid, edit=True)


@bot.on_callback_query(filters.regex(r'^game_revive_exp_(\d+)$'))
async def on_revive_exp(_, call):
    """修为复活"""
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return

    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    cfg = get_game_config()
    revive_exp_pct = cfg.get("revive_exp_pct", 50)

    player = sql_get_or_create_player(uid)
    if not getattr(player, 'is_dead', False):
        return await callAnswer(call, "道友尚未陨落，无需复活。", show_alert=True)

    realm = get_realm(player.realm)
    max_exp = realm[2]
    need_exp = int(max_exp * revive_exp_pct / 100) if max_exp > 0 else 0

    if max_exp == 0:
        return await callAnswer(call, "顶级境界无法使用修炼进度复活，请使用石子复活。", show_alert=True)

    if player.exp < need_exp:
        return await callAnswer(
            call,
            f"⚗️ 修炼进度不足！\n需要 {need_exp}，当前 {player.exp}",
            show_alert=True
        )

    # 扣除修为并复活
    new_exp = player.exp - need_exp
    sql_update_game_player(uid, exp=new_exp)

    from bot.modules.game.game_engine import revive_player
    revive_player(uid)

    await callAnswer(call, "✅ 复活成功！")
    await show_game_menu(call, uid, edit=True)


# ─────────────────────────── 商城 ─────────────────────────────────────────────

async def _show_shop(call, user_id: int):
    """渲染商城页面（从 DB 读取条目）"""
    e_real = sql_get_emby(tg=user_id)
    stones = e_real.iv if e_real else 0
    cfg = get_game_config()
    max_stamina = cfg["max_stamina"]

    player = sql_get_or_create_player(user_id)
    current_stamina = calc_current_stamina(player.stamina, player.stamina_at)

    entries = sql_get_shop_entries()

    text = (
        f"**🛒 修仙商城**\n\n"
        f"**⚡ 体力：** {current_stamina}/{max_stamina}\n"
        f"**💎 {sakura_b}：** {stones}\n\n"
        f"请选择要购买的商品："
    )

    btns = []
    if entries:
        row = []
        for entry in entries:
            btn_text = entry.name
            callback = f"game_shop_buy_{entry.shop_id}_{user_id}"
            row.append((btn_text, callback))
            if len(row) == 2:
                btns.append(row)
                row = []
        if row:
            btns.append(row)
    else:
        text += "\n\n⚠️ 商城暂无在售商品，请联系管理员配置。"

    btns.append([("🏠 返回主菜单", f"game_menu_{user_id}")])
    await editMessage(call, text, buttons=ikb(btns))


@bot.on_callback_query(filters.regex(r'^game_shop_(\d+)$'))
async def on_game_shop(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _show_shop(call, uid)


@bot.on_callback_query(filters.regex(r'^game_shop_buy_(.+)_(\d+)$'))
async def on_buy_shop_item(_, call):
    """商城商品购买页（从起购数量开始）"""
    main, uid_str = call.data.rsplit('_', 1)
    uid = int(uid_str)
    shop_id = main[len("game_shop_buy_"):]

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    entry = sql_get_shop_entry(shop_id)
    if not entry or not entry.enabled:
        return await callAnswer(call, "该商品不存在或已下架", show_alert=True)

    start_qty = getattr(entry, 'min_qty', 1)
    await _show_buy_page(call, uid, shop_id, qty=start_qty)


async def _show_buy_page(call, uid: int, shop_id: str, qty: int):
    """渲染购买页（含 +/- 数量按钮，实时显示总价）"""
    entry = sql_get_shop_entry(shop_id)
    if not entry or not entry.enabled:
        return await callAnswer(call, "该商品不存在或已下架", show_alert=True)

    e_real = sql_get_emby(tg=uid)
    stones = e_real.iv if e_real else 0

    min_qty  = max(1, getattr(entry, 'min_qty', 1) or 1)
    max_qty  = max(1, getattr(entry, 'max_qty', 1) or 1)
    qty_step = max(1, getattr(entry, 'qty_step', 1) or 1)

    # 保证 qty 在 [min_qty, max_qty] 内
    qty = max(min_qty, min(qty, max_qty))

    total_price = entry.price_stones * qty
    after_stones = stones - total_price

    cfg = get_game_config()
    max_stamina = cfg["max_stamina"]
    player = sql_get_or_create_player(uid)
    current_stamina = calc_current_stamina(player.stamina, player.stamina_at)

    # 描述（优先用物品管理中的 description）
    item_desc = ""
    item_name_display = entry.name or ""
    if entry.item_type == "stamina":
        can_add = max_stamina - current_stamina
        if can_add <= 0:
            return await callAnswer(call, "⚡ 体力已满，无需购买！", show_alert=True)
        actual_qty = min(qty, can_add)
        item_desc = f"⚡ 体力 +{actual_qty}（{current_stamina} → {current_stamina + actual_qty}/{max_stamina}）"
    else:
        from bot.sql_helper.sql_game import sql_get_item_config
        item_cfg = sql_get_item_config(entry.item_id) if entry.item_id else None
        if item_cfg:
            item_name_display = item_cfg.name
            item_desc = getattr(item_cfg, 'description', None) or f"获得 {item_cfg.name} ×{qty}"
        else:
            item_desc = f"获得 {entry.item_id or entry.name} ×{qty}"

    can_afford = stones >= total_price

    text = (
        f"**🛒 {item_name_display}**\n\n"
        f"**描述：** {item_desc}\n\n"
        f"**单件价格：** {entry.price_stones} {sakura_b}\n"
        f"**购买数量：** {qty}（单次购买上限 {max_qty}）\n"
        f"**合计：** {qty} × {entry.price_stones} = **{total_price} {sakura_b}**\n"
        f"**当前余额：** {stones} {sakura_b}\n"
        f"**购买后余额：** {after_stones} {sakura_b}"
        + ("" if can_afford else f"\n\n⚠️ {sakura_b} 不足，无法购买！")
    )

    prev_qty = max(min_qty, qty - qty_step)
    next_qty = min(max_qty, qty + qty_step)
    minus_cb   = f"game_shop_qty_{shop_id}_{prev_qty}_{uid}"
    plus_cb    = f"game_shop_qty_{shop_id}_{next_qty}_{uid}"
    confirm_cb = f"game_shop_confirm_{shop_id}_{qty}_{uid}"

    btns = [
        [(f"➖", minus_cb), (f"  {qty}  ", f"game_shop_buy_{shop_id}_{uid}"), (f"➕", plus_cb)],
        [
            ("✅ 确认购买" if can_afford else "💎 余额不足", confirm_cb if can_afford else f"game_shop_{uid}"),
            ("❌ 取消", f"game_shop_{uid}"),
        ],
    ]
    await callAnswer(call, "")
    await editMessage(call, text, buttons=ikb(btns))


@bot.on_callback_query(filters.regex(r'^game_shop_qty_(.+)_(\d+)_(\d+)$'))
async def on_shop_qty(_, call):
    """处理购买页 +/- 按钮（更新数量）"""
    # callback: game_shop_qty_{shop_id}_{qty}_{uid}
    parts = call.data.split('_')
    # parts: ['game','shop','qty', shop_id..., qty, uid]
    uid = int(parts[-1])
    qty = int(parts[-2])
    shop_id = '_'.join(parts[3:-2])

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    await _show_buy_page(call, uid, shop_id, qty)


@bot.on_callback_query(filters.regex(r'^game_shop_confirm_(.+)_(\d+)_(\d+)$'))
async def on_confirm_shop_item(_, call):
    """执行商城购买（已二次确认，含数量）"""
    parts = call.data.split('_')
    # callback: game_shop_confirm_{shop_id}_{qty}_{uid}
    uid = int(parts[-1])
    qty = int(parts[-2])
    shop_id = '_'.join(parts[3:-2])

    if not await _check_menu_owner(call, uid):
        return

    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    entry = sql_get_shop_entry(shop_id)
    if not entry or not entry.enabled:
        return await callAnswer(call, "该商品不存在或已下架", show_alert=True)

    max_qty  = getattr(entry, 'max_qty', 1)
    min_qty  = getattr(entry, 'min_qty', 1)
    qty_step = getattr(entry, 'qty_step', 1)
    qty = max(min_qty, min(qty, max_qty))
    total_price = entry.price_stones * qty

    e_real = sql_get_emby(tg=uid)
    if not e_real or e_real.iv < total_price:
        have = e_real.iv if e_real else 0
        return await callAnswer(
            call,
            f"💎 {sakura_b} 不足！\n需要 {total_price}，当前 {have}",
            show_alert=True
        )

    cfg = get_game_config()
    max_stamina = cfg["max_stamina"]

    # 扣除石子
    from bot.sql_helper.sql_audit import log_audit
    new_iv = e_real.iv - total_price
    sql_update_emby(Emby.tg == uid, iv=new_iv)
    log_audit(
        category="credits",
        action="game_shop",
        source="bot",
        target_tg=uid,
        target_name=e_real.name,
        before_val=str(e_real.iv),
        after_val=str(new_iv),
        detail=f"游戏商城购买：{entry.name} ×{qty}，消耗 {total_price} {sakura_b}"
    )

    result_text = ""

    if entry.item_type == "stamina":
        player = sql_get_or_create_player(uid)
        current_stamina = calc_current_stamina(player.stamina, player.stamina_at)
        can_buy = max_stamina - current_stamina
        actual_qty = min(qty, can_buy)
        if actual_qty <= 0:
            # 退款
            sql_update_emby(Emby.tg == uid, iv=e_real.iv)
            return await callAnswer(call, "⚡ 体力已满，无法购买！", show_alert=True)
        new_stamina = current_stamina + actual_qty
        sql_update_game_player(uid, stamina=new_stamina, stamina_at=datetime.now())
        result_text = f"⚡ 体力 +{actual_qty}（当前 {new_stamina}/{max_stamina}）"

    elif entry.item_type == "item" and entry.item_id:
        sql_add_item(uid, entry.item_id, qty)
        from bot.sql_helper.sql_game import sql_get_item_config
        item_cfg = sql_get_item_config(entry.item_id)
        item_name = item_cfg.name if item_cfg else entry.item_id
        result_text = f"获得 {item_name} ×{qty}"

    else:
        result_text = f"已购买 {entry.name} ×{qty}"

    # 展示购买结果页
    text = (
        f"**✅ 购买成功！**\n\n"
        f"**商品：** {entry.name} ×{qty}\n"
        f"**效果：** {result_text}\n"
        f"**消耗：** {total_price} {sakura_b}\n"
        f"**当前余额：** {new_iv} {sakura_b}"
    )
    btns = ikb([
        [("🛒 继续购物", f"game_shop_{uid}"),
         ("🏠 返回主菜单", f"game_menu_{uid}")],
    ])
    await callAnswer(call)
    await editMessage(call, text, buttons=btns)


# ─────────────────────────── 排行榜 ──────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_rank_(\d+)$'))
async def on_game_rank(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    from bot.sql_helper.sql_game import sql_get_realm_ranking
    from bot.sql_helper.sql_emby import sql_get_emby as get_emby
    from bot.modules.game.game_data import get_realm_name

    cfg = get_game_config()
    limit = cfg.get("rank_limit", 20)
    top = sql_get_realm_ranking(limit)

    lines = ["**📊 修仙排行榜（修为排名）**\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(top):
        e_info = get_emby(tg=p.tg)
        name = e_info.name if e_info else f"道友{p.tg}"
        medal = medals[i] if i < 3 else f"{i+1}."
        realm_name = get_realm_name(p.realm)
        lines.append(f"{medal} **{name}** — {realm_name}")

    if not top:
        lines.append("暂无修仙者，快来成为第一个吧！")

    text = "\n".join(lines)
    buttons = ikb([[("🏠 返回主菜单", f"game_menu_{uid}")]])
    await editMessage(call, text, buttons=buttons)


# ─────────────────────────── 菜单回调 ────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_rules_(\d+)$'))
async def on_game_rules(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return

    cfg = get_game_config()
    max_stamina = cfg.get("max_stamina", 10)
    stamina_recover = cfg.get("stamina_recover_minutes", 60)
    death_auto_revive = cfg.get("death_auto_revive_hours", 12)
    revive_stone_cost = cfg.get("revive_stone_cost", 50)

    text = (
        "**📖 修仙游戏规则**\n\n"
        "**🏔️ 修行**\n"
        f"每次修行消耗 1 点体力，随机触发事件获得修炼进度与道具。"
        f"体力上限 {max_stamina} 点，每 {stamina_recover} 分钟自动恢复 1 点。\n\n"
        "**⚡ 突破**\n"
        "修炼进度达到当前境界上限后，可点击突破按钮晋升境界，提升攻防与生命上限。\n\n"
        "**🐲 团本**\n"
        "多人协作副本，组队挑战强力 BOSS。参与者轮流行动，击败 BOSS 可获得丰厚奖励。\n\n"
        "**🎒 背包**\n"
        "存放修行中获得的道具，包括突破丹药、战斗道具等，可在战斗中使用。\n\n"
        "**🛒 商城**\n"
        "使用石子购买体力补充、道具等商品，助力修仙之路。\n\n"
        "**💀 死亡与复活**\n"
        f"HP 降为 0 时陨落，扣除部分修炼进度并可能掉落道具。\n"
        f"复活方式：① 消耗 {revive_stone_cost} 石子立即满血复活；"
        f"② 消耗当前境界上限 50% 的修炼进度复活；"
        f"③ 等待 {death_auto_revive} 小时自动复活。\n\n"
        "**📊 排行**\n"
        "查看境界最高的修仙者排名，争夺榜首！"
    )
    buttons = ikb([[("🏠 返回主菜单", f"game_menu_{uid}")]])
    await editMessage(call, text, buttons=buttons)


@bot.on_callback_query(filters.regex(r'^game_menu_(\d+)$'))
async def on_game_menu(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    await show_game_menu(call, uid, edit=True)


@bot.on_callback_query(filters.regex(r'^game_close_(\d+)$'))
async def on_game_close(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    _clear_menu(uid)
    try:
        await call.message.delete()
    except Exception:
        pass
