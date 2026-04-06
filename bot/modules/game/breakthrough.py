"""
境界突破系统
- 经验满后可手动触发突破
- 丹药加减内联于突破页面，+/- 动态更新成功率
- 只有对应境界的丹药可使用（由 get_breakthrough_pill 返回当前境界所需丹药）
- 每次突破失败额外积累 break_fail_bonus_pct% 成功率（存入 break_fail_streak）
- 成功奖励石子（主要）或 Emby 天数（随机天数范围由配置决定）
- 失败损失 50% 修为，已使用的丹药不退还

【回调格式】
  game_break_{uid}              → 突破页（pending=0）
  game_break_c{n}_{uid}         → 突破页（pending=n，点+/-触发，动态刷新）
  game_break_confirm_c{n}_{uid} → 执行突破（消耗 n 个丹药后掷骰）
"""
import random
from datetime import datetime, timedelta

from pyrogram import filters
from pyromod.helpers import ikb

from bot import bot, LOGGER, sakura_b
from bot.func_helper.msg_utils import callAnswer, editMessage
from bot.modules.game.game_data import (
    get_game_config, get_realm, REALM_MAX_IDX, get_breakthrough_pill,
    INFINITE_REALM_START_IDX
)
from bot.modules.game.game_engine import (
    apply_realm_stats, grant_stone_reward, grant_emby_days_reward
)
from bot.modules.game.cultivation import _check_game_access, _check_menu_owner
from bot.sql_helper.sql_game import (
    sql_get_or_create_player, sql_update_game_player,
    sql_get_inventory_item, sql_use_item, sql_get_item_config,
    sql_get_major_realm_by_min_idx, sql_player_has_killed_boss,
    sql_get_boss
)


# ─────────────────────────── 突破页面渲染 ────────────────────────────────────

