"""
背包系统
- 展示玩家背包物品（装备/道具两个分类 Tab）
- 装备/卸下装备 → 结果页（避免双重 editMessage）
- 在背包中直接使用道具（usable_in_bag=True 的回血/加成物品）

【回调格式】
  game_inv_{uid}              → 默认显示装备 Tab
  game_inv_equip_{uid}        → 装备 Tab
  game_inv_item_{uid}         → 道具 Tab
  game_equip_{item_id}_{uid}  → 装备某件装备
  game_unequip_{item_id}_{uid}→ 卸下某件装备
  game_inv_use_{item_id}_{uid}→ 在背包中使用道具
"""
import random

from pyrogram import filters
from pyromod.helpers import ikb

from bot import bot, LOGGER, sakura_b
from bot.func_helper.msg_utils import callAnswer, editMessage
from bot.modules.game.game_data import get_rarity_display
from bot.modules.game.cultivation import _check_game_access, _check_menu_owner
from bot.sql_helper.sql_game import (
    sql_get_inventory, sql_get_item_config,
    sql_equip_item, sql_unequip_item,
    sql_get_or_create_player, sql_update_game_player,
    sql_get_inventory_item, sql_use_item,
)

# 装备槽位中文
_SLOT_NAMES = {
    "weapon":    "武器",
    "armor":     "护甲",
    "accessory": "饰品",
}


def _fmt_item_detail(item_cfg) -> str:
    lines = []
    if item_cfg.heal_min > 0 or item_cfg.heal_max > 0:
        lines.append(f"回复生命 {item_cfg.heal_min}~{item_cfg.heal_max}")
    if item_cfg.shield_min > 0 or item_cfg.shield_max > 0:
        lines.append(f"提供护盾 {item_cfg.shield_min}~{item_cfg.shield_max}")
    if item_cfg.atk_bonus > 0:
        lines.append(f"攻击 +{item_cfg.atk_bonus}")
    if item_cfg.def_bonus > 0:
        lines.append(f"防御 +{item_cfg.def_bonus}")
    if item_cfg.hp_bonus > 0:
        lines.append(f"最大血量 +{item_cfg.hp_bonus}")
    return "、".join(lines) if lines else "无附加属性"


# ─────────────────────────── 装备 Tab ────────────────────────────────────────

async def _show_equip_tab(call, uid: int):
    """装备 Tab：已装备 + 背包中的装备类物品"""
    inv_list = sql_get_inventory(uid)
    equipped = [i for i in inv_list if i.equipped]
    unequipped_equip = []
    for i in inv_list:
        if i.equipped:
            continue
        cfg = sql_get_item_config(i.item_id)
        if cfg and cfg.item_type == "equipment":
            unequipped_equip.append((i, cfg))

    lines = ["**⚔️ 背包 — 装备**\n"]
    btns = []

    # 已装备区域
    if equipped:
        lines.append("**── 已装备 ──**")
        for inv in equipped:
            cfg = sql_get_item_config(inv.item_id)
            if not cfg:
                continue
            slot = _SLOT_NAMES.get(cfg.slot or "", "?")
            lines.append(f"  [{slot}] **{cfg.name}** {get_rarity_display(cfg.rarity)}")
            detail = _fmt_item_detail(cfg)
            lines.append(f"    {detail}")
            btns.append([(f"❌ 卸下 {cfg.name}", f"game_unequip_{inv.item_id}_{uid}")])
        lines.append("")

    # 背包中的装备
    if unequipped_equip:
        lines.append("**── 背包中的装备 ──**")
        for inv, cfg in unequipped_equip:
            slot = _SLOT_NAMES.get(cfg.slot or "", "?")
            lines.append(f"  [{slot}] **{cfg.name}** ×{inv.quantity} {get_rarity_display(cfg.rarity)}")
            lines.append(f"    {_fmt_item_detail(cfg)}")
            btns.append([(f"✅ 装备 {cfg.name}", f"game_equip_{inv.item_id}_{uid}")])
        lines.append("")

    if not equipped and not unequipped_equip:
        lines.append("背包中没有任何装备。")

    text = "\n".join(lines)

    # Tab 切换 + 返回
    btns.append([
        ("⚔️ 装备 ●", f"game_inv_equip_{uid}"),
        ("🎒 道具", f"game_inv_item_{uid}"),
    ])
    btns.append([("🏠 返回主菜单", f"game_menu_{uid}")])
    await editMessage(call, text, buttons=ikb(btns))


# ─────────────────────────── 道具 Tab ────────────────────────────────────────

async def _show_item_tab(call, uid: int):
    """道具 Tab：消耗品/丹药/体力道具等，可使用的道具展示"使用"按钮"""
    inv_list = sql_get_inventory(uid)
    item_entries = []
    for i in inv_list:
        if i.equipped:
            continue
        cfg = sql_get_item_config(i.item_id)
        if cfg and cfg.item_type != "equipment":
            item_entries.append((i, cfg))

    lines = ["**🎒 背包 — 道具**\n"]
    btns = []

    if item_entries:
        for inv, cfg in item_entries:
            lines.append(f"  • **{cfg.name}** ×{inv.quantity} {get_rarity_display(cfg.rarity)}")
            lines.append(f"    {_fmt_item_detail(cfg)}")
            if cfg.usable_in_bag:
                btns.append([(f"💊 使用 {cfg.name}", f"game_inv_use_{inv.item_id}_{uid}")])
        lines.append("")
    else:
        lines.append("背包中没有任何道具。")

    text = "\n".join(lines)

    btns.append([
        ("⚔️ 装备", f"game_inv_equip_{uid}"),
        ("🎒 道具 ●", f"game_inv_item_{uid}"),
    ])
    btns.append([("🏠 返回主菜单", f"game_menu_{uid}")])
    await editMessage(call, text, buttons=ikb(btns))


