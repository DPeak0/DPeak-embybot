"""
团本系统（多人回合制战斗）
- 2-4 人参与，回合制
- BOSS 预告下回合动作
- 玩家可选：攻击/防御/使用道具/逃跑
- 超时自动跳过，超时 N 次自动逃跑
- DPS 评分 + 掉落分配
- BOSS 击败后进入 CD 冷却
"""
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict

from pyrogram import filters, enums
from pyrogram.errors import MessageNotModified, FloodWait
from pyromod.helpers import ikb

from bot import bot, LOGGER, sakura_b
from bot.func_helper.msg_utils import callAnswer, editMessage, sendMessage
from bot.modules.game.game_data import (
    get_game_config, get_realm_name, REALM_MAX_IDX, game_rate_limit_check
)
from bot.modules.game.game_engine import (
    roll_attack, roll_defend, roll_boss_attack,
    roll_heal, roll_shield,
    apply_damage_to_target,
    get_boss_next_action, boss_action_display,
    assign_loot_by_dps, calc_player_stats,
    calc_max_hp
)
from bot.modules.game.cultivation import _check_game_access, show_game_menu
from bot.sql_helper.sql_game import (
    sql_get_all_bosses, sql_get_boss, sql_get_loot_table,
    sql_create_raid, sql_get_raid, sql_get_active_raid_by_chat,
    sql_get_boss_cooldown, sql_update_raid,
    sql_add_participant, sql_get_participants,
    sql_update_participant,
    sql_get_or_create_player, sql_update_game_player,
    sql_add_item, sql_get_item_config, sql_get_inventory_item, sql_use_item,
    sql_record_boss_kill,
    GameRaid, GameRaidParticipant
)

# ── 战斗日志内存缓存 {raid_id: deque(maxlen=3)} ───────────────────────────────
from collections import deque
_raid_log_cache: dict = {}  # {raid_id: deque of detail str}


async def _tg_name(tg_id: int) -> str:
    """获取 TG 用户显示名称，带内存缓存（10分钟），失败时回退到 ID 字符串"""
    now = datetime.now()
    cached = _tg_name_cache.get(tg_id)
    if cached and (now - cached[1]).total_seconds() < 600:
        return cached[0]
    try:
        user = await bot.get_users(tg_id)
        name = user.first_name or str(tg_id)
    except Exception:
        name = str(tg_id)
    _tg_name_cache[tg_id] = (name, now)
    return name

async def _tg_names_batch(tg_ids: list) -> dict:
    """并发批量获取 TG 用户名，返回 {tg_id: name}"""
    results = await asyncio.gather(*[_tg_name(tg_id) for tg_id in tg_ids], return_exceptions=True)
    return {tg_id: (name if isinstance(name, str) else str(tg_id))
            for tg_id, name in zip(tg_ids, results)}



# {tg_id: (name, datetime)}
_tg_name_cache: Dict[int, tuple] = {}

# {raid_id: asyncio.Task}
_timeout_tasks: Dict[int, asyncio.Task] = {}


def _log_raid(raid_id: int, detail: str):
    """追加一条战斗日志到内存缓存（最多保留3条）"""
    if raid_id not in _raid_log_cache:
        _raid_log_cache[raid_id] = deque(maxlen=3)
    _raid_log_cache[raid_id].append(detail)


def _get_raid_logs(raid_id: int) -> list:
    """获取最近3条战斗日志（正序）"""
    return list(_raid_log_cache.get(raid_id, []))


def _clear_raid_logs(raid_id: int):
    """团本结束后清理内存日志"""
    _raid_log_cache.pop(raid_id, None)



# ─────────────────────────── 招募超时 ────────────────────────────────────────
# {raid_id: asyncio.Task}
_recruit_timeout_tasks: dict = {}
_RECRUIT_TIMEOUT = 300  # 秒


def _start_recruit_timeout(raid_id: int, chat_id: int, message_id: int):
    """启动招募超时任务，300秒无操作自动解散"""
    _cancel_recruit_timeout(raid_id)

    async def _timeout():
        await asyncio.sleep(_RECRUIT_TIMEOUT)
        raid = sql_get_raid(raid_id)
        if not raid or raid.status != 'recruiting':
            return
        sql_update_raid(raid_id, status='failed')
        _clear_raid_logs(raid_id)
        try:
            msg = await bot.get_messages(chat_id, message_id)
            await msg.edit("⏰ 招募已因长时间无人操作自动解散。")
        except Exception:
            pass

    try:
        loop = asyncio.get_running_loop()
        _recruit_timeout_tasks[raid_id] = loop.create_task(_timeout())
    except RuntimeError:
        pass


def _cancel_recruit_timeout(raid_id: int):
    task = _recruit_timeout_tasks.pop(raid_id, None)
    if task and not task.done():
        task.cancel()


