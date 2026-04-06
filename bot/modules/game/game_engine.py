"""
修仙游戏战斗引擎
负责：骰子计算、属性计算、体力管理、奖励发放
"""
import random
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

from bot import LOGGER
from bot.modules.game.game_data import get_game_config, get_realm, REALM_MAX_IDX


# ─────────────────────────── 体力管理 ────────────────────────────────────────

def calc_current_stamina(stamina_db: int, stamina_at: Optional[datetime]) -> int:
    """
    动态计算当前实际体力值（含自然恢复）
    :param stamina_db:  数据库存储的体力值（上次消耗时的值）
    :param stamina_at:  上次消耗体力的时间
    :return: 当前实际体力值（已钳位到 [0, max_stamina]）
    """
    cfg = get_game_config()
    max_stamina = cfg.get("base_stamina", cfg.get("max_stamina", 100))
    recover_minutes = cfg["stamina_recover_minutes"]

    if stamina_at is None:
        return min(stamina_db, max_stamina)

    elapsed_seconds = (datetime.now() - stamina_at).total_seconds()
    recovered = int(elapsed_seconds // (recover_minutes * 60))
    return min(stamina_db + recovered, max_stamina)


def stamina_recover_at(stamina_db: int, stamina_at: Optional[datetime]) -> Optional[datetime]:
    """返回体力下次满充时间，已满则返回 None"""
    cfg = get_game_config()
    max_stamina = cfg.get("base_stamina", cfg.get("max_stamina", 100))
    current = calc_current_stamina(stamina_db, stamina_at)
    if current >= max_stamina:
        return None
    need = max_stamina - current
    recover_minutes = cfg["stamina_recover_minutes"]
    base = stamina_at or datetime.now()
    return base + timedelta(minutes=need * recover_minutes)


# ─────────────────────────── 玩家属性计算 ────────────────────────────────────

def calc_player_stats(player) -> Tuple[int, int, int]:
    """
    计算玩家当前实际属性（含装备加成）
    :return: (effective_attack, effective_defense, max_hp_bonus)
    """
    from bot.sql_helper.sql_game import sql_get_inventory, GameInventory
    from bot.sql_helper.sql_game import sql_get_item_config

    equipped_items = [
        item for item in sql_get_inventory(player.tg)
        if item.equipped
    ]

    atk_bonus = 0
    def_bonus = 0
    hp_bonus = 0

    for inv in equipped_items:
        item_cfg = sql_get_item_config(inv.item_id)
        if item_cfg and item_cfg.item_type == "equipment":
            atk_bonus += item_cfg.atk_bonus
            def_bonus += item_cfg.def_bonus
            hp_bonus += item_cfg.hp_bonus

    return (
        player.attack + atk_bonus,
        player.defense + def_bonus,
        hp_bonus
    )


def calc_max_hp(player) -> int:
    """计算当前最大 HP（境界基础 + 装备加成）"""
    _, _, hp_bonus = calc_player_stats(player)
    realm = get_realm(player.realm)
    return realm[3] + hp_bonus  # base_max_hp + equipment hp_bonus


# ─────────────────────────── 骰子系统 ────────────────────────────────────────

def roll_d20() -> int:
    return random.randint(1, 20)


def roll_attack(player_atk: int) -> Tuple[int, int]:
    """
    玩家攻击骰子：攻击伤害 = 攻击力 + 随机点数（骰子影响随机加成范围）
    :return: (dice_1_20, final_damage)
    """
    dice = roll_d20()
    # 随机加成：骰子越高加成越高
    if dice <= 5:
        bonus = random.randint(1, max(1, player_atk // 4))
    elif dice <= 14:
        bonus = random.randint(max(1, player_atk // 4), max(2, player_atk // 2))
    elif dice <= 19:
        bonus = random.randint(max(1, player_atk // 2), player_atk)
    else:  # 20 = 暴击
        bonus = random.randint(player_atk, player_atk * 2)
    dmg = max(1, player_atk + bonus)
    return dice, dmg


def roll_defend(player_def: int) -> Tuple[int, int]:
    """
    玩家防御骰子：护盾值 = 防御力（骰子影响小幅浮动）
    :return: (dice_1_20, shield_value)
    """
    dice = roll_d20()
    # 护盾 = 防御力，骰子影响 ±20% 浮动
    mult = 0.8 + (dice / 20) * 0.4  # 0.8 ~ 1.2
    shield = max(1, int(player_def * mult))
    return dice, shield


def roll_boss_attack(atk_min: int, atk_max: int) -> Tuple[int, int]:
    """
    BOSS 攻击骰子
    :return: (dice_1_20, final_damage)
    """
    dice = roll_d20()
    base = random.randint(atk_min, atk_max)
    # BOSS 骰子影响最终伤害
    mult = 0.6 + (dice / 20) * 0.8
    dmg = max(1, int(base * mult))
    return dice, dmg


def roll_heal(heal_min: int, heal_max: int) -> Tuple[int, int]:
    """
    治疗骰子
    :return: (dice_1_20, heal_amount)
    """
    dice = roll_d20()
    base = random.randint(heal_min, heal_max)
    mult = 0.7 + (dice / 20) * 0.6
    heal = max(1, int(base * mult))
    return dice, heal


def roll_shield(shield_min: int, shield_max: int) -> Tuple[int, int]:
    """
    道具护盾骰子
    :return: (dice_1_20, shield_value)
    """
    dice = roll_d20()
    base = random.randint(shield_min, shield_max)
    mult = 0.7 + (dice / 20) * 0.6
    shield = max(1, int(base * mult))
    return dice, shield


def apply_damage_to_target(hp: int, shield: int, damage: int) -> Tuple[int, int, int]:
    """
    伤害结算（先扣护盾再扣 HP）
    :return: (new_hp, new_shield, actual_hp_damage)
    """
    if shield >= damage:
        return hp, shield - damage, 0
    remaining = damage - shield
    new_hp = max(0, hp - remaining)
    return new_hp, 0, remaining


# ─────────────────────────── 修行经验计算 ────────────────────────────────────

def calc_cultivation_exp(realm_idx: int, exp_mult: float = 1.0) -> int:
    """计算一次修行获得的经验值"""
    realm = get_realm(realm_idx)
    max_exp = realm[4] if len(realm) > 4 else realm[2]  # 兼容
    max_exp = realm[2]  # 境界升级所需经验
    # 基础经验 = 10%~30% 的升级经验需求
    if max_exp == 0:
        return 0  # 顶级境界
    base = random.randint(
        max(1, int(max_exp * 0.08)),
        max(2, int(max_exp * 0.25))
    )
    return max(1, int(base * exp_mult))


# ─────────────────────────── 升级逻辑 ────────────────────────────────────────

def apply_realm_stats(player) -> Tuple[int, int, int]:
    """
    根据境界重新计算基础属性（升界时调用）
    :return: (new_max_hp, new_attack, new_defense)
    """
    realm = get_realm(player.realm)
    _, _, base_max_hp, base_atk, base_def = realm[0], realm[1], realm[3], realm[4], realm[5]
    return base_max_hp, base_atk, base_def


# ─────────────────────────── BOSS 行动 AI ─────────────────────────────────────

# BOSS 行动权重（默认值，可被 DB 中的 boss 配置覆盖）
_BOSS_ACTION_WEIGHTS_DEFAULT = {
    "attack":        55,
    "double_attack": 15,
    "defend":        15,
    "heal":          15,
}


def get_boss_next_action(boss_hp: int, boss_max_hp: int, boss=None) -> str:
    """
    根据 BOSS 剩余血量智能决定下回合动作。
    优先使用 boss 对象中配置的行动权重；血量低时动态调整。
    """
    if boss is not None:
        weights = {
            "attack":        getattr(boss, 'action_w_attack', 55) or 55,
            "double_attack": getattr(boss, 'action_w_double', 15) or 15,
            "defend":        getattr(boss, 'action_w_defend', 15) or 15,
            "heal":          getattr(boss, 'action_w_heal',   15) or 15,
        }
    else:
        weights = _BOSS_ACTION_WEIGHTS_DEFAULT.copy()

    hp_ratio = boss_hp / max(boss_max_hp, 1)

    if hp_ratio < 0.3:
        # 血量低于 30%：更倾向 heal 和 double_attack
        total = sum(weights.values()) or 100
        weights["heal"]          = int(weights["heal"]          * 2.0)
        weights["double_attack"] = int(weights["double_attack"] * 1.7)
        weights["attack"]        = max(10, total - weights["heal"] - weights["double_attack"] - weights["defend"])
    elif hp_ratio < 0.6:
        weights["heal"]          = int(weights["heal"]          * 1.4)
        weights["double_attack"] = int(weights["double_attack"] * 1.3)

    total = sum(weights.values())
    r = random.uniform(0, total)
    cumulative = 0
    for action, w in weights.items():
        cumulative += w
        if r <= cumulative:
            return action
    return "attack"


_BOSS_ACTION_NAMES = {
    "attack":        "⚔️ 攻击",
    "double_attack": "💢 连斩",
    "defend":        "🛡️ 防御",
    "heal":          "💚 恢复",
}


def boss_action_display(action: str) -> str:
    return _BOSS_ACTION_NAMES.get(action, "⚔️ 攻击")


# ─────────────────────────── 奖励发放 ────────────────────────────────────────

def grant_stone_reward(tg: int, amount: int, reason: str = "游戏奖励") -> bool:
    """
    给玩家发放石子（积分）奖励
    """
    from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
    from bot.sql_helper.sql_audit import log_audit
    try:
        e = sql_get_emby(tg=tg)
        if not e:
            return False
        new_iv = e.iv + amount
        ok = sql_update_emby(Emby.tg == tg, iv=new_iv)
        if ok:
            log_audit(
                category="credits",
                action="game_reward",
                source="bot",
                target_tg=tg,
                target_name=e.name,
                before_val=str(e.iv),
                after_val=str(new_iv),
                detail=f"{reason}：+{amount} 石子，当前={new_iv}"
            )
        return ok
    except Exception as ex:
        LOGGER.error(f"【游戏】发放石子奖励失败 tg={tg}: {ex}")
        return False


def grant_emby_days_reward(tg: int, days: int, reason: str = "游戏奖励") -> bool:
    """
    给玩家发放 Emby 到期天数奖励
    """
    from datetime import datetime, timedelta
    from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
    from bot.sql_helper.sql_audit import log_audit
    try:
        e = sql_get_emby(tg=tg)
        if not e:
            return False
        old_ex = e.ex
        now = datetime.now()
        base = max(old_ex, now) if old_ex else now
        new_ex = base + timedelta(days=days)
        ok = sql_update_emby(Emby.tg == tg, ex=new_ex)
        if ok:
            old_str = old_ex.strftime('%Y-%m-%d') if old_ex else '无'
            new_str = new_ex.strftime('%Y-%m-%d')
            log_audit(
                category="credits",
                action="game_reward",
                source="bot",
                target_tg=tg,
                target_name=e.name,
                before_val=old_str,
                after_val=new_str,
                detail=f"{reason}：+{days} 天 Emby 到期，操作前={old_str}，操作后={new_str}"
            )
        return ok
    except Exception as ex:
        LOGGER.error(f"【游戏】发放天数奖励失败 tg={tg}: {ex}")
        return False


# ─────────────────────────── 团本掉落结算 ────────────────────────────────────

def roll_raid_loot(boss_id: str, rate_multiplier: float = 1.0) -> Optional[Tuple[str, int]]:
    """
    从 BOSS 掉落权重池中随机抽取一件物品（每人独立调用一次）。
    drop_rate 为权重值，所有条目合计≤1.0；合计<1.0 时剩余概率为"无掉落"。
    rate_multiplier=0.5 时整体掉落概率减半（奖励减半机制）。
    :return: (item_id, 1) 或 None
    """
    from bot.sql_helper.sql_game import sql_get_loot_table
    if rate_multiplier <= 0:
        return None
    loot_table = sql_get_loot_table(boss_id)
    if not loot_table:
        return None

    total_weight = sum(e.drop_rate for e in loot_table)
    if total_weight <= 0:
        return None

    # rate_multiplier < 1.0 时，以 (1 - rate_multiplier) 的概率直接返回无掉落
    if rate_multiplier < 1.0 and random.random() > rate_multiplier:
        return None

    # 从权重池抽取（total_weight 可 < 1.0，不足部分为无掉落槽）
    r = random.uniform(0, max(total_weight, 1.0))
    cumulative = 0.0
    for entry in loot_table:
        cumulative += entry.drop_rate
        if r <= cumulative:
            return entry.item_id, 1
    return None  # 落入"无掉落"区间


def assign_loot_by_dps(
    participants: List[Any],
    boss_id: str,
    item_name_map: Dict[str, str],
    reward_multiplier: float = 1.0,
) -> Dict[int, List[Tuple[str, int, str]]]:
    """
    每位存活玩家独立从掉落池抽取1件物品。
    传说品质道具（rarity='legendary'）全场至多1人获得。
    :return: {tg: [(item_id, qty, item_name), ...]}
    """
    from bot.sql_helper.sql_game import sql_get_item_config

    result: Dict[int, List[Tuple[str, int, str]]] = {p.tg: [] for p in participants}

    if reward_multiplier <= 0:
        return result

    alive = [p for p in participants if p.is_alive] or list(participants)
    legendary_won = False

    for p in alive:
        drop = roll_raid_loot(boss_id, rate_multiplier=reward_multiplier)
        if drop is None:
            continue
        item_id, qty = drop
        # 传说品质限定：全场只有第一位获得者可以拿走
        item_cfg = sql_get_item_config(item_id)
        if item_cfg and item_cfg.rarity == 'legendary':
            if legendary_won:
                continue  # 跳过，不给本玩家
            legendary_won = True
        name = item_name_map.get(item_id, item_id)
        result[p.tg].append((item_id, qty, name))

    return result


# ─────────────────────────── 死亡与复活 ──────────────────────────────────────

def trigger_player_death(tg: int) -> dict:
    """
    触发玩家死亡：
    1. 扣除 death_exp_loss_pct% 修为
    2. 概率掉落背包道具（按稀有度权重，装备优先）
    3. 设置 is_dead=True, dead_at=datetime.now()
    返回 dict: {exp_lost, dropped_item_name or None}
    """
    from bot.sql_helper.sql_game import (
        sql_get_or_create_player, sql_update_game_player,
        sql_get_inventory, sql_get_item_config,
        sql_use_item, sql_unequip_item
    )
    cfg = get_game_config()
    player = sql_get_or_create_player(tg)

    # 扣除修为
    exp_loss_pct = cfg.get("death_exp_loss_pct", 10)
    exp_lost = max(0, int(player.exp * exp_loss_pct / 100))
    new_exp = max(0, player.exp - exp_lost)

    # 掉落判定
    dropped_name = None
    drop_chance = cfg.get("death_drop_chance", 50)
    if random.randint(1, 100) <= drop_chance:
        inv_list = sql_get_inventory(tg)
        equip_mult = cfg.get("death_equip_weight_mult", 2)
        rarity_weights = {
            "common":    cfg.get("death_rarity_w_common", 50),
            "uncommon":  cfg.get("death_rarity_w_uncommon", 25),
            "rare":      cfg.get("death_rarity_w_rare", 15),
            "epic":      cfg.get("death_rarity_w_epic", 8),
            "legendary": cfg.get("death_rarity_w_legendary", 2),
        }
        candidates = []
        for inv in inv_list:
            item_cfg = sql_get_item_config(inv.item_id)
            if not item_cfg:
                continue
            base_w = rarity_weights.get(item_cfg.rarity, 10)
            is_equip = (item_cfg.item_type == "equipment")
            weight = base_w * equip_mult if is_equip else base_w
            candidates.append((inv, item_cfg, weight))

        if candidates:
            total_w = sum(c[2] for c in candidates)
            r = random.uniform(0, total_w)
            cum = 0
            chosen_inv, chosen_cfg, _ = candidates[-1]
            for inv, item_cfg, w in candidates:
                cum += w
                if r <= cum:
                    chosen_inv, chosen_cfg = inv, item_cfg
                    break
            # 移除该物品（1个）
            if chosen_inv.equipped:
                sql_unequip_item(tg, chosen_inv.item_id)
            else:
                sql_use_item(tg, chosen_inv.item_id, 1)
            dropped_name = chosen_cfg.name

    sql_update_game_player(tg,
        exp=new_exp, hp=0, is_dead=True,
        dead_at=datetime.now(), break_pill_bonus=0,
        death_exp_lost=exp_lost,
        death_dropped_item=dropped_name,
    )
    LOGGER.info(f"【游戏-死亡】tg={tg} 修为损失={exp_lost} 掉落={dropped_name}")
    return {"exp_lost": exp_lost, "dropped_name": dropped_name}


def revive_player(tg: int):
    """复活玩家：满血复活，清除死亡标记及死亡惩罚记录"""
    from bot.sql_helper.sql_game import sql_get_or_create_player, sql_update_game_player
    player = sql_get_or_create_player(tg)
    sql_update_game_player(tg, hp=player.max_hp, is_dead=False, dead_at=None,
                           death_exp_lost=0, death_dropped_item=None)
    LOGGER.info(f"【游戏-复活】tg={tg} 满血复活，血量={player.max_hp}/{player.max_hp}")