# ─────────────────────────── 回调 ──────────────────────────────────────────

@bot.on_callback_query(filters.regex(r'^game_inv_(\d+)$'))
async def on_game_inventory(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _show_equip_tab(call, uid)


@bot.on_callback_query(filters.regex(r'^game_inv_equip_(\d+)$'))
async def on_inv_equip_tab(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _show_equip_tab(call, uid)


@bot.on_callback_query(filters.regex(r'^game_inv_item_(\d+)$'))
async def on_inv_item_tab(_, call):
    uid = int(call.data.rsplit('_', 1)[1])
    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)
    await _show_item_tab(call, uid)


@bot.on_callback_query(filters.regex(r'^game_equip_(.+)_(\d+)$'))
async def on_equip_item(_, call):
    main, uid_str = call.data.rsplit('_', 1)
    uid = int(uid_str)
    item_id = main[len("game_equip_"):]

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    item_cfg = sql_get_item_config(item_id)
    if not item_cfg:
        return await callAnswer(call, "道具不存在", show_alert=True)

    # 卸下同槽位已有装备
    inv_list = sql_get_inventory(uid)
    for inv in inv_list:
        if inv.equipped:
            other_cfg = sql_get_item_config(inv.item_id)
            if other_cfg and other_cfg.slot == item_cfg.slot:
                sql_unequip_item(uid, inv.item_id)
                break

    if sql_equip_item(uid, item_id):
        _refresh_player_stats(uid)
        result_text = f"✅ 已装备 **{item_cfg.name}**！\n\n{_fmt_item_detail(item_cfg)}"
    else:
        result_text = "❌ 装备失败，请检查背包"

    btns = ikb([[
        ("⚔️ 返回装备", f"game_inv_equip_{uid}"),
        ("🏠 返回主菜单", f"game_menu_{uid}"),
    ]])
    await callAnswer(call, "")
    await editMessage(call, f"**⚔️ 装备结果**\n\n{result_text}", buttons=btns)


@bot.on_callback_query(filters.regex(r'^game_unequip_(.+)_(\d+)$'))
async def on_unequip_item(_, call):
    main, uid_str = call.data.rsplit('_', 1)
    uid = int(uid_str)
    item_id = main[len("game_unequip_"):]

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    item_cfg = sql_get_item_config(item_id)
    if not item_cfg:
        return await callAnswer(call, "道具不存在", show_alert=True)

    if sql_unequip_item(uid, item_id):
        _refresh_player_stats(uid)
        result_text = f"✅ 已卸下 **{item_cfg.name}**"
    else:
        result_text = "❌ 卸下失败"

    btns = ikb([[
        ("⚔️ 返回装备", f"game_inv_equip_{uid}"),
        ("🏠 返回主菜单", f"game_menu_{uid}"),
    ]])
    await callAnswer(call, "")
    await editMessage(call, f"**⚔️ 卸下结果**\n\n{result_text}", buttons=btns)


@bot.on_callback_query(filters.regex(r'^game_inv_use_(.+)_(\d+)$'))
async def on_inv_use_item(_, call):
    """在背包中使用道具（仅 usable_in_bag=True 的物品）"""
    main, uid_str = call.data.rsplit('_', 1)
    uid = int(uid_str)
    item_id = main[len("game_inv_use_"):]

    if not await _check_menu_owner(call, uid):
        return
    e, err = _check_game_access(uid)
    if err:
        return await callAnswer(call, err, show_alert=True)

    item_cfg = sql_get_item_config(item_id)
    if not item_cfg or not item_cfg.usable_in_bag:
        return await callAnswer(call, "该道具无法在背包中使用", show_alert=True)

    if not sql_use_item(uid, item_id):
        return await callAnswer(call, f"背包中没有 {item_cfg.name} 了！", show_alert=True)

    player = sql_get_or_create_player(uid)
    result_lines = [f"💊 使用了 **{item_cfg.name}**\n"]

    # 回血效果
    if item_cfg.heal_min > 0 or item_cfg.heal_max > 0:
        heal = random.randint(item_cfg.heal_min, item_cfg.heal_max)
        new_hp = min(player.max_hp, player.hp + heal)
        sql_update_game_player(uid, hp=new_hp)
        result_lines.append(f"❤️ 恢复生命 **+{heal}**（{new_hp}/{player.max_hp}）")

    result_text = "\n".join(result_lines)

    btns = ikb([[
        ("🎒 返回道具", f"game_inv_item_{uid}"),
        ("🏠 返回主菜单", f"game_menu_{uid}"),
    ]])
    await callAnswer(call, "")
    await editMessage(call, result_text, buttons=btns)


def _refresh_player_stats(user_id: int):
    """重新计算并保存玩家装备加成后的属性"""
    from bot.modules.game.game_engine import calc_max_hp
    player = sql_get_or_create_player(user_id)
    new_max_hp = calc_max_hp(player)
    new_hp = min(player.hp, new_max_hp)
    sql_update_game_player(user_id, max_hp=new_max_hp, hp=new_hp)