# ─────────────────────────── 团本列表 ────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_raid_list_(\d+)$'))
async def on_raid_list(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    from bot.modules.game.cultivation import _check_menu_owner
    if not await _check_menu_owner(call, uid):
        return

    user_id = uid
    e, err = _check_game_access(user_id)
    if err:
        return await callAnswer(call, err, show_alert=True)

    # 检查死亡状态
    player = sql_get_or_create_player(user_id)
    if getattr(player, 'is_dead', False):
        return await callAnswer(call, "💀 道友已陨落，无法参与团本！请先复活。", show_alert=True)

    bosses = sql_get_all_bosses()
    if not bosses:
        return await editMessage(call, "⚠️ 暂无可用团本，请联系管理员配置 BOSS！",
                                 buttons=ikb([[("🏠 返回", f"game_menu_{uid}")]]))

    lines = ["**🐲 团本列表**\n", "选择要挑战的 BOSS："]
    btns = []

    for boss in bosses:
        chat_id = call.message.chat.id
        cooldown_raid = sql_get_boss_cooldown(boss.boss_id, chat_id)
        is_cd = False
        if cooldown_raid and cooldown_raid.next_spawn_at:
            if cooldown_raid.next_spawn_at > datetime.now():
                is_cd = True
            else:
                sql_update_raid(cooldown_raid.id, status='completed')

        realm_name = get_realm_name(boss.recommend_realm)
        btn_label = f"{'🔴 ' if is_cd else ''}挑战 {boss.name}（{realm_name}）{'[CD]' if is_cd else ''}"
        if is_cd:
            btns.append([(btn_label, f"game_raid_cd_{boss.boss_id}")])
        else:
            btns.append([(btn_label, f"game_raid_info_{boss.boss_id}_{uid}")])

    btns.append([("🏠 返回主菜单", f"game_menu_{uid}")])
    await editMessage(call, "\n".join(lines), buttons=ikb(btns))


@bot.on_callback_query(filters.regex('^game_raid_cd_(.+)$'))
async def on_raid_cd(_, call):
    await callAnswer(call, "此 BOSS 正在冷却中，请等待刷新！", show_alert=True)


@bot.on_callback_query(filters.regex(r'^game_raid_info_(.+)_(\d+)$'))
async def on_raid_info(_, call):
    """展示 BOSS 详情 + 开始组队按钮"""
    # 末尾 _{uid}，剩余为 boss_id
    main, uid_str = call.data.rsplit('_', 1)
    uid = int(uid_str)
    boss_id = main[len("game_raid_info_"):]

    user_id = call.from_user.id
    e, err = _check_game_access(user_id)
    if err:
        return await callAnswer(call, err, show_alert=True)

    boss = sql_get_boss(boss_id)
    if not boss:
        return await callAnswer(call, "BOSS 不存在或已关闭", show_alert=True)

    chat_id = call.message.chat.id
    active = sql_get_active_raid_by_chat(chat_id, boss_id)

    recommend_name = get_realm_name(boss.recommend_realm)
    text = (
        f"**⚔️ {boss.name}**\n\n"
        f"推荐修为：{recommend_name}\n"
        f"基础血量：{boss.hp}　基础护盾：{boss.shield}（按人数倍增）\n"
        f"攻击：{boss.atk_min}~{boss.atk_max}\n"
        f"击杀冷却：{boss.cd_hours} 小时\n\n"
        f"人数：{boss.min_players}~{boss.max_players} 人（至少 {boss.min_players} 人可开始战斗）\n"
    )
    btns = []
    if active:
        if active.status == 'recruiting':
            text += f"\n🟡 当前已有组队中的团本（{len(sql_get_participants(active.id))} 人）"
            btns.append([(f"加入当前团本", f"game_raid_join_{active.id}")])
        elif active.status == 'active':
            text += f"\n🔴 当前战斗进行中，无法加入新队伍"
    else:
        btns.append([(f"🚀 发起组队", f"game_raid_start_{boss_id}")])

    btns.append([("🔙 返回列表", f"game_raid_list_{uid}")])
    await editMessage(call, text, buttons=ikb(btns))


# ─────────────────────────── 发起组队 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_start_(.+)$'))
async def on_raid_start_recruit(_, call):
    """创建新的团本招募"""
    user_id = call.from_user.id
    e, err = _check_game_access(user_id)
    if err:
        return await callAnswer(call, err, show_alert=True)

    boss_id = call.data[len("game_raid_start_"):]
    boss = sql_get_boss(boss_id)
    if not boss:
        return await callAnswer(call, "BOSS 不存在", show_alert=True)

    chat_id = call.message.chat.id
    cfg = get_game_config()
    max_players = getattr(boss, 'max_players', None) or 4

    # 检查冷却
    cd_raid = sql_get_boss_cooldown(boss_id, chat_id)
    if cd_raid and cd_raid.next_spawn_at and cd_raid.next_spawn_at > datetime.now():
        remaining = cd_raid.next_spawn_at - datetime.now()
        h = int(remaining.total_seconds() // 3600)
        m = int((remaining.total_seconds() % 3600) // 60)
        return await callAnswer(call, f"此 BOSS 冷却中，剩余 {h}h{m}m", show_alert=True)

    # 检查是否已有进行中
    active = sql_get_active_raid_by_chat(chat_id, boss_id)
    if active:
        return await callAnswer(call, "已有进行中的团本，请加入现有队伍！", show_alert=True)

    # 创建团本
    raid = sql_create_raid(boss_id, chat_id, boss.hp)
    if not raid:
        return await callAnswer(call, "创建团本失败，请稍后重试", show_alert=True)

    # 发起者加入（使用实际当前 HP）
    player = sql_get_or_create_player(user_id)
    current_hp = player.hp
    max_hp = calc_max_hp(player)
    sql_add_participant(raid.id, user_id, hp=current_hp, max_hp=max_hp, join_order=1)

    name = await _tg_name(user_id)
    text = _format_recruit_text(raid.id, boss, [{"tg": user_id, "name": name}], max_players)
    btns = _recruit_buttons(raid.id)

    msg = await call.message.edit(text=text, reply_markup=ikb(btns))
    if msg:
        sql_update_raid(raid.id, message_id=msg.id)
        _start_recruit_timeout(raid.id, call.message.chat.id, msg.id)

    # 血量不满时弹窗提醒
    if current_hp < max_hp:
        await callAnswer(call, f"⚠️ 您的血量不满！({current_hp}/{max_hp})\n建议回复生命后再参战。", show_alert=True)


def _format_recruit_text(raid_id: int, boss, participants_info: list, max_players: int) -> str:
    cur = len(participants_info)
    min_players = getattr(boss, 'min_players', None) or 2
    lines = [
        f"**🐲 {boss.name} - 组队中**\n",
        f"推荐修为：{get_realm_name(boss.recommend_realm)}\n",
        f"**参与者（{cur}/{max_players}）：**",
    ]
    for i, p in enumerate(participants_info):
        lines.append(f"  {i+1}. {p['name']}")
    lines.append(f"\n⚠️ 至少 {min_players} 人方可开战，最多 {max_players} 人")
    return "\n".join(lines)


def _recruit_buttons(raid_id: int) -> list:
    return [
        [("➕ 加入队伍", f"game_raid_join_{raid_id}"),
         ("⚔️ 开始战斗", f"game_raid_begin_{raid_id}")],
        [("❌ 解散队伍", f"game_raid_disband_{raid_id}")],
    ]


# ─────────────────────────── 加入队伍 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_join_(\\d+)$'))
async def on_raid_join(_, call):
    user_id = call.from_user.id
    e, err = _check_game_access(user_id)
    if err:
        return await callAnswer(call, err, show_alert=True)

    raid_id = int(call.data.split('_')[-1])
    cfg = get_game_config()

    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'recruiting':
        return await callAnswer(call, "团本不在招募中", show_alert=True)

    _boss = sql_get_boss(raid.boss_id)
    max_players = (getattr(_boss, 'max_players', None) or 4)

    participants = sql_get_participants(raid_id)
    if any(p.tg == user_id for p in participants):
        return await callAnswer(call, "您已在队伍中！", show_alert=True)

    if len(participants) >= max_players:
        return await callAnswer(call, f"队伍已满（{max_players} 人）！", show_alert=True)

    # 使用实际当前 HP
    player = sql_get_or_create_player(user_id)
    current_hp = player.hp
    max_hp = calc_max_hp(player)
    sql_add_participant(raid_id, user_id, hp=current_hp, max_hp=max_hp,
                        join_order=len(participants) + 1)

    # 刷新招募消息
    participants = sql_get_participants(raid_id)
    boss = sql_get_boss(raid.boss_id)
    tg_ids = [p.tg for p in participants]
    p_names = []
    for tg_id in tg_ids:
        p_names.append({"tg": tg_id, "name": await _tg_name(tg_id)})

    text = _format_recruit_text(raid_id, boss, p_names, max_players)
    btns = _recruit_buttons(raid_id)
    try:
        await call.message.edit(text=text, reply_markup=ikb(btns))
    except MessageNotModified:
        pass

    # 血量不满时给警告
    if current_hp < max_hp:
        await callAnswer(call, f"⚠️ 已加入！但您血量不满 ({current_hp}/{max_hp})，请注意！", show_alert=True)
    else:
        await callAnswer(call, "✅ 成功加入队伍！")
    # 有人加入，重置招募超时
    raid_obj = sql_get_raid(raid_id)
    if raid_obj and raid_obj.message_id:
        _start_recruit_timeout(raid_id, call.message.chat.id, raid_obj.message_id)


# ─────────────────────────── 解散队伍 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_disband_(\\d+)$'))
async def on_raid_disband(_, call):
    user_id = call.from_user.id
    raid_id = int(call.data.split('_')[-1])

    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'recruiting':
        return await callAnswer(call, "无法解散", show_alert=True)

    participants = sql_get_participants(raid_id)
    if participants and participants[0].tg != user_id:
        return await callAnswer(call, "只有队长可以解散队伍", show_alert=True)

    sql_update_raid(raid_id, status='failed')
    _cancel_recruit_timeout(raid_id)
    try:
        await call.message.edit("**团本已解散。**")
    except Exception:
        pass


# ─────────────────────────── 开始战斗 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_begin_(\\d+)$'))
async def on_raid_begin(_, call):
    user_id = call.from_user.id
    raid_id = int(call.data.split('_')[-1])
    cfg = get_game_config()

    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'recruiting':
        return await callAnswer(call, "团本不在招募状态", show_alert=True)

    boss = sql_get_boss(raid.boss_id)
    min_players = (getattr(boss, 'min_players', None) or 2)

    participants = sql_get_participants(raid_id)
    if participants[0].tg != user_id:
        return await callAnswer(call, "只有队长可以开始战斗", show_alert=True)

    if len(participants) < min_players:
        return await callAnswer(
            call,
            f"人数不足！至少需要 {min_players} 人（当前 {len(participants)} 人）",
            show_alert=True
        )

    # 血量/护盾按参与人数缩放（每多1人多1倍基础值）
    num_players = len(participants)
    scaled_hp     = boss.hp     * num_players
    scaled_shield = boss.shield * num_players

    # 初始化战斗（取消招募超时）
    _cancel_recruit_timeout(raid_id)
    sql_update_raid(
        raid_id,
        status='active',
        round_num=1,
        cur_player_idx=0,
        boss_hp=scaled_hp,
        boss_max_hp=scaled_hp,
        boss_shield=scaled_shield,
        boss_next_action=get_boss_next_action(scaled_hp, scaled_hp, boss),
        started_at=datetime.now(),
        turn_started_at=datetime.now(),
        last_action_text=None
    )

    # 发送第一回合状态
    await _send_battle_status(call.message, raid_id)

    # 启动超时任务
    _start_timeout_task(raid_id, participants[0].tg, call.message.chat.id)


# ─────────────────────────── 战斗状态展示 ────────────────────────────────────

async def _send_battle_status(msg, raid_id: int, raid=None, boss=None, participants=None):
    """发送/编辑当前回合战斗状态消息（raid/boss/participants 可传入避免重复查询）"""
    if raid is None:
        raid = sql_get_raid(raid_id)
    if not raid:
        return
    if boss is None:
        boss = sql_get_boss(raid.boss_id)
    if participants is None:
        participants = sql_get_participants(raid_id)

    if not participants:
        return

    alive_players = [p for p in participants if p.is_alive]
    if not alive_players:
        return

    # 当前行动玩家
    cur_idx = raid.cur_player_idx % len(alive_players)
    cur_player = alive_players[cur_idx]

    cfg = get_game_config()

    # 并发批量获取所有参与者名字
    all_tg_ids = [p.tg for p in participants]
    name_map = await _tg_names_batch(all_tg_ids)
    cur_name = name_map[cur_player.tg]

    lines = [
        f"**⚔️ 团本战斗 - 第 {raid.round_num} 回合**\n",
        f"🐲 **{boss.name}**  血量：{raid.boss_hp}/{raid.boss_max_hp}"
        + (f"  🛡️{raid.boss_shield}" if raid.boss_shield > 0 else ""),
    ]

    # 近期战报（最多3条）
    recent_logs = _get_raid_logs(raid_id)
    if recent_logs:
        lines.append("")
        lines.append("**─ 近期战报 ─**")
        for detail in recent_logs:
            lines.append(f"· {detail}")

    # BOSS 下回合预告
    lines.append("")
    lines.append(f"🔮 **下回合 BOSS 将：{boss_action_display(raid.boss_next_action)}**")
    lines.append("")

    lines.append("**── 队员状态 ──**")
    for p in participants:
        p_name = name_map[p.tg]
        hp_bar = "█" * min(10, round(p.hp / max(p.max_hp, 1) * 10))
        hp_bar += "░" * (10 - len(hp_bar))
        status = "💀" if not p.is_alive else ("▶️" if p.tg == cur_player.tg else "·")
        shield_text = f" 🛡️{p.shield}" if p.shield > 0 else ""
        done_text = " ✅" if p.turn_done else ""
        lines.append(
            f"  {status} **{p_name}** {p.hp}/{p.max_hp} [{hp_bar}]{shield_text}{done_text}"
        )

    lines.append(f"\n**▶️ {cur_name}，请选择行动：**")
    lines.append(f"⏱️ {cfg['raid_timeout_seconds']} 秒内未操作自动跳过")

    text = "\n".join(lines)

    btns = [
        [("⚔️ 攻击", f"game_raid_act_attack_{raid_id}"),
         ("🛡️ 防御", f"game_raid_act_defend_{raid_id}")],
        [("🎒 使用道具", f"game_raid_act_item_{raid_id}"),
         ("🏃 逃跑", f"game_raid_act_escape_{raid_id}")],
    ]

    try:
        new_msg = await msg.edit(text=text, reply_markup=ikb(btns))
        if new_msg:
            sql_update_raid(raid_id, message_id=new_msg.id, turn_started_at=datetime.now())
    except MessageNotModified:
        pass
    except FloodWait as f:
        # 战斗状态消息被限流时直接跳过，下次行动会重新 edit，不堆积重试
        LOGGER.warning(f"【团本】战斗状态 FloodWait {f.value}s，跳过本次 edit")
    except Exception as ex:
        LOGGER.error(f"【团本】发送战斗状态失败: {ex}")


# ─────────────────────────── 行动处理器 ──────────────────────────────────────

async def _verify_raid_action(call, raid_id: int):
    """
    验证玩家是否有权在当前回合行动
    :return: (raid, cur_player, participants) 或 (None, None, None)
    """
    user_id = call.from_user.id
    if not game_rate_limit_check(user_id):
        await callAnswer(call, "⚠️ 请不要频繁操作，稍后再试！", show_alert=True)
        return None, None, None
    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'active':
        await callAnswer(call, "战斗已结束", show_alert=True)
        return None, None, None

    participants = sql_get_participants(raid_id)
    alive = [p for p in participants if p.is_alive]
    if not alive:
        await callAnswer(call, "所有人已倒下", show_alert=True)
        return None, None, None

    cur_idx = raid.cur_player_idx % len(alive)
    cur_player = alive[cur_idx]

    if cur_player.tg != user_id:
        cur_name = await _tg_name(cur_player.tg)
        await callAnswer(call, f"现在是 {cur_name} 的回合！", show_alert=True)
        return None, None, None

    return raid, cur_player, participants


@bot.on_callback_query(filters.regex('^game_raid_act_attack_(\\d+)$'))
async def on_raid_attack(_, call):
    raid_id = int(call.data.split('_')[-1])
    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    boss = sql_get_boss(raid.boss_id)
    player = sql_get_or_create_player(cur_player.tg)
    atk, _, _ = calc_player_stats(player)

    dice, dmg = roll_attack(atk)

    # 先打护盾再打 HP
    new_boss_hp, new_boss_shield, hp_dmg = apply_damage_to_target(
        raid.boss_hp, raid.boss_shield, dmg
    )

    sql_update_raid(raid_id, boss_hp=new_boss_hp, boss_shield=new_boss_shield)
    sql_update_participant(raid_id, cur_player.tg,
                           damage_dealt=cur_player.damage_dealt + dmg,
                           turn_done=True)

    p_name = await _tg_name(cur_player.tg)

    shield_text = f"（破盾+实伤{hp_dmg}）" if raid.boss_shield > 0 else ""
    # 紧凑一行日志
    action_text = f"⚔️ {p_name} 攻击 {boss.name}，造成 {dmg} 伤害{shield_text}"

    _log_raid(raid_id, action_text)
    sql_update_raid(raid_id, last_action_text=action_text)

    # 玩家操作弹窗反馈
    popup = f"⚔️ 造成 {dmg} 点伤害！Boss 剩余：{new_boss_hp}/{raid.boss_max_hp}"
    await callAnswer(call, popup, show_alert=True)
    _cancel_timeout_task(raid_id)

    # 检查 BOSS 是否死亡
    if new_boss_hp <= 0:
        return await _raid_victory(call.message, raid_id)

    # 推进到下一位玩家或 BOSS 回合
    await _advance_turn(call.message, raid_id, call=call)


@bot.on_callback_query(filters.regex('^game_raid_act_defend_(\\d+)$'))
async def on_raid_defend(_, call):
    raid_id = int(call.data.split('_')[-1])
    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    player = sql_get_or_create_player(cur_player.tg)
    _, def_, _ = calc_player_stats(player)

    dice, shield_val = roll_defend(def_)
    new_shield = cur_player.shield + shield_val

    sql_update_participant(raid_id, cur_player.tg, shield=new_shield, turn_done=True)

    p_name = await _tg_name(cur_player.tg)

    # 紧凑一行日志
    action_text = f"🛡️ {p_name} 防御，获得 {shield_val} 护盾（当前 {new_shield}）"
    _log_raid(raid_id, action_text)
    sql_update_raid(raid_id, last_action_text=action_text)

    # 玩家操作弹窗反馈
    await callAnswer(call, f"🛡️ 获得 {shield_val} 点护盾！", show_alert=True)
    _cancel_timeout_task(raid_id)
    await _advance_turn(call.message, raid_id, call=call)


# ─────────────────────────── 逃跑系统 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_act_escape_(\\d+)$'))
async def on_raid_escape(_, call):
    """逃跑确认页"""
    raid_id = int(call.data.split('_')[-1])
    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    text = (
        f"**🏃 确认逃离战场？**\n\n"
        f"⚠️ 逃跑将视为**战死**，触发死亡惩罚！\n"
        f"逃跑后无法获得任何战利品，其余队员继续战斗。"
    )
    btns = ikb([
        [("✅ 确认逃跑", f"game_raid_escape_confirm_{raid_id}"),
         ("❌ 继续战斗", f"game_raid_escape_cancel_{raid_id}")],
    ])
    try:
        await call.message.edit(text=text, reply_markup=btns)
    except Exception:
        pass
    await callAnswer(call)


@bot.on_callback_query(filters.regex('^game_raid_escape_cancel_(\\d+)$'))
async def on_raid_escape_cancel(_, call):
    """取消逃跑，返回战斗状态"""
    raid_id = int(call.data.split('_')[-1])
    # 只有当前回合玩家才能取消
    user_id = call.from_user.id
    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'active':
        return await callAnswer(call, "战斗已结束", show_alert=True)
    participants = sql_get_participants(raid_id)
    alive = [p for p in participants if p.is_alive]
    if not alive:
        return
    cur_idx = raid.cur_player_idx % len(alive)
    cur_p = alive[cur_idx]
    if cur_p.tg != user_id:
        return await callAnswer(call, "不是你的回合", show_alert=True)
    await callAnswer(call)
    await _send_battle_status(call.message, raid_id)


@bot.on_callback_query(filters.regex('^game_raid_escape_confirm_(\\d+)$'))
async def on_raid_escape_confirm(_, call):
    """执行逃跑"""
    raid_id = int(call.data.split('_')[-1])
    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return
    await callAnswer(call)
    _cancel_timeout_task(raid_id)
    await _process_escape(call.message, raid_id, cur_player.tg, auto=False)


async def _process_escape(msg, raid_id: int, player_tg: int, auto: bool = False):
    """处理玩家逃跑（手动或超时）→ 直接触发死亡"""
    raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'active':
        return

    participants = sql_get_participants(raid_id)
    p = next((p for p in participants if p.tg == player_tg), None)
    if not p or not p.is_alive:
        return

    p_name = await _tg_name(player_tg)

    # 逃跑 = 战死，触发死亡惩罚
    sql_update_participant(raid_id, player_tg, is_alive=False, turn_done=True, hp=0)
    sql_update_game_player(player_tg, hp=0)
    from bot.modules.game.game_engine import trigger_player_death
    trigger_player_death(player_tg)

    escape_type = "超时自动逃跑" if auto else "选择逃跑"
    action_text = f"💀 {p_name} {escape_type}，战死沙场！"
    _log_raid(raid_id, action_text)
    sql_update_raid(raid_id, last_action_text=action_text)

    # 检查剩余存活人数
    participants_fresh = sql_get_participants(raid_id)
    alive_remaining = [pp for pp in participants_fresh if pp.is_alive]
    if not alive_remaining:
        return await _raid_defeat(msg, raid_id)

    await _advance_turn(msg, raid_id)


# ─────────────────────────── 使用道具 ────────────────────────────────────────

@bot.on_callback_query(filters.regex('^game_raid_act_item_(\\d+)$'))
async def on_raid_use_item(_, call):
    """展示可用道具列表"""
    raid_id = int(call.data.split('_')[-1])
    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    user_id = call.from_user.id
    from bot.sql_helper.sql_game import sql_get_inventory
    inv_list = sql_get_inventory(user_id)
    usable = []
    for inv in inv_list:
        if inv.equipped or inv.quantity < 1:
            continue
        item_cfg = sql_get_item_config(inv.item_id)
        if not item_cfg:
            continue
        # 团本中可用：回复药剂、护体灵符
        if item_cfg.item_type == "potion" and (
            item_cfg.heal_min > 0 or item_cfg.shield_min > 0
        ):
            usable.append((inv, item_cfg))

    if not usable:
        return await callAnswer(call, "背包中没有可在战斗中使用的道具！", show_alert=True)

    btns = []
    for inv, item_cfg in usable[:6]:  # 最多展示 6 个
        btns.append([(f"💊 {item_cfg.name} ×{inv.quantity}",
                      f"game_raid_item_{inv.item_id}_{raid_id}")])
    btns.append([("🔙 取消", f"game_raid_cancel_item_{raid_id}")])

    await callAnswer(call)
    try:
        await call.message.edit(
            text=call.message.text + "\n\n**💊 选择道具：**",
            reply_markup=ikb(btns)
        )
    except Exception:
        pass


@bot.on_callback_query(filters.regex('^game_raid_cancel_item_(\\d+)$'))
async def on_raid_cancel_item(_, call):
    raid_id = int(call.data.split('_')[-1])
    await callAnswer(call)
    await _send_battle_status(call.message, raid_id)


@bot.on_callback_query(filters.regex('^game_raid_item_([a-z_]+)_(\\d+)$'))
async def on_raid_select_item(_, call):
    """选择了道具后，选择使用目标"""
    raid_id = int(call.data.split('_')[-1])
    item_id = '_'.join(call.data.split('_')[3:-1])

    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    alive = [p for p in participants if p.is_alive]
    item_cfg = sql_get_item_config(item_id)
    if not item_cfg:
        return await callAnswer(call, "道具不存在", show_alert=True)

    # 选择目标
    btns = []
    for p in alive:
        p_name = await _tg_name(p.tg)
        btns.append([(f"👤 {p_name} (血量 {p.hp}/{p.max_hp})",
                      f"game_raid_use_{item_id}_{p.tg}_{raid_id}")])
    btns.append([("🔙 取消", f"game_raid_cancel_item_{raid_id}")])

    await callAnswer(call)
    await call.message.edit(
        text=f"**对谁使用 {item_cfg.name}？**",
        reply_markup=ikb(btns)
    )


@bot.on_callback_query(filters.regex('^game_raid_use_([a-z_]+)_(\\d+)_(\\d+)$'))
async def on_raid_use_on_target(_, call):
    """确认使用道具到指定目标（使用道具不消耗回合）"""
    parts = call.data.split('_')
    raid_id = int(parts[-1])
    target_tg = int(parts[-2])
    item_id = '_'.join(parts[3:-2])

    raid, cur_player, participants = await _verify_raid_action(call, raid_id)
    if not raid:
        return

    # 消耗道具
    if not sql_use_item(cur_player.tg, item_id):
        return await callAnswer(call, "道具不足！", show_alert=True)

    item_cfg = sql_get_item_config(item_id)
    target_p = next((p for p in participants if p.tg == target_tg), None)
    if not target_p:
        return await callAnswer(call, "目标不存在", show_alert=True)

    actor_name = await _tg_name(cur_player.tg)
    target_name = await _tg_name(target_tg)

    action_text = ""
    popup_text = ""
    value = 0

    if item_cfg.heal_min > 0:
        from bot.modules.game.game_engine import roll_heal
        dice, heal = roll_heal(item_cfg.heal_min, item_cfg.heal_max)
        new_hp = min(target_p.max_hp, target_p.hp + heal)
        sql_update_participant(raid_id, target_tg, hp=new_hp)
        sql_update_participant(raid_id, cur_player.tg,
                               heal_done=cur_player.heal_done + heal)
        # 注意：不设置 turn_done=True，道具不占用回合
        value = heal
        self_target = "自己" if target_tg == cur_player.tg else target_name
        action_text = f"💊 {actor_name} 对 {self_target} 使用 {item_cfg.name}，回血 +{heal}（{new_hp}/{target_p.max_hp}）"
        popup_text = f"💊 {item_cfg.name}：{self_target} 恢复 {heal} 点生命！"
    elif item_cfg.shield_min > 0:
        from bot.modules.game.game_engine import roll_shield
        dice, shield_val = roll_shield(item_cfg.shield_min, item_cfg.shield_max)
        new_shield = target_p.shield + shield_val
        sql_update_participant(raid_id, target_tg, shield=new_shield)
        # 注意：不设置 turn_done=True，道具不占用回合
        value = shield_val
        self_target = "自己" if target_tg == cur_player.tg else target_name
        action_text = f"🛡️ {actor_name} 对 {self_target} 使用 {item_cfg.name}，护盾 +{shield_val}"
        popup_text = f"🛡️ {item_cfg.name}：{self_target} 获得 {shield_val} 点护盾！"
        dice = 0
    else:
        action_text = f"✨ {actor_name} 使用 {item_cfg.name}，效果不明显"
        popup_text = f"使用了 {item_cfg.name}"
        dice = 0

    _log_raid(raid_id, action_text)
    sql_update_raid(raid_id, last_action_text=action_text)

    # 重置超时（玩家还需继续行动）
    _cancel_timeout_task(raid_id)
    _start_timeout_task(raid_id, cur_player.tg, call.message.chat.id)

    # 弹窗反馈（使用道具后还可以继续攻击/防御）
    await callAnswer(call, popup_text + "\n\n可继续选择攻击或防御！", show_alert=True)
    # 刷新战斗状态（不推进回合）
    await _send_battle_status(call.message, raid_id)


# ─────────────────────────── 回合推进 ────────────────────────────────────────

async def _advance_turn(msg, raid_id: int, call=None, raid=None, participants=None):
    """
    推进到下一行动玩家，若本轮所有玩家已行动则执行 BOSS 回合
    """
    if raid is None:
        raid = sql_get_raid(raid_id)
    if not raid or raid.status != 'active':
        return

    if participants is None:
        participants = sql_get_participants(raid_id)
    alive = [p for p in participants if p.is_alive]

    if not alive:
        return await _raid_defeat(msg, raid_id)

    all_done = all(p.turn_done for p in alive)

    if all_done:
        # 执行 BOSS 回合
        await _boss_turn(msg, raid_id, call=call, raid=raid, participants=participants)
    else:
        # 找下一个未行动的存活玩家
        cur_idx = raid.cur_player_idx
        next_idx = (cur_idx + 1) % len(alive)
        for _ in range(len(alive)):
            if not alive[next_idx % len(alive)].turn_done:
                break
            next_idx += 1

        sql_update_raid(raid_id, cur_player_idx=next_idx % len(alive),
                        turn_started_at=datetime.now())
        # 重新查一次 raid 以获取最新状态
        updated_raid = sql_get_raid(raid_id)
        await _send_battle_status(msg, raid_id, raid=updated_raid, participants=participants)

        # 重新启动超时
        next_player = alive[next_idx % len(alive)]
        _start_timeout_task(raid_id, next_player.tg, msg.chat.id)


async def _boss_turn(msg, raid_id: int, call=None, raid=None, participants=None):
    """BOSS 执行行动"""
    if raid is None:
        raid = sql_get_raid(raid_id)
    boss = sql_get_boss(raid.boss_id)
    if participants is None:
        participants = sql_get_participants(raid_id)
    alive = [p for p in participants if p.is_alive]

    # 用内存 dict 跟踪本回合 HP/shield 变化，避免 double_attack 重复查 DB
    p_state = {p.tg: {"hp": p.hp, "shield": p.shield, "is_alive": p.is_alive, "max_hp": p.max_hp}
               for p in participants}

    action = raid.boss_next_action
    action_lines = []

    if action == "attack":
        target = random.choice(alive)
        dice, dmg = roll_boss_attack(boss.atk_min, boss.atk_max)
        st = p_state[target.tg]
        new_hp, new_shield, hp_dmg = apply_damage_to_target(st["hp"], st["shield"], dmg)
        is_alive = new_hp > 0
        p_state[target.tg].update(hp=new_hp, shield=new_shield, is_alive=is_alive)
        sql_update_participant(raid_id, target.tg, hp=new_hp, shield=new_shield, is_alive=is_alive)
        sql_update_game_player(target.tg, hp=new_hp)
        if not is_alive:
            from bot.modules.game.game_engine import trigger_player_death
            trigger_player_death(target.tg)

        t_name = await _tg_name(target.tg)
        shield_hit = f"（破盾+实伤{hp_dmg}）" if st["shield"] > 0 else ""
        line = f"🐲 {boss.name} 猛攻 {t_name}，造成 {dmg} 伤害{shield_hit}（剩余 {new_hp}/{st['max_hp']}）"
        if not is_alive:
            line += f" 💀倒下了！"
        action_lines.append(line)
        _log_raid(raid_id, line)

    elif action == "double_attack":
        targets = random.choices(alive, k=min(2, len(alive)))
        # 并发获取目标名字
        target_names = await _tg_names_batch([t.tg for t in targets])
        hit_parts = []
        for target in targets:
            st = p_state[target.tg]
            if not st["is_alive"]:
                continue
            dice, dmg = roll_boss_attack(boss.atk_min, boss.atk_max)
            dmg = int(dmg * 0.7)
            new_hp, new_shield, hp_dmg = apply_damage_to_target(st["hp"], st["shield"], dmg)
            is_alive = new_hp > 0
            p_state[target.tg].update(hp=new_hp, shield=new_shield, is_alive=is_alive)
            sql_update_participant(raid_id, target.tg, hp=new_hp, shield=new_shield, is_alive=is_alive)
            sql_update_game_player(target.tg, hp=new_hp)
            if not is_alive:
                from bot.modules.game.game_engine import trigger_player_death
                trigger_player_death(target.tg)
            t_name = target_names[target.tg]
            dead_mark = "💀" if not is_alive else ""
            hit_parts.append(f"{t_name} -{dmg}{dead_mark}")
        double_line = f"💢 {boss.name} 连击！" + "，".join(hit_parts)
        action_lines.append(double_line)
        _log_raid(raid_id, double_line)

    elif action == "defend":
        def_min = getattr(boss, 'def_min', 10) or 10
        def_max = getattr(boss, 'def_max', 30) or 30
        shield_add = random.randint(def_min, def_max)
        new_shield = raid.boss_shield + shield_add
        sql_update_raid(raid_id, boss_shield=new_shield)
        defend_line = f"🛡️ {boss.name} 结起护盾，获得 {shield_add} 点护盾（当前 {new_shield}）"
        action_lines.append(defend_line)
        _log_raid(raid_id, defend_line)

    elif action == "heal":
        heal_min = getattr(boss, 'heal_min', 20) or 20
        heal_max = getattr(boss, 'heal_max', 60) or 60
        heal_amount = random.randint(heal_min, heal_max)
        new_hp = min(raid.boss_max_hp, raid.boss_hp + heal_amount)
        sql_update_raid(raid_id, boss_hp=new_hp)
        heal_line = f"💚 {boss.name} 自我恢复，回复 {heal_amount} 血（{new_hp}/{raid.boss_max_hp}）"
        action_lines.append(heal_line)
        _log_raid(raid_id, heal_line)

    # 重置所有玩家的本回合状态（护盾清零）
    for p in participants:
        sql_update_participant(raid_id, p.tg, turn_done=False, shield=0)

    # 检查是否全灭（用内存状态，不再重查 DB）
    alive_now_tgs = [tg for tg, st in p_state.items() if st["is_alive"]]
    if not alive_now_tgs:
        return await _raid_defeat(msg, raid_id)

    # 紧凑 BOSS 行动文本
    boss_result_text = "\n".join(action_lines) if action_lines else f"🐲 {boss.name} 行动了"

    # 更新 raid：进入下一回合，用内存中已知的 boss_hp（defend/heal 已更新 DB，attack 用 raid.boss_hp）
    current_boss_hp = raid.boss_hp  # attack/double_attack 不改 boss_hp，defend/heal 已写 DB
    new_round = raid.round_num + 1
    next_boss_action = get_boss_next_action(current_boss_hp, raid.boss_max_hp, boss)
    sql_update_raid(
        raid_id,
        round_num=new_round,
        cur_player_idx=0,
        boss_next_action=next_boss_action,
        turn_started_at=datetime.now(),
        last_action_text=boss_result_text
    )

    # BOSS 行动弹窗（通过触发本回合结束的玩家 call 弹出）
    if call is not None:
        try:
            await call.answer(f"🐲 【BOSS 行动！】\n{boss_result_text}", show_alert=True)
        except Exception as ex:
            LOGGER.warning(f"【团本】BOSS行动弹窗失败: {ex}")

    # 展示新回合状态（重新查 raid 获取最新 round_num/boss_next_action）
    updated_raid = sql_get_raid(raid_id)
    updated_participants = sql_get_participants(raid_id)
    alive_now = [p for p in updated_participants if p.is_alive]
    await _send_battle_status(msg, raid_id, raid=updated_raid, boss=boss, participants=updated_participants)
    _start_timeout_task(raid_id, alive_now[0].tg, msg.chat.id)


# ─────────────────────────── 胜利/失败结算 ───────────────────────────────────

async def _raid_victory(msg, raid_id: int):
    """团本胜利结算"""
    raid = sql_get_raid(raid_id)
    boss = sql_get_boss(raid.boss_id)
    participants = sql_get_participants(raid_id)

    # 设置 BOSS 冷却
    now = datetime.now()
    next_spawn = now + timedelta(hours=boss.cd_hours)
    sql_update_raid(raid_id, status='cooldown', finished_at=now, next_spawn_at=next_spawn)
    _clear_raid_logs(raid_id)

    # 构建物品名称映射
    from bot.sql_helper.sql_game import sql_get_all_items
    all_items = sql_get_all_items()
    item_name_map = {item.item_id: item.name for item in all_items}

    # ── 境界资格检查（批量查 player）────────────────────────────────────────────
    boss_realm = boss.recommend_realm
    all_tg_ids = [p.tg for p in participants]
    player_map = {p.tg: sql_get_or_create_player(p.tg) for p in participants}
    participant_realms = [(tg, player_map[tg].realm) for tg in all_tg_ids]

    # 并发批量获取所有参与者名字
    name_map = await _tg_names_batch(all_tg_ids)

    all_qualified = all(r >= boss_realm for _, r in participant_realms)
    any_overleveled = any(r > boss_realm for _, r in participant_realms)

    if not all_qualified:
        reward_multiplier = 0.0
        reward_note = f"⚠️ 队伍中有修为未达到推荐境界（{get_realm_name(boss_realm)}）的成员，**本次挑战不获得奖励**！"
    elif any_overleveled:
        reward_multiplier = 0.5
        reward_note = f"📉 队伍中有修为高于推荐境界（{get_realm_name(boss_realm)}）的成员，**本次奖励减半**！"
    else:
        reward_multiplier = 1.0
        reward_note = None

    # DPS 得分计算
    scored = sorted(
        participants,
        key=lambda p: p.damage_dealt + p.heal_done * 0.5,
        reverse=True
    )

    # 掉落分配
    loot_map = assign_loot_by_dps(participants, raid.boss_id, item_name_map,
                                   reward_multiplier=reward_multiplier)

    # 发放物品到背包
    for tg_id, items in loot_map.items():
        for item_id, qty, item_name in items:
            sql_add_item(tg_id, item_id, qty)

    # 记录 BOSS 击杀（所有参与者均获得击杀记录，用于前置任务校验）
    for p in participants:
        sql_record_boss_kill(p.tg, raid.boss_id)

    # 构建结算文本
    lines = [
        f"**🎉 {boss.name} 已被击败！**\n",
        f"战斗历时：{raid.round_num} 回合\n",
        "**─ DPS 排名 ─**",
    ]
    medals = ["🥇", "🥈", "🥉", "4️⃣"]
    for i, p in enumerate(scored):
        name = name_map[p.tg]
        score = p.damage_dealt + p.heal_done * 0.5
        dead_text = " 💀" if not p.is_alive else ""
        lines.append(f"{medals[i] if i < 4 else f'{i+1}.'} **{name}** - 得分 {score:.0f}{dead_text}")

    # 境界提示
    if reward_note:
        lines.append(f"\n{reward_note}")

    lines.append("\n**─ 掉落物品 ─**")
    any_drop = False
    for p in participants:
        items = loot_map.get(p.tg, [])
        if items:
            any_drop = True
            name = name_map[p.tg]
            item_texts = "、".join(item_name for _, _, item_name in items)
            lines.append(f"  **{name}**：{item_texts}")

    if not any_drop:
        lines.append("  （本次无掉落）")

    lines.append(f"\n⏱️ {boss.name} 将在 **{boss.cd_hours} 小时**后重新出现")

    try:
        await msg.edit(text="\n".join(lines), reply_markup=None)
    except Exception as ex:
        LOGGER.error(f"【团本】发送胜利结算失败: {ex}")


async def _raid_defeat(msg, raid_id: int):
    """团本失败"""
    raid = sql_get_raid(raid_id)
    boss = sql_get_boss(raid.boss_id)
    sql_update_raid(raid_id, status='failed', finished_at=datetime.now())
    _clear_raid_logs(raid_id)

    text = (
        f"**💀 全军覆没！**\n\n"
        f"**{boss.name}** 获得了胜利...\n"
        f"本次战斗历时 {raid.round_num} 回合，无掉落\n\n"
        f"休息一番，再来挑战吧！"
    )
    try:
        await msg.edit(text=text, reply_markup=None)
    except Exception:
        pass


# ─────────────────────────── 超时管理 ────────────────────────────────────────

def _start_timeout_task(raid_id: int, player_tg: int, chat_id: int):
    """启动玩家回合超时任务"""
    _cancel_timeout_task(raid_id)
    cfg = get_game_config()
    timeout = cfg["raid_timeout_seconds"]
    auto_escape_threshold = cfg.get("raid_escape_auto_timeout", 3)

    async def _auto_skip():
        await asyncio.sleep(timeout)
        raid = sql_get_raid(raid_id)
        if not raid or raid.status != 'active':
            return
        participants = sql_get_participants(raid_id)
        alive = [p for p in participants if p.is_alive]
        if not alive:
            return
        cur_idx = raid.cur_player_idx % len(alive)
        cur_p = alive[cur_idx]
        if cur_p.tg != player_tg:
            return

        # 累加超时计数
        new_timeout_count = (cur_p.timeout_count or 0) + 1
        sql_update_participant(raid_id, player_tg, timeout_count=new_timeout_count)

        try:
            msg = await bot.get_messages(chat_id, raid.message_id)
            if new_timeout_count >= auto_escape_threshold:
                # 超时 N 次 → 自动逃跑
                await _process_escape(msg, raid_id, player_tg, auto=True)
            else:
                # 正常跳过本回合
                sql_update_participant(raid_id, player_tg, turn_done=True)
                remaining = auto_escape_threshold - new_timeout_count
                skip_name = await _tg_name(player_tg)
                skip_action = f"⏱️ {skip_name} 超时跳过（再超时 {remaining} 次将自动逃跑）"
                sql_update_raid(raid_id, last_action_text=skip_action)
                await _advance_turn(msg, raid_id)
        except Exception as ex:
            LOGGER.warning(f"【团本超时跳过】{ex}")

    task = asyncio.create_task(_auto_skip())
    _timeout_tasks[raid_id] = task


def _cancel_timeout_task(raid_id: int):
    task = _timeout_tasks.pop(raid_id, None)
    if task and not task.done():
        task.cancel()