async def _render_break_page(call, uid: int, pending: int = 0):
    """
    渲染突破页面。
    pending = 本次打算使用的丹药数量（随 +/- 按钮实时更新）
    """
    cfg = get_game_config()
    player = sql_get_or_create_player(uid)

    # 冷却检查
    cooldown_at = getattr(player, 'break_cooldown_at', None)
    if cooldown_at and cooldown_at > datetime.now():
        remaining = cooldown_at - datetime.now()
        h = int(remaining.total_seconds() // 3600)
        m = int((remaining.total_seconds() % 3600) // 60)
        return await callAnswer(call, f"⏳ 突破冷却中，还需 {h}h{m}m 后方可再次尝试。", show_alert=True)

    realm = get_realm(player.realm)
    realm_name = realm[1]
    max_exp = realm[2]

    is_infinite = player.realm >= INFINITE_REALM_START_IDX

    if not is_infinite and player.realm >= REALM_MAX_IDX:
        return await callAnswer(call, "🌟 您已到达最高有限境界！若您位于 DP巅峰，可继续突破。", show_alert=True)

    if max_exp > 0 and player.exp < max_exp:
        return await callAnswer(
            call,
            f"修为尚未圆满，继续修炼吧！\n当前：{player.exp}/{max_exp}",
            show_alert=True
        )

    pill_id, pill_name = get_breakthrough_pill(player.realm)
    # 无限境界（DP巅峰）不需要丹药
    if is_infinite:
        pill_id, pill_name = None, None
    base_rate = cfg["base_break_rate"]
    max_rate = cfg["max_break_rate"]

    # 获取当前境界所需丹药配置与背包数量
    bag_qty = 0
    boost_per = 0
    if pill_id:
        pill_cfg = sql_get_item_config(pill_id)
        boost_per = (pill_cfg.break_boost if pill_cfg else 20) or 20
        inv = sql_get_inventory_item(uid, pill_id)
        bag_qty = inv.quantity if inv else 0

    # 钳位：不能超过背包数量
    pending = max(0, min(pending, bag_qty))

    streak = getattr(player, 'break_fail_streak', 0) or 0
    fail_bonus_pct = cfg.get("break_fail_bonus_pct", 5)
    streak_bonus = streak * fail_bonus_pct

    pending_bonus = pending * boost_per
    total_rate = min(max_rate, base_rate + pending_bonus + streak_bonus)

    next_realm = get_realm(player.realm + 1)
    next_realm_name = next_realm[1]

    # ── 文本组装 ──
    text = (
        f"**⚡ 境界突破**\n\n"
        f"**当前境界：** {realm_name}\n"
        f"**当前修为：** {player.exp}/{max_exp if max_exp > 0 else '已满'}\n"
        f"**突破目标：** {next_realm_name}\n\n"
        f"**基础成功率：** {base_rate}%\n"
    )
    if is_infinite:
        text += "✨ **DP巅峰境界无需丹药，可无限突破！**\n"
    if streak > 0:
        text += f"**连败加成：** +{streak_bonus}%（已连败 {streak} 次）\n"
    if pill_id:
        text += f"\n**💊 当前所需：{pill_name}（拥有 {bag_qty} 个）**\n"
        if pending > 0:
            text += f"**丹药加成：** +{pending_bonus}%\n"
    text += f"**当前成功率：** **{total_rate}%**\n\n"
    text += "⚠️ 突破失败将损失 50% 修炼进度，使用的丹药不会退还。"

    # ── 前置任务提示 ──
    try:
        next_realm_idx = player.realm + 1
        prereq_cfg = sql_get_major_realm_by_min_idx(next_realm_idx)
        if prereq_cfg and getattr(prereq_cfg, 'prereq_enabled', False):
            prereq_boss_id = getattr(prereq_cfg, 'prereq_boss_id', None)
            if prereq_boss_id:
                boss_cfg = sql_get_boss(prereq_boss_id)
                boss_name = boss_cfg.name if boss_cfg else prereq_boss_id
                has_killed = sql_player_has_killed_boss(uid, prereq_boss_id)
                if has_killed:
                    text += f"\n\n✅ 前置任务已完成：击败【{boss_name}】"
                else:
                    text += f"\n\n🔒 **前置任务未完成！**\n需先击败团本 BOSS【{boss_name}】才能突破至「{prereq_cfg.major_realm}」"
    except Exception:
        pass

    # ── 按钮组装 ──
    btns = []

    if pill_id:
        # 丹药加减行
        minus_cb = f"game_break_c{max(0, pending - 1)}_{uid}"
        plus_cb  = f"game_break_c{min(bag_qty, pending + 1)}_{uid}"
        btns.append([
            ("➖", minus_cb),
            (f"使用：{pending} 个", f"game_break_c{pending}_{uid}"),
            ("➕", plus_cb),
        ])

    confirm_label = "🚀 立刻突破" if pending == 0 else f"🚀 突破（{pending}个丹药）"
    btns.append([
        (confirm_label, f"game_break_confirm_c{pending}_{uid}"),
        ("🏠 返回", f"game_menu_{uid}"),
    ])

    await callAnswer(call)
    await editMessage(call, text, buttons=ikb(btns))


# ─────────────────────────── 突破页入口 ──────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_break_(\d+)$'))
async def on_game_break(_, call):
    """打开突破页，pending 归零"""
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _render_break_page(call, uid, pending=0)


# ─────────────────────────── +/- 按钮回调 ────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_break_c(\d+)_(\d+)$'))
async def on_break_pill_count(_, call):
    """点 +/- 调整丹药数量，重新渲染突破页"""
    # 格式：game_break_c{n}_{uid}
    parts = call.data.split('_')   # ['game','break','c{n}','{uid}']
    pending = int(parts[2][1:])    # 去掉 'c'
    uid     = int(parts[3])

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _render_break_page(call, uid, pending=pending)


# ─────────────────────────── 执行突破 ────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_break_confirm_c(\d+)_(\d+)$'))
async def on_break_confirm(_, call):
    """
    执行突破：先从背包消耗 pending 个对应丹药，再掷骰决定成败。
    格式：game_break_confirm_c{n}_{uid}
    """
    parts   = call.data.split('_')   # ['game','break','confirm','c{n}','{uid}']
    pending = int(parts[3][1:])      # 去掉 'c'
    uid     = int(parts[4])

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    cfg    = get_game_config()
    player = sql_get_or_create_player(uid)
    realm  = get_realm(player.realm)
    realm_name = realm[1]
    max_exp    = realm[2]

    is_infinite = player.realm >= INFINITE_REALM_START_IDX

    if not is_infinite and player.realm >= REALM_MAX_IDX:
        return await callAnswer(call, "已是最高有限境界！", show_alert=True)
    if max_exp > 0 and player.exp < max_exp:
        return await callAnswer(call, "修为尚未圆满！", show_alert=True)

    # ── 前置任务检查（进入新大境界时校验）──
    next_realm_idx = player.realm + 1
    try:
        prereq_cfg = sql_get_major_realm_by_min_idx(next_realm_idx)
        if prereq_cfg and getattr(prereq_cfg, 'prereq_enabled', False):
            prereq_boss_id = getattr(prereq_cfg, 'prereq_boss_id', None)
            if prereq_boss_id and not sql_player_has_killed_boss(uid, prereq_boss_id):
                boss_cfg = sql_get_boss(prereq_boss_id)
                boss_name = boss_cfg.name if boss_cfg else prereq_boss_id
                return await callAnswer(
                    call,
                    f"⚔️ 突破至「{prereq_cfg.major_realm}」需先完成前置任务：\n"
                    f"击败【{boss_name}】一次！\n\n"
                    f"请前往团本挑战该 BOSS 后再尝试突破。",
                    show_alert=True
                )
    except Exception as _prereq_ex:
        LOGGER.warning(f"【突破】前置任务检查失败，跳过: {_prereq_ex}")

    # ── 消耗丹药（无限境界跳过）──
    pill_id, pill_name = get_breakthrough_pill(player.realm)
    if is_infinite:
        pill_id, pill_name = None, None
    pill_bonus = 0
    actually_used = 0
    if pill_id and pending > 0:
        pill_cfg  = sql_get_item_config(pill_id)
        boost_per = (pill_cfg.break_boost if pill_cfg else 20) or 20
        for _ in range(pending):
            if not sql_use_item(uid, pill_id):
                break
            actually_used += 1
        pill_bonus = actually_used * boost_per

    base_rate  = cfg["base_break_rate"]
    fail_bonus_pct = cfg.get("break_fail_bonus_pct", 5)
    streak = getattr(player, 'break_fail_streak', 0) or 0
    streak_bonus = streak * fail_bonus_pct
    total_rate = min(cfg["max_break_rate"], base_rate + pill_bonus + streak_bonus)

    roll    = random.randint(1, 100)
    success = roll <= total_rate

    next_realm_idx  = player.realm + 1
    next_realm      = get_realm(next_realm_idx)
    next_realm_name = next_realm[1]

    pill_info = f"（使用了 {actually_used} 个 {pill_name}）\n" if actually_used > 0 else ""

    if success:
        new_exp  = 0  # 突破成功：exp 归零
        new_realm = next_realm_idx
        base_max_hp, base_atk, base_def = apply_realm_stats(
            type('P', (), {'realm': new_realm})()
        )
        new_max_hp = base_max_hp
        new_hp     = min(player.hp, new_max_hp)

        success_cd_enabled = cfg.get("break_success_cd_enabled", True)
        cd_hours = cfg.get("break_success_cooldown_hours", 168)
        cd_at = (datetime.now() + timedelta(hours=cd_hours)) if success_cd_enabled else None
        sql_update_game_player(
            uid,
            realm=new_realm, exp=new_exp,
            max_hp=new_max_hp, hp=new_hp,
            attack=base_atk, defense=base_def,
            break_pill_bonus=0, break_fail_streak=0,
            break_cooldown_at=cd_at
        )

        stone_rate = cfg["break_reward_stone_rate"]
        if random.randint(1, 100) <= stone_rate:
            stone_min = cfg.get("break_reward_stone_min", 10)
            stone_max = cfg.get("break_reward_stone_max", 50)
            reward_amount = random.randint(stone_min, max(stone_min, stone_max)) * (new_realm + 1)
            grant_stone_reward(uid, reward_amount, f"突破至{next_realm_name}")
            reward_text = f"💎 **获得 {reward_amount} {sakura_b}！**"
        else:
            days_min = cfg.get("break_reward_emby_days_min", 1)
            days_max = cfg.get("break_reward_emby_days_max", 3)
            days = random.randint(days_min, max(days_min, days_max))
            grant_emby_days_reward(uid, days, f"突破至{next_realm_name}")
            reward_text = f"📅 **Emby 到期延长 {days} 天！**"

        streak_info = f"（连败加成已清零）\n" if streak > 0 else ""
        if success_cd_enabled:
            cd_text = f"⏳ 下次突破冷却：{cd_hours} 小时"
        else:
            cd_text = "⏳ 成功冷却已关闭，可立刻再次突破"
        text = (
            f"**🎉 突破成功！**\n\n"
            f"{pill_info}"
            f"骰子：{roll} ≤ {total_rate}（成功率）\n\n"
            f"**境界提升：** {realm_name} → **{next_realm_name}**\n"
            f"修炼进度归零（进入新境界重新积累）\n"
            f"{streak_info}\n"
            f"{reward_text}\n\n"
            f"💖 新的最大生命：{new_max_hp}\n"
            f"⚔️ 攻击：{base_atk}　🛡️ 防御：{base_def}\n\n"
            f"{cd_text}"
        )

    else:
        new_exp = max(0, int(player.exp * 0.5))
        new_streak = streak + 1
        next_bonus = new_streak * fail_bonus_pct
        fail_cd_enabled = cfg.get("break_fail_cd_enabled", True)
        cd_hours = cfg.get("break_fail_cooldown_hours", 24)
        cd_at = (datetime.now() + timedelta(hours=cd_hours)) if fail_cd_enabled else None
        sql_update_game_player(uid, exp=new_exp, break_pill_bonus=0, break_fail_streak=new_streak,
                               break_cooldown_at=cd_at)
        exp_lost = player.exp - new_exp

        fail_pill = f"（使用了 {actually_used} 个 {pill_name}，丹药已消耗）\n" if actually_used > 0 else ""
        if fail_cd_enabled:
            cd_text = f"⏳ 冷却 {cd_hours} 小时后可再次尝试突破"
        else:
            cd_text = "⏳ 失败冷却已关闭，可立刻再次尝试"
        text = (
            f"**💨 突破失败...**\n\n"
            f"{fail_pill}"
            f"骰子：{roll} > {total_rate}（成功率）\n\n"
            f"境界未能突破，还需继续修炼...\n"
            f"💔 损失修炼进度 {exp_lost}（当前：{new_exp}/{max_exp}）\n\n"
            f"🔥 **连败加成 +{fail_bonus_pct}%**，下次突破成功率 +{next_bonus}%（已积累）\n"
            f"{cd_text}\n"
            f"收拾心情，继续努力吧！"
        )

    btns = ikb([[("🏠 返回主菜单", f"game_menu_{uid}")]])
    await callAnswer(call)
    await editMessage(call, text, buttons=btns)
