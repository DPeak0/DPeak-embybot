"""
修仙游戏静态数据定义 + 数据库初始化种子
包含：境界表、初始BOSS配置、物品配置、掉落表
"""
from bot import LOGGER

# ─────────────────────────── 游戏默认配置 ────────────────────────────────────

DEFAULT_GAME_CONFIG = {
    "enabled": True,              # 游戏总开关
    "max_stamina": 100,           # 最大体力
    "stamina_recover_minutes": 10,  # 每X分钟恢复1点体力
    "base_break_rate": 40,        # 基础突破成功率（%）
    "max_break_rate": 90,         # 最高突破成功率（%）
    "break_fail_bonus_pct": 5,    # 每次突破失败后，下次成功率额外增加的百分比
    "break_fail_cd_enabled": True,      # 突破失败冷却开关
    "break_fail_cooldown_hours": 24,   # 突破失败冷却时间（小时）
    "break_success_cd_enabled": True,   # 突破成功冷却开关
    "break_success_cooldown_hours": 168,  # 突破成功冷却时间（小时，默认7天=168小时）
    "break_reward_stone_rate": 80,  # 突破奖励石子概率（%），其余奖励Emby天数
    "break_reward_stone_min": 10,   # 突破奖励石子最小值（乘以境界系数）
    "break_reward_stone_max": 50,   # 突破奖励石子最大值（乘以境界系数）
    "break_reward_emby_days_min": 1,  # 突破奖励Emby天数最小值
    "break_reward_emby_days_max": 3,  # 突破奖励Emby天数最大值
    "raid_timeout_seconds": 120,  # 玩家回合超时时间（秒）
    "raid_escape_hp_pct": 30,     # 逃跑时受到 max_hp 该百分比的伤害
    "raid_escape_stone_min": 10,  # 逃跑石子惩罚最小值
    "raid_escape_stone_max": 50,  # 逃跑石子惩罚最大值
    "raid_escape_auto_timeout": 3, # 超时 N 次后自动触发逃跑
    "rank_limit": 20,             # 排行榜展示人数
    # 死亡系统
    "death_exp_loss_pct": 10,          # 死亡时修为损失百分比
    "death_drop_chance": 50,           # 死亡道具掉落概率(%)
    "death_equip_weight_mult": 2,      # 装备类相比道具的额外掉落倍率（整数）
    "death_rarity_w_common": 50,       # 死亡掉落-普通权重
    "death_rarity_w_uncommon": 25,     # 死亡掉落-优良权重
    "death_rarity_w_rare": 15,         # 死亡掉落-稀有权重
    "death_rarity_w_epic": 8,          # 死亡掉落-史诗权重
    "death_rarity_w_legendary": 2,     # 死亡掉落-传说权重
    "cultiv_rarity_w_common": 55,      # 修行掉落-普通品质权重
    "cultiv_rarity_w_uncommon": 28,    # 修行掉落-优良品质权重
    "cultiv_rarity_w_rare": 12,        # 修行掉落-稀有品质权重
    "cultiv_rarity_w_epic": 4,         # 修行掉落-史诗品质权重
    "cultiv_rarity_w_legendary": 1,    # 修行掉落-传说品质权重
    "revive_stone_cost": 50,           # 石子复活费用
    "revive_exp_pct": 50,              # 修为复活扣除当前境界上限的百分比
    "death_auto_revive_hours": 12,     # 自动复活时间（小时）
    "game_open_to_all": False,         # True=任何TG用户可玩，False=仅已注册Emby用户可玩
    "callback_rate_limit": 3,          # 每秒最多允许的游戏回调次数，超出则拦截
    # 修行事件权重与数值范围（各字段含义见 CULTIVATION_EVENTS）
    # weight=相对权重，exp_min/max=每次修行获得经验绝对值范围，hp_change_min/max=HP绝对变化量（正=回复，负=损失）
    # item_drop_rate=物品掉落触发概率(0~100%)，item_drop_max=单次最多掉落件数
    "cultivation_events": {
        "normal":           {"weight": 35, "exp_min":  50, "exp_max": 200, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate":  0, "item_drop_max": 1},
        "lucky":            {"weight": 12, "exp_min": 150, "exp_max": 500, "hp_change_min":   0, "hp_change_max":  20, "item_drop_rate": 60, "item_drop_max": 2},
        "evil_cultivator":  {"weight": 12, "exp_min":  50, "exp_max": 200, "hp_change_min": -60, "hp_change_max": -10, "item_drop_rate":  0, "item_drop_max": 1},
        "spirit_spring":    {"weight":  8, "exp_min": 200, "exp_max": 600, "hp_change_min":  30, "hp_change_max":  80, "item_drop_rate":  0, "item_drop_max": 1},
        "fierce_beast":     {"weight":  8, "exp_min": 100, "exp_max": 350, "hp_change_min": -40, "hp_change_max":  -5, "item_drop_rate": 70, "item_drop_max": 2},
        "enlightenment":    {"weight":  4, "exp_min": 400, "exp_max":1200, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate": 25, "item_drop_max": 1},
        "demon_invasion":   {"weight":  4, "exp_min":  30, "exp_max": 120, "hp_change_min": -80, "hp_change_max": -30, "item_drop_rate":  0, "item_drop_max": 1},
        "ancient_text":     {"weight":  4, "exp_min": 200, "exp_max": 700, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate": 40, "item_drop_max": 1},
        "heavenly_thunder": {"weight":  3, "exp_min": 150, "exp_max": 500, "hp_change_min": -60, "hp_change_max": -10, "item_drop_rate": 60, "item_drop_max": 1},
        "spirit_rain":      {"weight":  4, "exp_min": 100, "exp_max": 300, "hp_change_min":  20, "hp_change_max":  60, "item_drop_rate":  0, "item_drop_max": 1},
        "lost_in_wild":     {"weight":  3, "exp_min":   5, "exp_max":  30, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate":  0, "item_drop_max": 1},
        "spirit_beast":     {"weight":  3, "exp_min": 120, "exp_max": 400, "hp_change_min":   0, "hp_change_max":  20, "item_drop_rate": 20, "item_drop_max": 1},
        "fellow_daoist":    {"weight":  3, "exp_min": 100, "exp_max": 300, "hp_change_min":  10, "hp_change_max":  30, "item_drop_rate": 15, "item_drop_max": 1},
        "evil_qi":          {"weight":  2, "exp_min": 150, "exp_max": 500, "hp_change_min":-100, "hp_change_max": -40, "item_drop_rate": 80, "item_drop_max": 1},
        "treasure_find":    {"weight":  3, "exp_min":  50, "exp_max": 200, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate": 90, "item_drop_max": 3},
        "meridian_damage":  {"weight":  3, "exp_min":-200, "exp_max": -50, "hp_change_min": -30, "hp_change_max":  -5, "item_drop_rate": 50, "item_drop_max": 1},
        "spirit_stone":     {"weight":  4, "exp_min": 120, "exp_max": 400, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate": 30, "item_drop_max": 1},
        "pill_furnace":     {"weight":  3, "exp_min": 150, "exp_max": 450, "hp_change_min":   0, "hp_change_max":  10, "item_drop_rate": 50, "item_drop_max": 1},
        "illusion_trap":    {"weight":  2, "exp_min":-300, "exp_max":-100, "hp_change_min": -20, "hp_change_max":   0, "item_drop_rate":  0, "item_drop_max": 1},
        "dao_heart_test":   {"weight":  3, "exp_min": 200, "exp_max": 600, "hp_change_min": -30, "hp_change_max":  -5, "item_drop_rate": 25, "item_drop_max": 1},
        "spirit_vortex":    {"weight":  2, "exp_min": 500, "exp_max":1500, "hp_change_min":   0, "hp_change_max":   0, "item_drop_rate":  0, "item_drop_max": 1},
        "curse_mark":       {"weight":  2, "exp_min":-500, "exp_max":-150, "hp_change_min": -50, "hp_change_max": -10, "item_drop_rate": 70, "item_drop_max": 1},
        "elder_guidance":   {"weight":  3, "exp_min": 250, "exp_max": 800, "hp_change_min":   0, "hp_change_max":  15, "item_drop_rate": 30, "item_drop_max": 1},
    },
}


# ─────────────────────────── 境界表 ──────────────────────────────────────────
# 格式：(realm_id, display_name, max_exp, base_max_hp, base_attack, base_defense)
# 每大境界10层子境界；max_exp=0 表示已到顶

REALMS = [
    # ── 肉体凡胎（0）── 初始境界，无需丹药即可突破至练气
    (0,  "肉体凡胎",     50,        50,      5,     3),
    # ── 练气期（1-10）──
    (1,  "练气一层",     100,       80,      8,     5),
    (2,  "练气二层",     150,       88,      9,     6),
    (3,  "练气三层",     230,       97,      10,    7),
    (4,  "练气四层",     340,       106,     10,    7),
    (5,  "练气五层",     510,       117,     11,    8),
    (6,  "练气六层",     770,       128,     12,    9),
    (7,  "练气七层",     1150,      141,     13,    10),
    (8,  "练气八层",     1730,      155,     14,    11),
    (9,  "练气九层",     2590,      170,     15,    12),
    (10, "练气十层",     3900,      188,     17,    14),
    # ── 筑基期（11-20）──
    (11, "筑基一层",     5500,      240,     22,    19),
    (12, "筑基二层",     6300,      265,     24,    21),
    (13, "筑基三层",     7200,      292,     27,    23),
    (14, "筑基四层",     8200,      321,     30,    26),
    (15, "筑基五层",     9300,      354,     33,    29),
    (16, "筑基六层",     10600,     390,     36,    32),
    (17, "筑基七层",     12100,     429,     40,    35),
    (18, "筑基八层",     13800,     472,     44,    39),
    (19, "筑基九层",     15700,     519,     48,    43),
    (20, "筑基十层",     18000,     571,     53,    47),
    # ── 金丹期（21-30）──
    (21, "金丹一层",     22000,     700,     68,    62),
    (22, "金丹二层",     26000,     770,     75,    68),
    (23, "金丹三层",     31000,     847,     83,    75),
    (24, "金丹四层",     36500,     932,     91,    83),
    (25, "金丹五层",     43000,     1025,    100,   91),
    (26, "金丹六层",     50500,     1128,    110,   100),
    (27, "金丹七层",     60000,     1241,    121,   110),
    (28, "金丹八层",     70000,     1365,    133,   121),
    (29, "金丹九层",     82000,     1502,    146,   133),
    (30, "金丹十层",     97000,     1652,    161,   146),
    # ── 元婴期（31-40）──
    (31, "元婴一层",     110000,    2050,    202,   190),
    (32, "元婴二层",     130000,    2255,    222,   209),
    (33, "元婴三层",     153000,    2481,    244,   230),
    (34, "元婴四层",     181000,    2729,    268,   253),
    (35, "元婴五层",     214000,    3002,    295,   278),
    (36, "元婴六层",     253000,    3302,    325,   306),
    (37, "元婴七层",     299000,    3632,    357,   337),
    (38, "元婴八层",     353000,    3996,    393,   371),
    (39, "元婴九层",     417000,    4395,    432,   408),
    (40, "元婴十层",     493000,    4835,    475,   449),
    # ── 化神期（41-50）──
    (41, "化神一层",     560000,    6000,    530,   505),
    (42, "化神二层",     661000,    6600,    583,   556),
    (43, "化神三层",     780000,    7260,    641,   612),
    (44, "化神四层",     921000,    7986,    705,   673),
    (45, "化神五层",     1087000,   8785,    776,   740),
    (46, "化神六层",     1282000,   9664,    854,   814),
    (47, "化神七层",     1513000,   10630,   939,   896),
    (48, "化神八层",     1785000,   11693,   1033,  986),
    (49, "化神九层",     2106000,   12862,   1136,  1084),
    (50, "化神十层",     2485000,   14148,   1250,  1192),
    # ── 炼虚期（51-60）──
    (51, "炼虚一层",     2800000,   17500,   1500,  1425),
    (52, "炼虚二层",     3300000,   19250,   1650,  1568),
    (53, "炼虚三层",     3900000,   21175,   1815,  1725),
    (54, "炼虚四层",     4600000,   23293,   1997,  1898),
    (55, "炼虚五层",     5400000,   25622,   2197,  2088),
    (56, "炼虚六层",     6400000,   28184,   2417,  2297),
    (57, "炼虚七层",     7500000,   31002,   2659,  2527),
    (58, "炼虚八层",     8900000,   34102,   2925,  2780),
    (59, "炼虚九层",     10500000,  37512,   3218,  3058),
    (60, "炼虚十层",     12400000,  41264,   3540,  3363),
    # ── 合体期（61-70）──
    (61, "合体一层",     14000000,  51000,   4250,  4038),
    (62, "合体二层",     16500000,  56100,   4675,  4442),
    (63, "合体三层",     19500000,  61710,   5143,  4886),
    (64, "合体四层",     23000000,  67881,   5657,  5375),
    (65, "合体五层",     27000000,  74669,   6223,  5913),
    (66, "合体六层",     32000000,  82136,   6845,  6504),
    (67, "合体七层",     38000000,  90350,   7530,  7154),
    (68, "合体八层",     45000000,  99385,   8283,  7869),
    (69, "合体九层",     53000000,  109324,  9111,  8656),
    (70, "合体十层",     62000000,  120257,  10022, 9521),
    # ── 大乘期（71-80）──
    (71, "大乘一层",     71000000,  145000,  12500, 11875),
    (72, "大乘二层",     83000000,  159500,  13750, 13063),
    (73, "大乘三层",     98000000,  175450,  15125, 14369),
    (74, "大乘四层",     115000000, 192995,  16638, 15806),
    (75, "大乘五层",     136000000, 212295,  18302, 17387),
    (76, "大乘六层",     160000000, 233525,  20132, 19126),
    (77, "大乘七层",     189000000, 256878,  22145, 21038),
    (78, "大乘八层",     223000000, 282566,  24360, 23142),
    (79, "大乘九层",     263000000, 310823,  26796, 25456),
    (80, "大乘十层",     310000000, 341906,  29476, 28003),
    # ── 渡劫期（81-90）──
    (81, "渡劫一层",     360000000, 412000,  35500, 33725),
    (82, "渡劫二层",     425000000, 453200,  39050, 37098),
    (83, "渡劫三层",     500000000, 498520,  42955, 40808),
    (84, "渡劫四层",     590000000, 548372,  47251, 44889),
    (85, "渡劫五层",     696000000, 603210,  51976, 49377),
    (86, "渡劫六层",     820000000, 663531,  57174, 54315),
    (87, "渡劫七层",     967000000, 729884,  62892, 59747),
    (88, "渡劫八层",     1140000000,802873,  69181, 65722),
    (89, "渡劫九层",     1344000000,883161,  76099, 72294),
    (90, "渡劫十层",     0,          971478,  83709, 79524),  # max_exp=0 已到顶
]

REALM_NAMES = {r[0]: r[1] for r in REALMS}
REALM_MAX_IDX = len(REALMS) - 1  # = 90
INFINITE_REALM_START_IDX = 91    # DP巅峰 起始索引

# 大境界名称 → (min_idx, max_idx)
MAJOR_REALM_RANGES = {
    "练气": (1,  10),
    "筑基": (11, 20),
    "金丹": (21, 30),
    "元婴": (31, 40),
    "化神": (41, 50),
    "炼虚": (51, 60),
    "合体": (61, 70),
    "大乘": (71, 80),
    "渡劫": (81, 90),
}


# ─────────────────────────── 大境界配置缓存 ──────────────────────────────────

_major_realm_cache = None  # List of GameMajorRealmConfig or None


def _get_major_realm_configs():
    """从 DB 加载大境界配置列表（带缓存）"""
    global _major_realm_cache
    if _major_realm_cache is not None:
        return _major_realm_cache
    try:
        from bot.sql_helper.sql_game import sql_get_all_major_realms
        rows = sql_get_all_major_realms(include_disabled=False)
        if rows:
            _major_realm_cache = sorted(rows, key=lambda r: r.min_idx)
            return _major_realm_cache
    except Exception:
        pass
    return []


def reload_major_realm_cache():
    """清除大境界缓存，强制下次重新读取"""
    global _major_realm_cache
    _major_realm_cache = None


def _compute_realm_from_major(idx: int):
    """
    从大境界 base+step 配置计算指定索引的境界属性。
    返回 (idx, name, max_exp, hp, atk, def) 或 None。
    """
    configs = _get_major_realm_configs()
    if not configs:
        return None
    for mc in sorted(configs, key=lambda r: r.min_idx, reverse=True):
        if mc.is_infinite:
            continue
        if mc.min_idx <= idx < mc.min_idx + (mc.layer_count or 10):
            layer = idx - mc.min_idx
            # 最后一层（渡劫十层 idx=90）修为上限强制为 0
            is_last = (mc.sort_order == max(c.sort_order for c in configs if not c.is_infinite)
                       and layer == (mc.layer_count or 10) - 1)
            max_exp = 0 if is_last else (mc.base_max_exp + layer * mc.step_max_exp)
            hp  = mc.base_max_hp  + layer * mc.step_max_hp
            atk = mc.base_attack  + layer * mc.step_attack
            def_ = mc.base_defense + layer * mc.step_defense
            # 名称：优先从 GameRealmConfig 取，fallback 到硬编码
            name = REALM_NAMES.get(idx, f"{mc.major_realm}{layer + 1}层")
            return (idx, name, int(max_exp), int(hp), int(atk), int(def_))
    return None


def _get_infinite_realm(idx: int):
    """计算无限境界（DP巅峰）的属性"""
    configs = _get_major_realm_configs()
    inf_mc = None
    for mc in configs:
        if mc.is_infinite and idx >= mc.min_idx:
            inf_mc = mc
            break
    tier = idx - (inf_mc.min_idx if inf_mc else INFINITE_REALM_START_IDX)
    layer_num = tier + 1
    name = f"DP巅峰{layer_num}层"
    if inf_mc:
        max_exp = int(inf_mc.base_max_exp + tier * inf_mc.step_max_exp)
        hp   = int(inf_mc.base_max_hp + tier * inf_mc.step_max_hp)
        atk  = int(inf_mc.base_attack  + tier * inf_mc.step_attack)
        def_ = int(inf_mc.base_defense + tier * inf_mc.step_defense)
    else:
        # 硬编码 fallback
        max_exp = 2000000000 + tier * 500000000
        hp   = 1200000 + tier * 100000
        atk  = 95000  + tier * 10000
        def_ = 90000  + tier * 9000
    return (idx, name, max_exp, hp, atk, def_)


# ─────────────────────────── 境界 DB 缓存 ─────────────────────────────────────

_realm_cache = None  # List of GameRealmConfig or None


def get_realm_from_db(idx: int):
    """从DB读取境界配置，失败则fallback到硬编码REALMS"""
    global _realm_cache
    try:
        from bot.sql_helper.sql_game import sql_get_all_realms
        if _realm_cache is None:
            rows = sql_get_all_realms(include_disabled=False)
            if rows:
                _realm_cache = sorted(rows, key=lambda r: r.realm_idx)
        if _realm_cache:
            for r in _realm_cache:
                if r.realm_idx == idx:
                    return (r.realm_idx, r.name, r.max_exp, r.base_max_hp, r.base_attack, r.base_defense)
    except Exception:
        pass
    return None


def reload_realm_cache():
    """清除境界缓存，强制下次重新读取"""
    global _realm_cache
    _realm_cache = None


def get_realm(idx: int) -> tuple:
    """返回境界元组 (idx, name, max_exp, hp, atk, def)
    优先级：无限境界计算 > 大境界 base+step 计算 > 个体 DB > 硬编码
    """
    # 1. 无限境界（DP巅峰）
    if idx >= INFINITE_REALM_START_IDX:
        return _get_infinite_realm(idx)
    # 2. 从大境界配置按 base+step 计算
    computed = _compute_realm_from_major(idx)
    if computed:
        return computed
    # 3. 个体 GameRealmConfig（fallback）
    db_realm = get_realm_from_db(idx)
    if db_realm:
        return db_realm
    # 4. 硬编码 REALMS
    idx = max(0, min(idx, REALM_MAX_IDX))
    return REALMS[idx]


def get_realm_max_idx() -> int:
    """获取最大有限境界索引（渡劫十层=90），不含无限境界"""
    global _realm_cache
    try:
        from bot.sql_helper.sql_game import sql_get_all_realms
        if _realm_cache is None:
            rows = sql_get_all_realms(include_disabled=False)
            if rows:
                _realm_cache = sorted(rows, key=lambda r: r.realm_idx)
        if _realm_cache:
            return max(r.realm_idx for r in _realm_cache)
    except Exception:
        pass
    return REALM_MAX_IDX


def get_realm_name(idx: int) -> str:
    return get_realm(idx)[1]


# ─────────────────────────── 突破所需丹药 ────────────────────────────────────
# 格式：(realm_range_min, realm_range_max, item_id, item_name)
# 肉体凡胎(0)→练气一层(1) 不需要丹药，所以从1开始
# 渡劫十层(90) 为顶级境界，不需要突破丹药
BREAKTHROUGH_PILLS = [
    (1,  10, "zhujidan",         "筑基丹"),       # 练气期 1-10 层
    (11, 20, "jindan_guoguo",    "金丹道果"),      # 筑基期 11-20 层
    (21, 30, "yuanying_zhenzhu", "元婴真珠"),      # 金丹期 21-30 层
    (31, 40, "huashen_lingdan",  "化神灵丹"),      # 元婴期 31-40 层
    (41, 50, "lianzhen_lingqi",  "炼真灵气"),      # 化神期 41-50 层
    (51, 60, "lianzhu_lingshi",  "炼虚灵晶"),      # 炼虚期 51-60 层
    (61, 70, "heti_lingshi",     "合体灵晶"),      # 合体期 61-70 层
    (71, 80, "dacheng_lingshi",  "大乘灵石"),      # 大乘期 71-80 层
]


def get_breakthrough_pill(realm_idx: int):
    """
    根据当前境界返回对应突破丹药 (item_id, item_name)。
    优先从物品管理 DB 中查询 item_type='breakthrough' 且
    realm_req_min <= realm_idx <= realm_req_max 的启用物品；
    若 DB 无匹配则回退到硬编码 BREAKTHROUGH_PILLS 列表。
    """
    try:
        from bot.sql_helper.sql_game import sql_get_all_items
        items = sql_get_all_items(include_disabled=False)
        pills = [it for it in items if getattr(it, 'item_type', '') == 'breakthrough']
        for it in pills:
            rmin = getattr(it, 'realm_req_min', None)
            rmax = getattr(it, 'realm_req_max', None)
            if rmin is not None and rmax is not None and rmin <= realm_idx <= rmax:
                return it.item_id, it.name
    except Exception:
        pass
    # fallback: 硬编码列表
    for rmin, rmax, item_id, item_name in BREAKTHROUGH_PILLS:
        if rmin <= realm_idx <= rmax:
            return item_id, item_name
    return None, None


# ─────────────────────────── 初始物品数据 ────────────────────────────────────

INITIAL_ITEMS = [
    # ── 消耗品（普通/稀有）───────────────────────────────────────────────────────
    dict(item_id="huichun_dan",   name="回春丹",     item_type="potion",
         heal_min=50,  heal_max=100, rarity="common",   usable_in_bag=True,
         description="基础回复丹，随处可见，回血 50~100。"),
    dict(item_id="zhongji_huichun", name="中级回春丹", item_type="potion",
         heal_min=150, heal_max=250, rarity="rare",     usable_in_bag=True,
         description="中阶炼药师所制，回复效果不错，回血 150~250。"),
    # 团本护盾类（仅战斗中使用）
    dict(item_id="huti_lingfu",   name="护体灵符",   item_type="potion",
         shield_min=40, shield_max=80, rarity="common", usable_in_bag=False,
         description="常见灵符，团本战斗中使用，提供护盾 40~80。"),
    # 突破丹药
    dict(item_id="zhujidan",         name="筑基丹",   item_type="breakthrough",
         realm_req_min=1,  realm_req_max=10, break_boost=20, rarity="uncommon"),
    dict(item_id="jindan_guoguo",    name="金丹道果", item_type="breakthrough",
         realm_req_min=11, realm_req_max=20, break_boost=20, rarity="rare"),
    dict(item_id="yuanying_zhenzhu", name="元婴真珠", item_type="breakthrough",
         realm_req_min=21, realm_req_max=30, break_boost=20, rarity="epic"),
    dict(item_id="huashen_lingdan",  name="化神灵丹", item_type="breakthrough",
         realm_req_min=31, realm_req_max=40, break_boost=20, rarity="epic"),
    dict(item_id="lianzhen_lingqi",  name="炼真灵气", item_type="breakthrough",
         realm_req_min=41, realm_req_max=50, break_boost=20, rarity="legendary"),
    dict(item_id="lianzhu_lingshi",  name="炼虚灵晶", item_type="breakthrough",
         realm_req_min=51, realm_req_max=60, break_boost=20, rarity="legendary"),
    dict(item_id="heti_lingshi",     name="合体灵晶", item_type="breakthrough",
         realm_req_min=61, realm_req_max=70, break_boost=20, rarity="legendary"),
    dict(item_id="dacheng_lingshi",  name="大乘灵石", item_type="breakthrough",
         realm_req_min=71, realm_req_max=80, break_boost=20, rarity="legendary"),
    # ── 武器（普通）────────────────────────────────────────────────────────────
    dict(item_id="qingfengjian",  name="清风剑",     item_type="equipment",
         slot="weapon", atk_bonus=10, rarity="common",
         description="入门级长剑，轻便好用，攻击 +10。"),
    # ── 护甲（普通/优良）────────────────────────────────────────────────────────
    dict(item_id="xuanbing_jia",  name="玄冰甲",     item_type="equipment",
         slot="armor",  def_bonus=8,  rarity="common",
         description="寒冰铁锻造，坚固耐用，防御 +8。"),
    dict(item_id="tianhuo_pao",   name="天火袍",     item_type="equipment",
         slot="armor",  def_bonus=7, atk_bonus=5, rarity="uncommon",
         description="以天火凤羽织就，攻防兼备，攻击 +5、防御 +7。"),
    # ── 饰品（稀有）────────────────────────────────────────────────────────────
    dict(item_id="hunyuan_zhi",   name="混元珠",     item_type="equipment",
         slot="accessory", atk_bonus=5, def_bonus=5, hp_bonus=50, rarity="rare",
         description="混沌元气凝聚之珠，属性均衡，攻击 +5、防御 +5、最大血量 +50。"),
    # ── 武器（分级：优良/稀有/史诗/传说）──────────────────────────────────────
    dict(item_id="liuying_jian",   name="流影剑",   item_type="equipment",
         slot="weapon", atk_bonus=20, rarity="uncommon",
         description="剑光流转如影随形，出手迅捷，攻击 +20。"),
    dict(item_id="ziyun_dao",      name="紫云刀",   item_type="equipment",
         slot="weapon", atk_bonus=40, def_bonus=5, rarity="rare",
         description="刀身如紫云翻卷，杀伐之气十足，攻击 +40、防御 +5。"),
    dict(item_id="zhanlong_ge",    name="斩龙戈",   item_type="equipment",
         slot="weapon", atk_bonus=70, def_bonus=10, rarity="epic",
         description="据传此戈曾斩杀一条蛟龙，霸气锋锐，攻击 +70、防御 +10。"),
    dict(item_id="taiyi_shenjian", name="太易神剑", item_type="equipment",
         slot="weapon", atk_bonus=130, hp_bonus=80, rarity="legendary",
         description="太易境界所铸神兵，剑意通天，攻击 +130、最大血量 +80。"),
    # ── 护甲（分级：优良/稀有/史诗/传说）──────────────────────────────────────
    dict(item_id="lingxia_pao",    name="灵霞袍",   item_type="equipment",
         slot="armor", def_bonus=16, hp_bonus=50, rarity="uncommon",
         description="以五色灵霞织就，轻盈又护体，防御 +16、最大血量 +50。"),
    dict(item_id="xuanwu_jia",     name="玄武甲",   item_type="equipment",
         slot="armor", def_bonus=30, hp_bonus=120, rarity="rare",
         description="仿玄武神兽形制打造，坚若磐石，防御 +30、最大血量 +120。"),
    dict(item_id="dixuan_kai",     name="地玄铠",   item_type="equipment",
         slot="armor", def_bonus=55, hp_bonus=250, rarity="epic",
         description="取地脉玄铁冶炼而成，防御 +55、最大血量 +250。"),
    # ── 饰品（分级：优良/稀有/史诗/传说）──────────────────────────────────────
    dict(item_id="judao_jie",      name="聚道结",   item_type="equipment",
         slot="accessory", atk_bonus=8, def_bonus=8, hp_bonus=30, rarity="uncommon",
         description="一枚汇聚道则之力的结环，攻防均衡，攻击 +8、防御 +8、血量 +30。"),
    dict(item_id="xueying_pai",    name="血影牌",   item_type="equipment",
         slot="accessory", atk_bonus=22, hp_bonus=130, rarity="rare",
         description="血色符文镌刻其上，激发潜在杀意，攻击 +22、最大血量 +130。"),
    dict(item_id="tianyuan_pei",   name="天元佩",   item_type="equipment",
         slot="accessory", def_bonus=32, hp_bonus=280, rarity="epic",
         description="天元之气凝固成形，守护力极强，防御 +32、最大血量 +280。"),
    dict(item_id="wuji_huan",      name="无极环",   item_type="equipment",
         slot="accessory", atk_bonus=65, def_bonus=65, hp_bonus=500, rarity="legendary",
         description="无极大道化形为环，攻守兼备，攻击 +65、防御 +65、最大血量 +500。"),
    # ── BOSS 级掉落（传说）──────────────────────────────────────────────────────
    dict(item_id="boss_fox_pelt",    name="千年狐裘",   item_type="equipment",
         slot="armor", def_bonus=20, hp_bonus=80, rarity="legendary"),
    dict(item_id="boss_demon_blade", name="魔刀碎片",   item_type="equipment",
         slot="weapon", atk_bonus=25, rarity="legendary"),
    dict(item_id="boss_ancient_seal", name="古战场印记", item_type="equipment",
         slot="accessory", atk_bonus=15, def_bonus=15, hp_bonus=150, rarity="legendary"),
    dict(item_id="boss_heaven_crown", name="天界遗冠",  item_type="equipment",
         slot="armor", def_bonus=40, hp_bonus=300, rarity="legendary"),
    # ── 消耗品（分级：普通→传说）──────────────────────────────────────────────
    dict(item_id="lingzhi_pian",    name="灵芝碎片",   item_type="potion",
         heal_min=15, heal_max=40, rarity="common",    usable_in_bag=True,
         description="灵芝边角料，回复少量生命，常见于荒野修行中。回血 15~40。"),
    dict(item_id="huixue_ling",     name="回血灵液",   item_type="potion",
         heal_min=80, heal_max=160, rarity="uncommon", usable_in_bag=True,
         description="灵泉水凝炼而成，回复中量生命。回血 80~160。"),
    dict(item_id="gaoji_huichun",   name="高级回春丹", item_type="potion",
         heal_min=400, heal_max=700, rarity="epic",    usable_in_bag=True,
         description="顶级炼丹师所炼，回复大量生命。回血 400~700。"),
    dict(item_id="quanfu_shendan",  name="全复神丹",   item_type="potion",
         heal_min=1000, heal_max=2000, rarity="legendary", usable_in_bag=True,
         description="传说中的九转还魂丹，几乎可完全恢复生命。回血 1000~2000。"),
    dict(item_id="tieling_pei",     name="铁灵佩",     item_type="potion",
         shield_min=100, shield_max=180, rarity="uncommon", usable_in_bag=False,
         description="铁制符牌，团本战斗中使用，提供护盾 100~180。"),
    dict(item_id="xuanjin_hu",      name="玄金护体",   item_type="potion",
         shield_min=200, shield_max=350, rarity="rare",     usable_in_bag=False,
         description="玄金为材铸造，可吸收大量伤害，护盾 200~350。"),
    dict(item_id="taiyi_shenhu",    name="太乙神护",   item_type="potion",
         shield_min=400, shield_max=650, rarity="epic",     usable_in_bag=False,
         description="太乙真火淬炼，护盾坚不可摧，护盾 400~650。"),
    dict(item_id="lingxue_jing",    name="灵血晶",     item_type="potion",
         heal_min=150, heal_max=280, shield_min=120, shield_max=200,
         rarity="rare", usable_in_bag=True,
         description="血灵双效珍材，背包中使用时回血 150~280；团本中亦可提供护盾 120~200。"),
]

# ─────────────────────────── 初始 BOSS 数据 ──────────────────────────────────

INITIAL_BOSSES = [
    # ── 11 个大境界对应 BOSS ───────────────────────────────────────────────────
    dict(
        boss_id="realm_boss_0",
        name="山野凶兽",
        recommend_realm=0,
        hp=200, shield=0,
        atk_min=3, atk_max=8,
        def_min=3, def_max=8,
        heal_min=10, heal_max=20,
        cd_hours=2,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_1",
        name="气海邪魔",
        recommend_realm=5,
        hp=500, shield=0,
        atk_min=10, atk_max=20,
        def_min=10, def_max=20,
        heal_min=25, heal_max=50,
        cd_hours=4,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_2",
        name="筑基邪修",
        recommend_realm=15,
        hp=2000, shield=100,
        atk_min=35, atk_max=65,
        def_min=30, def_max=60,
        heal_min=80, heal_max=160,
        cd_hours=8,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_3",
        name="金丹魔君",
        recommend_realm=25,
        hp=8000, shield=500,
        atk_min=100, atk_max=180,
        def_min=80, def_max=150,
        heal_min=300, heal_max=600,
        cd_hours=12,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_4",
        name="元婴老怪",
        recommend_realm=35,
        hp=30000, shield=2000,
        atk_min=350, atk_max=550,
        def_min=250, def_max=450,
        heal_min=1000, heal_max=2000,
        cd_hours=24,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_5",
        name="化神战尊",
        recommend_realm=45,
        hp=100000, shield=8000,
        atk_min=1000, atk_max=1600,
        def_min=800, def_max=1400,
        heal_min=3000, heal_max=6000,
        cd_hours=36,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_6",
        name="炼虚圣主",
        recommend_realm=55,
        hp=350000, shield=25000,
        atk_min=2800, atk_max=4500,
        def_min=2000, def_max=3500,
        heal_min=10000, heal_max=20000,
        cd_hours=48,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_7",
        name="合体始祖",
        recommend_realm=65,
        hp=1200000, shield=80000,
        atk_min=8000, atk_max=13000,
        def_min=6000, def_max=10000,
        heal_min=35000, heal_max=65000,
        cd_hours=72,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_8",
        name="大乘神魔",
        recommend_realm=75,
        hp=4000000, shield=300000,
        atk_min=25000, atk_max=38000,
        def_min=18000, def_max=30000,
        heal_min=120000, heal_max=220000,
        cd_hours=96,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_9",
        name="渡劫天劫化身",
        recommend_realm=85,
        hp=15000000, shield=1000000,
        atk_min=70000, atk_max=110000,
        def_min=50000, def_max=85000,
        heal_min=400000, heal_max=800000,
        cd_hours=168,
        min_players=2, max_players=4,
    ),
    dict(
        boss_id="realm_boss_10",
        name="太古神魔",
        recommend_realm=91,
        hp=50000000, shield=3000000,
        atk_min=150000, atk_max=250000,
        def_min=110000, def_max=190000,
        heal_min=1500000, heal_max=3000000,
        cd_hours=240,
        min_players=2, max_players=4,
    ),
]

# ─────────────────────────── BOSS 掉落表 ─────────────────────────────────────
# 新格式：(boss_id, item_id, drop_rate)  drop_rate 为权重，每个 BOSS 的条目合计 = 1.0
# 每次击杀后每位玩家从权重池中独立随机抽取 1 件物品（合计<1.0 则有概率无掉落）
INITIAL_LOOT = [
    # ── 山野凶兽（肉体凡胎）────────────────────────────────────────────────────
    ("realm_boss_0",  "huichun_dan",      0.70),
    ("realm_boss_0",  "lingzhi_pian",     0.30),
    # ── 气海邪魔（练气）───────────────────────────────────────────────────────
    ("realm_boss_1",  "huichun_dan",      0.35),
    ("realm_boss_1",  "lingzhi_pian",     0.20),
    ("realm_boss_1",  "huti_lingfu",      0.20),
    ("realm_boss_1",  "tieling_pei",      0.10),
    ("realm_boss_1",  "zhujidan",         0.15),
    # ── 筑基邪修（筑基）───────────────────────────────────────────────────────
    ("realm_boss_2",  "zhongji_huichun",  0.25),
    ("realm_boss_2",  "huixue_ling",      0.15),
    ("realm_boss_2",  "huti_lingfu",      0.20),
    ("realm_boss_2",  "tieling_pei",      0.15),
    ("realm_boss_2",  "liuying_jian",     0.10),
    ("realm_boss_2",  "jindan_guoguo",    0.15),
    # ── 金丹魔君（金丹）───────────────────────────────────────────────────────
    ("realm_boss_3",  "zhongji_huichun",  0.20),
    ("realm_boss_3",  "huixue_ling",      0.15),
    ("realm_boss_3",  "xuanjin_hu",       0.15),
    ("realm_boss_3",  "tianhuo_pao",      0.12),
    ("realm_boss_3",  "lingxia_pao",      0.10),
    ("realm_boss_3",  "ziyun_dao",        0.08),
    ("realm_boss_3",  "yuanying_zhenzhu", 0.10),
    ("realm_boss_3",  "judao_jie",        0.10),
    # ── 元婴老怪（元婴）───────────────────────────────────────────────────────
    ("realm_boss_4",  "zhongji_huichun",  0.20),
    ("realm_boss_4",  "huixue_ling",      0.15),
    ("realm_boss_4",  "xuanjin_hu",       0.15),
    ("realm_boss_4",  "lingxue_jing",     0.10),
    ("realm_boss_4",  "xuanwu_jia",       0.10),
    ("realm_boss_4",  "judao_jie",        0.10),
    ("realm_boss_4",  "huashen_lingdan",  0.10),
    ("realm_boss_4",  "hunyuan_zhi",      0.10),
    # ── 化神战尊（化神）───────────────────────────────────────────────────────
    ("realm_boss_5",  "zhongji_huichun",  0.15),
    ("realm_boss_5",  "huixue_ling",      0.15),
    ("realm_boss_5",  "taiyi_shenhu",     0.15),
    ("realm_boss_5",  "lingxue_jing",     0.10),
    ("realm_boss_5",  "zhanlong_ge",      0.08),
    ("realm_boss_5",  "xueying_pai",      0.10),
    ("realm_boss_5",  "hunyuan_zhi",      0.10),
    ("realm_boss_5",  "lianzhen_lingqi",  0.10),
    ("realm_boss_5",  "xuanwu_jia",       0.07),
    # ── 炼虚圣主（炼虚）───────────────────────────────────────────────────────
    ("realm_boss_6",  "gaoji_huichun",    0.15),
    ("realm_boss_6",  "taiyi_shenhu",     0.15),
    ("realm_boss_6",  "lingxue_jing",     0.10),
    ("realm_boss_6",  "dixuan_kai",       0.08),
    ("realm_boss_6",  "tianyuan_pei",     0.10),
    ("realm_boss_6",  "zhanlong_ge",      0.08),
    ("realm_boss_6",  "hunyuan_zhi",      0.10),
    ("realm_boss_6",  "lianzhu_lingshi",  0.12),
    ("realm_boss_6",  "boss_fox_pelt",    0.06),
    ("realm_boss_6",  "boss_demon_blade", 0.06),
    # ── 合体始祖（合体）───────────────────────────────────────────────────────
    ("realm_boss_7",  "gaoji_huichun",    0.15),
    ("realm_boss_7",  "taiyi_shenhu",     0.15),
    ("realm_boss_7",  "lingxue_jing",     0.08),
    ("realm_boss_7",  "dixuan_kai",       0.08),
    ("realm_boss_7",  "tianyuan_pei",     0.10),
    ("realm_boss_7",  "taiyi_shenjian",   0.06),
    ("realm_boss_7",  "hunyuan_zhi",      0.10),
    ("realm_boss_7",  "heti_lingshi",     0.12),
    ("realm_boss_7",  "boss_ancient_seal",0.08),
    ("realm_boss_7",  "wuji_huan",        0.04),
    # ── 大乘神魔（大乘）───────────────────────────────────────────────────────
    ("realm_boss_8",  "gaoji_huichun",    0.20),
    ("realm_boss_8",  "taiyi_shenhu",     0.15),
    ("realm_boss_8",  "lingxue_jing",     0.08),
    ("realm_boss_8",  "dixuan_kai",       0.08),
    ("realm_boss_8",  "tianyuan_pei",     0.08),
    ("realm_boss_8",  "taiyi_shenjian",   0.08),
    ("realm_boss_8",  "dacheng_lingshi",  0.12),
    ("realm_boss_8",  "boss_heaven_crown",0.08),
    ("realm_boss_8",  "wuji_huan",        0.06),
    # ── 渡劫天劫化身（渡劫）────────────────────────────────────────────────────
    ("realm_boss_9",  "gaoji_huichun",    0.15),
    ("realm_boss_9",  "quanfu_shendan",   0.10),
    ("realm_boss_9",  "taiyi_shenhu",     0.15),
    ("realm_boss_9",  "lingxue_jing",     0.08),
    ("realm_boss_9",  "tianyuan_pei",     0.08),
    ("realm_boss_9",  "taiyi_shenjian",   0.08),
    ("realm_boss_9",  "dacheng_lingshi",  0.12),
    ("realm_boss_9",  "boss_ancient_seal",0.08),
    ("realm_boss_9",  "wuji_huan",        0.08),
    ("realm_boss_9",  "boss_heaven_crown",0.05),
    # ── 太古神魔（DP巅峰）──────────────────────────────────────────────────────
    ("realm_boss_10", "gaoji_huichun",    0.15),
    ("realm_boss_10", "quanfu_shendan",   0.15),
    ("realm_boss_10", "taiyi_shenhu",     0.15),
    ("realm_boss_10", "lingxue_jing",     0.08),
    ("realm_boss_10", "taiyi_shenjian",   0.10),
    ("realm_boss_10", "wuji_huan",        0.10),
    ("realm_boss_10", "boss_heaven_crown",0.07),
    ("realm_boss_10", "boss_ancient_seal",0.07),
    ("realm_boss_10", "boss_demon_blade", 0.07),
    ("realm_boss_10", "boss_fox_pelt",    0.06),
]

# ─────────────────────────── 修行随机事件 ─────────────────────────────────────
# 基础定义：name/desc/item_drop 固定，weight/exp_mult/hp_change 可由 Admin 在概率管理中覆盖
# hp_change_pct 正=回复，负=损失（相对最大HP的百分比）
CULTIVATION_EVENTS = [
    {
        "id": "normal",
        "name": "平静修行",
        "desc": "你端坐蒲团，感受天地灵气缓缓流入经脉，心境平和。",
        "item_drop": [],
    },
    {
        "id": "lucky",
        "name": "奇遇天降",
        "desc": "灵气忽然涌动，你循着感应发现了一处天然灵穴，盘膝而坐，修为大涨！",
        "item_drop": [
            ("lingzhi_pian",  0.40),
            ("huichun_dan",   0.25),
            ("huixue_ling",   0.15),
            ("huti_lingfu",   0.20),
            ("zhujidan",      0.10),
        ],
    },
    {
        "id": "evil_cultivator",
        "name": "邪修袭扰",
        "desc": "一名邪道修士突然现身，对你发动偷袭！你奋力将其击退，但也挂了彩。",
        "item_drop": [],
    },
    {
        "id": "spirit_spring",
        "name": "灵泉洗髓",
        "desc": "你偶然踏入一片隐秘谷地，泉水汩汩而涌，浸泡其中，筋骨一新，伤势全消！",
        "item_drop": [],
    },
    {
        "id": "fierce_beast",
        "name": "凶兽来袭",
        "desc": "一头饥肠辘辘的凶兽突破结界扑来！你虽击退了它，却也付出了代价。",
        "item_drop": [
            ("lingzhi_pian",  0.40),
            ("huichun_dan",   0.35),
            ("huti_lingfu",   0.25),
            ("tieling_pei",   0.12),
            ("qingfengjian",  0.08),
            ("xuanbing_jia",  0.08),
        ],
    },
    {
        "id": "enlightenment",
        "name": "顿悟时刻",
        "desc": "灵光一闪，你猛然参透了一段功法玄机，心神沉浸其中，修为飞速精进！",
        "item_drop": [
            ("zhujidan",      0.08),
            ("tieling_pei",   0.15),
            ("huti_lingfu",   0.20),
            ("judao_jie",     0.06),
        ],
    },
    {
        "id": "demon_invasion",
        "name": "魔气侵体",
        "desc": "修炼之时，一股浊重的魔气从地底涌出，侵入你的识海，令你心神大乱！",
        "item_drop": [],
    },
    {
        "id": "ancient_text",
        "name": "拾得古籍",
        "desc": "你在山洞深处发现了一本残破的古籍，字字玑珠，研读片刻便有所领悟。",
        "item_drop": [
            ("lingzhi_pian",  0.30),
            ("huichun_dan",   0.20),
            ("huti_lingfu",   0.20),
            ("tieling_pei",   0.10),
        ],
    },
    {
        "id": "heavenly_thunder",
        "name": "天雷淬体",
        "desc": "天空骤变，一道天雷轰然劈下！你险死还生，却在雷火灼烧中被迫开辟了新的经脉。",
        "item_drop": [
            ("lingzhi_pian",  0.40),
            ("huichun_dan",   0.40),
            ("huixue_ling",   0.15),
        ],
    },
    {
        "id": "spirit_rain",
        "name": "灵雨降临",
        "desc": "细细的灵雨从天而降，每一滴都蕴含着天地精华，你尽情沐浴，气脉通畅无比。",
        "item_drop": [],
    },
    {
        "id": "lost_in_wild",
        "name": "迷路荒野",
        "desc": "你追逐一只神秘灵禽，不知不觉深入荒野，等回过神来，大半天的修炼时间已白白虚度……",
        "item_drop": [],
    },
    {
        "id": "spirit_beast",
        "name": "灵兽相伴",
        "desc": "一只温顺的灵兽悄然凑近，蜷伏于你身旁。它的灵气与你的修炼产生了奇妙共鸣。",
        "item_drop": [
            ("lingzhi_pian",  0.25),
            ("huti_lingfu",   0.20),
            ("tieling_pei",   0.10),
        ],
    },
    {
        "id": "fellow_daoist",
        "name": "同门切磋",
        "desc": "一位同门道友前来拜访，两人切磋交流，相互印证功法，皆有所得。",
        "item_drop": [
            ("lingzhi_pian",  0.25),
            ("huichun_dan",   0.15),
            ("judao_jie",     0.05),
        ],
    },
    {
        "id": "evil_qi",
        "name": "走火入魔",
        "desc": "你强行催动功法冲关，不料气机逆行，走火入魔！体内真气横冲直撞，五脏震荡。",
        "item_drop": [
            ("lingzhi_pian",  0.35),
            ("huichun_dan",   0.55),
            ("huixue_ling",   0.20),
        ],
    },
    {
        "id": "treasure_find",
        "name": "洞天遗宝",
        "desc": "你意外推开了一处隐秘洞府的石门，里面零落着先人遗留的几件宝物。",
        "item_drop": [
            ("lingzhi_pian",  0.30),
            ("tieling_pei",   0.20),
            ("huti_lingfu",   0.25),
            ("zhujidan",      0.12),
            ("liuying_jian",  0.10),
            ("lingxia_pao",   0.08),
            ("judao_jie",     0.10),
            ("qingfengjian",  0.08),
        ],
    },
    {
        "id": "meridian_damage",
        "name": "经脉受损",
        "desc": "修炼时一股逆流真气冲击经脉，你强行压制，却留下了暗伤，修为倒退了一截。",
        "item_drop": [
            ("lingzhi_pian",  0.35),
            ("huichun_dan",   0.35),
        ],
    },
    {
        "id": "spirit_stone",
        "name": "灵石矿脉",
        "desc": "你在山壁间发现了一条细小的灵石矿脉，随手取了几块，灵气充沛，修炼事半功倍。",
        "item_drop": [
            ("huti_lingfu",   0.25),
            ("tieling_pei",   0.15),
            ("lingzhi_pian",  0.20),
        ],
    },
    {
        "id": "pill_furnace",
        "name": "遗落丹炉",
        "desc": "荒草丛中，一只古旧丹炉兀自燃烧，炉中残余的丹气被你尽数吸收，大有裨益。",
        "item_drop": [
            ("lingzhi_pian",  0.35),
            ("huichun_dan",   0.30),
            ("zhujidan",      0.12),
            ("huixue_ling",   0.10),
        ],
    },
    {
        "id": "illusion_trap",
        "name": "幻阵困身",
        "desc": "你不慎踏入一处上古幻阵，在虚幻与现实间挣扎了许久，精神大耗，修为也随之消散。",
        "item_drop": [],
    },
    {
        "id": "dao_heart_test",
        "name": "道心历练",
        "desc": "心魔突现，以你最深的执念化形来袭。你以道心迎战，虽险胜，却也因此对大道有了更深的感悟。",
        "item_drop": [
            ("lingzhi_pian",  0.20),
            ("huti_lingfu",   0.20),
            ("tieling_pei",   0.12),
            ("zhujidan",      0.06),
        ],
    },
    {
        "id": "spirit_vortex",
        "name": "灵气漩涡",
        "desc": "天地间突然形成一处灵气漩涡，你恰好处于中心，被动吸收了大量灵气，修为暴涨！",
        "item_drop": [],
    },
    {
        "id": "curse_mark",
        "name": "诅咒侵蚀",
        "desc": "不知何时，你身上附着了一道古老诅咒，它悄然蚕食你的修为，等你察觉时已损失惨重。",
        "item_drop": [
            ("lingzhi_pian",  0.40),
            ("huichun_dan",   0.45),
            ("huixue_ling",   0.15),
        ],
    },
    {
        "id": "elder_guidance",
        "name": "前辈指点",
        "desc": "一位云游的老修士路过，见你根骨不错，随口点拨了几句，令你茅塞顿开，修为精进。",
        "item_drop": [
            ("lingzhi_pian",  0.20),
            ("huti_lingfu",   0.20),
            ("tieling_pei",   0.12),
            ("zhujidan",      0.08),
            ("judao_jie",     0.05),
        ],
    },
]


def get_weighted_event() -> dict:
    """
    随机选取修行事件。
    权重/数值范围优先从 config.cultivation_events 读取，fallback 到 DEFAULT_GAME_CONFIG。
    返回已解析的 event dict，含 exp_min/max（经验绝对值）、hp_change_pct（已随机取值）、item_drop_rate/max。
    """
    import random
    cfg = get_game_config()
    ev_cfgs = cfg.get("cultivation_events") or {}
    default_ev_cfgs = DEFAULT_GAME_CONFIG["cultivation_events"]

    # 合并权重
    weighted = []
    for event in CULTIVATION_EVENTS:
        eid = event["id"]
        ecfg = {**default_ev_cfgs.get(eid, {}), **ev_cfgs.get(eid, {})}
        w = ecfg.get("weight", 10)
        weighted.append((event, w, ecfg))

    total = sum(w for _, w, _ in weighted)
    r = random.uniform(0, total)
    cumulative = 0.0
    chosen_event, chosen_ecfg = weighted[0][0], weighted[0][2]
    for event, w, ecfg in weighted:
        cumulative += w
        if r <= cumulative:
            chosen_event, chosen_ecfg = event, ecfg
            break

    result = dict(chosen_event)
    # 经验绝对值范围（由 cultivation.py 直接 randint 取值）
    result["exp_min"] = int(chosen_ecfg.get("exp_min", 50))
    result["exp_max"] = int(chosen_ecfg.get("exp_max", 200))
    # HP 变化绝对值（已随机取值）
    hp_min = int(chosen_ecfg.get("hp_change_min", 0))
    hp_max = int(chosen_ecfg.get("hp_change_max", 0))
    result["hp_change_pct"] = random.randint(min(hp_min, hp_max), max(hp_min, hp_max))
    # 物品掉落控制
    result["item_drop_rate"] = int(chosen_ecfg.get("item_drop_rate", 0))
    result["item_drop_max"]  = int(chosen_ecfg.get("item_drop_max", 1))
    return result


# ─────────────────────────── 稀有度显示 ──────────────────────────────────────

RARITY_DISPLAY = {
    "common":    "⚪ 普通",
    "uncommon":  "🟢 优良",
    "rare":      "🔵 稀有",
    "epic":      "🟣 史诗",
    "legendary": "🟡 传说",
}


def get_rarity_display(rarity: str) -> str:
    return RARITY_DISPLAY.get(rarity, "⚪ 普通")


# ─────────────────────────── 数据库种子函数 ──────────────────────────────────

def seed_game_data():
    """已禁用自动补全，所有数据请通过管理后台手动配置"""
    pass


# ─────────────────────────── 游戏配置读取 ────────────────────────────────────

_game_config_cache = None


def get_game_config() -> dict:
    """
    读取游戏配置，优先从 config.json 的 game 字段读取，fallback 到默认值
    """
    global _game_config_cache
    if _game_config_cache is not None:
        return _game_config_cache

    try:
        from bot import config
        game_cfg = getattr(config, 'game', None)
        if game_cfg and isinstance(game_cfg, dict):
            merged = DEFAULT_GAME_CONFIG.copy()
            merged.update(game_cfg)
            _game_config_cache = merged
            return _game_config_cache
    except Exception:
        pass
    _game_config_cache = DEFAULT_GAME_CONFIG.copy()
    return _game_config_cache


def reload_game_config():
    """清除缓存，强制下次重新读取"""
    global _game_config_cache
    _game_config_cache = None


# ─────────────────────────── 游戏回调限流 ────────────────────────────────────
# {user_id: [timestamp, ...]}  滑动窗口，只保留最近1秒内的时间戳
import time as _time
_rate_window: dict = {}

def game_rate_limit_check(user_id: int) -> bool:
    """
    检查用户是否超过游戏回调频率限制。
    :return: True=允许通过，False=被限流
    """
    cfg = get_game_config()
    limit = cfg.get("callback_rate_limit", 3)
    now = _time.monotonic()
    window = _rate_window.get(user_id, [])
    # 只保留1秒内的记录
    window = [t for t in window if now - t < 1.0]
    if len(window) >= limit:
        _rate_window[user_id] = window
        return False
    window.append(now)
    _rate_window[user_id] = window
    return True
