"""
修仙游戏数据库模型
表：game_player / game_inventory / game_raid / game_raid_participant /
    game_raid_log / game_boss_config / game_item_config / game_loot_entry /
    game_realm_config
"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from bot.sql_helper import Base, Session, engine
from sqlalchemy import (
    Column, BigInteger, String, DateTime, Integer, Text,
    Boolean, Float, UniqueConstraint, text, inspect
)
from sqlalchemy import text as sa_text
from bot import LOGGER


# ─────────────────────────────── ORM 模型 ─────────────────────────────────────

class GamePlayer(Base):
    """玩家游戏档案"""
    __tablename__ = 'game_player'

    tg = Column(BigInteger, primary_key=True, autoincrement=False)
    realm = Column(Integer, default=0)        # 境界索引 (0=肉体凡胎)
    exp = Column(Integer, default=0)          # 当前经验
    hp = Column(Integer, default=50)          # 当前血量（由境界0决定）
    max_hp = Column(Integer, default=50)      # 最大血量
    attack = Column(Integer, default=5)       # 基础攻击（由境界0决定）
    defense = Column(Integer, default=3)      # 基础防御（由境界0决定）
    stamina = Column(Integer, default=100)    # 当前体力值
    stamina_at = Column(DateTime, nullable=True)  # 上次消耗体力时间（动态计算恢复）
    break_pill_bonus = Column(Integer, default=0)  # 当前叠加的突破成功率加成（%）
    break_fail_streak = Column(Integer, default=0) # 连续突破失败次数（用于递增成功率加成）
    break_cooldown_at = Column(DateTime, nullable=True)  # 突破冷却到期时间（成功7天/失败24小时）
    is_dead = Column(Boolean, default=False)  # 是否死亡状态
    dead_at = Column(DateTime, nullable=True) # 死亡时间（用于自动复活计时）
    death_exp_lost = Column(Integer, default=0, nullable=True)    # 本次死亡扣除的修为
    death_dropped_item = Column(String(100), nullable=True)       # 本次死亡掉落的道具名（可空）
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class GameInventory(Base):
    """背包（物品库存）"""
    __tablename__ = 'game_inventory'
    __table_args__ = (UniqueConstraint('tg', 'item_id', 'equipped', name='uq_inv_tg_item_equipped'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg = Column(BigInteger, nullable=False, index=True)
    item_id = Column(String(50), nullable=False)
    quantity = Column(Integer, default=1)
    equipped = Column(Boolean, default=False)  # 是否装备中
    created_at = Column(DateTime, default=datetime.now)


class GameRaid(Base):
    """团本战斗实例"""
    __tablename__ = 'game_raid'

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(String(50), nullable=False)     # 对应 game_boss_config.boss_id
    chat_id = Column(BigInteger, nullable=False)     # 发起的群聊 ID
    message_id = Column(Integer, nullable=True)      # 当前战斗状态消息 ID（用于编辑）
    status = Column(String(20), default='recruiting')  # recruiting/active/completed/cooldown/failed
    round_num = Column(Integer, default=0)           # 当前回合数
    cur_player_idx = Column(Integer, default=0)      # 当前行动玩家的序号
    turn_started_at = Column(DateTime, nullable=True) # 当前回合开始时间（用于超时检测）
    boss_hp = Column(Integer, nullable=False)
    boss_max_hp = Column(Integer, nullable=False)
    boss_shield = Column(Integer, default=0)
    boss_next_action = Column(String(20), default='attack')  # 预告动作
    last_action_text = Column(Text, nullable=True)   # 上一个行动描述（显示在战斗状态消息中）
    loot_json = Column(Text, nullable=True)          # 结算掉落记录（JSON）
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    next_spawn_at = Column(DateTime, nullable=True)  # CD 结束时间
    created_at = Column(DateTime, default=datetime.now)


class GameRaidParticipant(Base):
    """团本参与者"""
    __tablename__ = 'game_raid_participant'

    id = Column(Integer, primary_key=True, autoincrement=True)
    raid_id = Column(Integer, nullable=False, index=True)
    tg = Column(BigInteger, nullable=False, index=True)
    join_order = Column(Integer, default=0)          # 行动顺序
    hp = Column(Integer, nullable=False)
    max_hp = Column(Integer, nullable=False)
    shield = Column(Integer, default=0)
    is_alive = Column(Boolean, default=True)
    damage_dealt = Column(Integer, default=0)        # 总输出伤害（DPS）
    heal_done = Column(Integer, default=0)           # 总治疗量
    turn_done = Column(Boolean, default=False)       # 本回合是否已行动
    timeout_count = Column(Integer, default=0)       # 本场超时次数（累计，自动逃跑判断）



class GameBossConfig(Base):
    """BOSS 配置表（Admin 可热更新）"""
    __tablename__ = 'game_boss_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    recommend_realm = Column(Integer, default=0)      # 推荐境界索引
    hp = Column(Integer, nullable=False)
    shield = Column(Integer, default=0)
    atk_min = Column(Integer, nullable=False)
    atk_max = Column(Integer, nullable=False)
    defend_reduce = Column(Float, default=0.5)        # 防御时伤害减免比
    cd_hours = Column(Integer, default=6)             # 击杀后 CD（小时）
    boss_loot_id = Column(String(50), nullable=True)  # 极品掉落物品 ID（已弃用）
    boss_loot_rate = Column(Float, default=0.02)      # 极品掉落概率（已弃用）
    min_players = Column(Integer, default=2)          # 团本最少人数
    max_players = Column(Integer, default=4)          # 团本最多人数
    # BOSS 行动概率（整数权重，合计应=100）
    action_w_attack = Column(Integer, default=55)     # 普通攻击
    action_w_double = Column(Integer, default=15)     # 连斩
    action_w_defend = Column(Integer, default=15)     # 防御
    action_w_heal   = Column(Integer, default=15)     # 恢复
    # BOSS 防御/恢复数值范围
    def_min = Column(Integer, default=10)             # 防御最小护盾值
    def_max = Column(Integer, default=30)             # 防御最大护盾值
    heal_min = Column(Integer, default=20)            # 恢复最小血量
    heal_max = Column(Integer, default=60)            # 恢复最大血量
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class GameItemConfig(Base):
    """物品配置表（Admin 可热更新）"""
    __tablename__ = 'game_item_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    item_type = Column(String(20), nullable=False)    # potion/breakthrough/equipment/stamina
    # 消耗品属性
    heal_min = Column(Integer, default=0)
    heal_max = Column(Integer, default=0)
    shield_min = Column(Integer, default=0)
    shield_max = Column(Integer, default=0)
    # 装备属性
    slot = Column(String(20), nullable=True)          # weapon/armor/accessory
    atk_bonus = Column(Integer, default=0)
    def_bonus = Column(Integer, default=0)
    hp_bonus = Column(Integer, default=0)
    # 突破丹药属性
    realm_req_min = Column(Integer, default=0)        # 适用境界范围最小值
    realm_req_max = Column(Integer, default=100)      # 适用境界范围最大值
    break_boost = Column(Integer, default=0)          # 突破成功率加成（%）
    # 元数据
    usable_in_bag = Column(Boolean, default=False)    # 是否可在背包中直接使用
    rarity = Column(String(20), default='common')     # common/rare/epic/legendary
    description = Column(Text, nullable=True)         # 物品描述（商城/背包展示用）
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class GameLootEntry(Base):
    """掉落表（BOSS 普通掉落）"""
    __tablename__ = 'game_loot_entry'

    id = Column(Integer, primary_key=True, autoincrement=True)
    boss_id = Column(String(50), nullable=False, index=True)
    item_id = Column(String(50), nullable=False)
    drop_rate = Column(Float, nullable=False)         # 掉落概率 0.0~1.0
    max_per_kill = Column(Integer, default=1)         # 每次击杀最多掉落数量


class GameShopEntry(Base):
    """游戏商城条目（Admin 可增删改查）"""
    __tablename__ = 'game_shop_entry'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(String(50), unique=True, nullable=False)   # 唯一标识（自动数字）
    name = Column(String(100), nullable=True)                    # 商品显示名称（自动取物品名）
    item_type = Column(String(20), nullable=False)               # "stamina" / "item"
    item_id = Column(String(50), nullable=True)                  # item_type="item" 时对应物品 ID
    min_qty = Column(Integer, default=1)                         # 起购数量
    max_qty = Column(Integer, default=1)                         # 单次购买数量上限
    qty_step = Column(Integer, default=1)                        # 每次 +/- 幅度
    price_stones = Column(Integer, nullable=False)               # 石子价格（单件）
    sort_order = Column(Integer, default=0)                      # 显示排序（升序）
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class GameRealmConfig(Base):
    """境界配置表（Admin 可热更新）"""
    __tablename__ = 'game_realm_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    realm_idx = Column(Integer, unique=True, nullable=False)   # 境界索引
    name = Column(String(50), nullable=False)                   # 显示名
    major_realm = Column(String(20), nullable=True)             # 大境界（练气/筑基/…）
    max_exp = Column(Integer, default=0)                        # 升至下一境界所需修为（0=顶级）
    base_max_hp = Column(Integer, default=80)
    base_attack = Column(Integer, default=8)
    base_defense = Column(Integer, default=5)
    enabled = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class GameMajorRealmConfig(Base):
    """大境界配置表：每个大境界设置基础值+步长，自动计算各子境界属性"""
    __tablename__ = 'game_major_realm_config'

    id = Column(Integer, primary_key=True, autoincrement=True)
    major_realm = Column(String(50), unique=True, nullable=False)  # 大境界名，如"练气","DP巅峰"
    min_idx = Column(Integer, default=0)           # 该大境界第一层的 realm_idx
    layer_count = Column(Integer, default=10)      # 层数（有限境界）；is_infinite=True 时忽略
    is_infinite = Column(Boolean, default=False)   # True = DP巅峰类无上限境界
    # 有限境界：基础值（第0层/第1层）+ 步长（每升一层增加的数值）
    # 无限境界：基础值（第1重）+ 步长（每突破一次增加的数值）= 属性增量
    base_max_exp = Column(BigInteger, default=0)   # 第1层修为上限；无限境界每重的修为上限
    step_max_exp = Column(BigInteger, default=0)   # 每层修为上限增量（无限境界=每重额外增量）
    base_max_hp = Column(Integer, default=80)
    step_max_hp = Column(Integer, default=10)      # 每层/每突破 HP 增量
    base_attack = Column(Integer, default=8)
    step_attack = Column(Integer, default=1)
    base_defense = Column(Integer, default=5)
    step_defense = Column(Integer, default=1)
    sort_order = Column(Integer, default=0)
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # 前置任务：击败指定 BOSS 才可突破到此大境界
    prereq_enabled = Column(Boolean, default=False)  # 是否开启前置任务
    prereq_boss_id = Column(String(100), nullable=True)  # 前置 BOSS ID


class GamePlayerBossKill(Base):
    """玩家 BOSS 击杀记录（用于前置任务校验）"""
    __tablename__ = 'game_player_boss_kills'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg = Column(BigInteger, nullable=False, index=True)
    boss_id = Column(String(100), nullable=False, index=True)
    kill_count = Column(Integer, default=1)
    last_kill_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint('tg', 'boss_id'),)


# ─────────────────────────── 创建表 ───────────────────────────────────────────

for _model in [GamePlayer, GameInventory, GameRaid, GameRaidParticipant,
               GameBossConfig, GameItemConfig, GameLootEntry, GameShopEntry,
               GameRealmConfig, GameMajorRealmConfig, GamePlayerBossKill]:
    _model.__table__.create(bind=engine, checkfirst=True)


def _migrate_game_v2():
    """自动迁移：为已存在的表新增字段（幂等）"""
    try:
        from sqlalchemy import inspect, text as sa_text
        insp = inspect(engine)
        # game_raid: last_action_text
        raid_cols = [c['name'] for c in insp.get_columns('game_raid')]
        if 'last_action_text' not in raid_cols:
            with engine.connect() as conn:
                conn.execute(sa_text(
                    "ALTER TABLE game_raid ADD COLUMN last_action_text TEXT DEFAULT NULL"
                ))
                conn.commit()
            LOGGER.info("【游戏迁移】game_raid.last_action_text 已添加")
        # game_raid_participant: timeout_count
        part_cols = [c['name'] for c in insp.get_columns('game_raid_participant')]
        if 'timeout_count' not in part_cols:
            with engine.connect() as conn:
                conn.execute(sa_text(
                    "ALTER TABLE game_raid_participant ADD COLUMN timeout_count INT DEFAULT 0"
                ))
                conn.commit()
            LOGGER.info("【游戏迁移】game_raid_participant.timeout_count 已添加")
        # game_item_config: usable_in_bag
        item_cols = [c['name'] for c in insp.get_columns('game_item_config')]
        if 'usable_in_bag' not in item_cols:
            with engine.connect() as conn:
                conn.execute(sa_text(
                    "ALTER TABLE game_item_config ADD COLUMN usable_in_bag BOOLEAN DEFAULT FALSE"
                ))
                conn.commit()
            LOGGER.info("【游戏迁移】game_item_config.usable_in_bag 已添加")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v2】{_e}")


_migrate_game_v2()


def _migrate_game_v3():
    """自动迁移 v3：为 game_player 添加 is_dead / dead_at 字段（幂等）"""
    try:
        insp = inspect(engine)
        player_cols = [c['name'] for c in insp.get_columns('game_player')]
        with engine.connect() as conn:
            if 'is_dead' not in player_cols:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN is_dead BOOLEAN DEFAULT FALSE"))
                conn.commit()
                LOGGER.info("【游戏迁移 v3】game_player.is_dead 已添加")
            if 'dead_at' not in player_cols:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN dead_at DATETIME DEFAULT NULL"))
                conn.commit()
                LOGGER.info("【游戏迁移 v3】game_player.dead_at 已添加")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v3】{_e}")


_migrate_game_v3()


def _migrate_game_v4():
    """自动迁移 v4：为 game_boss_config 添加 min_players / max_players 字段（幂等）"""
    try:
        insp = inspect(engine)
        boss_cols = [c['name'] for c in insp.get_columns('game_boss_config')]
        with engine.connect() as conn:
            if 'min_players' not in boss_cols:
                conn.execute(sa_text("ALTER TABLE game_boss_config ADD COLUMN min_players INT DEFAULT 2"))
                conn.commit()
                LOGGER.info("【游戏迁移 v4】game_boss_config.min_players 已添加")
            if 'max_players' not in boss_cols:
                conn.execute(sa_text("ALTER TABLE game_boss_config ADD COLUMN max_players INT DEFAULT 4"))
                conn.commit()
                LOGGER.info("【游戏迁移 v4】game_boss_config.max_players 已添加")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v4】{_e}")


_migrate_game_v4()


def _migrate_game_v5():
    """自动迁移 v5：为 game_player 添加 break_fail_streak 字段（幂等）"""
    try:
        insp = inspect(engine)
        player_cols = [c['name'] for c in insp.get_columns('game_player')]
        if 'break_fail_streak' not in player_cols:
            with engine.connect() as conn:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN break_fail_streak INT DEFAULT 0"))
                conn.commit()
            LOGGER.info("【游戏迁移 v5】game_player.break_fail_streak 已添加")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v5】{_e}")


_migrate_game_v5()


def _migrate_game_v6():
    """自动迁移 v6：game_player 添加 break_cooldown_at 字段（幂等）"""
    try:
        insp = inspect(engine)
        player_cols = [c['name'] for c in insp.get_columns('game_player')]
        if 'break_cooldown_at' not in player_cols:
            with engine.connect() as conn:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN break_cooldown_at DATETIME DEFAULT NULL"))
                conn.commit()
            LOGGER.info("【游戏迁移 v6】game_player.break_cooldown_at 已添加")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v6】{_e}")


_migrate_game_v6()


def _migrate_game_v7():
    """
    自动迁移 v7：添加肉体凡胎初始境界(realm_idx=0)
    - 所有现有境界索引 +1（避免与新增的0冲突）
    - 所有玩家 realm +1（原练气一层玩家变为新索引1）
    - 同步更新 BOSS 推荐境界 + 突破丹药境界范围
    """
    try:
        with engine.connect() as conn:
            # 检测是否已迁移（肉体凡胎是否已存在）
            result = conn.execute(sa_text(
                "SELECT COUNT(*) FROM game_realm_config WHERE name='肉体凡胎'"
            ))
            if result.scalar() > 0:
                return  # 已迁移，跳过
        LOGGER.info("【游戏迁移 v7】开始添加肉体凡胎境界...")
        with engine.connect() as conn:
            # 1. 所有境界索引 +1（降序更新，避免唯一约束冲突）
            try:
                conn.execute(sa_text(
                    "UPDATE game_realm_config "
                    "SET realm_idx = realm_idx + 1, sort_order = sort_order + 1 "
                    "ORDER BY realm_idx DESC"
                ))
            except Exception:
                pass  # 表可能为空（全新安装），跳过
            # 2. 所有玩家境界 +1
            try:
                conn.execute(sa_text("UPDATE game_player SET realm = realm + 1"))
            except Exception:
                pass
            # 3. BOSS 推荐境界 +1
            try:
                conn.execute(sa_text(
                    "UPDATE game_boss_config SET recommend_realm = recommend_realm + 1"
                ))
            except Exception:
                pass
            # 4. 突破丹药适用境界范围 +1
            try:
                conn.execute(sa_text(
                    "UPDATE game_item_config "
                    "SET realm_req_min = realm_req_min + 1, realm_req_max = realm_req_max + 1 "
                    "WHERE item_type = 'breakthrough'"
                ))
            except Exception:
                pass
            conn.commit()
        # 5. 插入肉体凡胎境界配置
        sql_upsert_realm(0,
            name='肉体凡胎', major_realm='肉体凡胎',
            max_exp=50, base_max_hp=50, base_attack=5, base_defense=3,
            sort_order=0, enabled=True
        )
        LOGGER.info("【游戏迁移 v7】肉体凡胎已添加，所有境界/玩家/BOSS/丹药境界引用均已 +1")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v7】{_e}")


_migrate_game_v7()


def _migrate_game_v8():
    """v8: GameShopEntry.quantity → max_qty（单次购买数量上限）"""
    try:
        with engine.connect() as conn:
            cols = [r[0] for r in conn.execute(sa_text("SHOW COLUMNS FROM game_shop_entry")).fetchall()]
            if 'max_qty' in cols:
                return
            if 'quantity' in cols:
                conn.execute(sa_text("ALTER TABLE game_shop_entry CHANGE COLUMN `quantity` `max_qty` INT DEFAULT 1"))
            else:
                conn.execute(sa_text("ALTER TABLE game_shop_entry ADD COLUMN `max_qty` INT NOT NULL DEFAULT 1"))
            conn.commit()
        LOGGER.info("【游戏迁移 v8】game_shop_entry.quantity → max_qty")
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v8】跳过: {ex}")


_migrate_game_v8()


def _migrate_game_v9():
    """v9: GameItemConfig 增加 description；GameShopEntry 增加 min_qty/qty_step，name 改可空"""
    try:
        with engine.connect() as conn:
            item_cols = [r[0] for r in conn.execute(sa_text("SHOW COLUMNS FROM game_item_config")).fetchall()]
            if 'description' not in item_cols:
                conn.execute(sa_text("ALTER TABLE game_item_config ADD COLUMN `description` TEXT"))
                LOGGER.info("【游戏迁移 v9】game_item_config 新增 description")

            shop_cols = [r[0] for r in conn.execute(sa_text("SHOW COLUMNS FROM game_shop_entry")).fetchall()]
            if 'min_qty' not in shop_cols:
                conn.execute(sa_text("ALTER TABLE game_shop_entry ADD COLUMN `min_qty` INT NOT NULL DEFAULT 1"))
                LOGGER.info("【游戏迁移 v9】game_shop_entry 新增 min_qty")
            if 'qty_step' not in shop_cols:
                conn.execute(sa_text("ALTER TABLE game_shop_entry ADD COLUMN `qty_step` INT NOT NULL DEFAULT 1"))
                LOGGER.info("【游戏迁移 v9】game_shop_entry 新增 qty_step")
            conn.execute(sa_text("ALTER TABLE game_shop_entry MODIFY COLUMN `name` VARCHAR(100) NULL"))
            conn.commit()
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v9】跳过: {ex}")


_migrate_game_v9()


def _migrate_game_v10():
    """
    v10: 境界体系扩展至每大境界10层子境界（共91个境界，索引0-90）
    - 旧索引(0-25) → 新索引(0-90) 映射
    - 更新玩家 realm 字段
    - 更新 BOSS recommend_realm
    - 更新突破丹药 realm_req_min/realm_req_max
    - 清空旧境界配置（seed_game_data 会重新补充）
    """
    # 旧索引 → 新索引映射
    _OLD_TO_NEW = {
        0: 0,   # 肉体凡胎
        1: 1,   2: 2,   3: 3,   4: 4,   5: 5,
        6: 6,   7: 7,   8: 8,   9: 9,   # 练气1-9 不变
        10: 11,  # 筑基初期 → 筑基一层
        11: 14,  # 筑基中期 → 筑基四层
        12: 18,  # 筑基后期 → 筑基八层
        13: 21,  # 金丹初期 → 金丹一层
        14: 24,  # 金丹中期 → 金丹四层
        15: 28,  # 金丹后期 → 金丹八层
        16: 31,  # 元婴初期 → 元婴一层
        17: 34,  # 元婴中期 → 元婴四层
        18: 38,  # 元婴后期 → 元婴八层
        19: 41,  # 化神初期 → 化神一层
        20: 44,  # 化神中期 → 化神四层
        21: 48,  # 化神后期 → 化神八层
        22: 51,  # 炼虚期 → 炼虚一层
        23: 61,  # 合体期 → 合体一层
        24: 71,  # 大乘期 → 大乘一层
        25: 81,  # 渡劫期 → 渡劫一层
    }
    # 突破丹药 旧范围 → 新范围映射
    _PILL_RANGE_MAP = [
        # (old_rmin, old_rmax, new_rmin, new_rmax)
        (1,  9,  1,  10),   # 筑基丹
        (10, 12, 11, 20),   # 金丹道果
        (13, 15, 21, 30),   # 元婴真珠
        (16, 18, 31, 40),   # 化神灵丹
        (19, 21, 41, 50),   # 炼真灵气
        (22, 24, 71, 80),   # 大乘灵石（旧：炼虚+合体+大乘 → 仅大乘期）
    ]
    try:
        with engine.connect() as conn:
            # 检测是否已完成 v10 迁移（检查是否存在 realm_idx=10 且名称含"练气"）
            res = conn.execute(sa_text(
                "SELECT COUNT(*) FROM game_realm_config "
                "WHERE realm_idx=10 AND name LIKE '%练气%'"
            ))
            if res.scalar() > 0:
                return  # 已迁移，跳过
        LOGGER.info("【游戏迁移 v10】开始扩展境界体系为每大境界10层...")
        with engine.connect() as conn:
            # 1. 重映射玩家 realm（旧→新）
            for old_idx, new_idx in sorted(_OLD_TO_NEW.items(), reverse=True):
                if old_idx == new_idx:
                    continue
                conn.execute(sa_text(
                    f"UPDATE game_player SET realm={new_idx} WHERE realm={old_idx}"
                ))
            # 2. 重映射 BOSS recommend_realm（旧→新，降序避免冲突）
            for old_idx, new_idx in sorted(_OLD_TO_NEW.items(), reverse=True):
                if old_idx == new_idx:
                    continue
                conn.execute(sa_text(
                    f"UPDATE game_boss_config SET recommend_realm={new_idx} "
                    f"WHERE recommend_realm={old_idx}"
                ))
            # 3. 更新突破丹药 realm_req 范围
            for old_rmin, old_rmax, new_rmin, new_rmax in _PILL_RANGE_MAP:
                conn.execute(sa_text(
                    f"UPDATE game_item_config "
                    f"SET realm_req_min={new_rmin}, realm_req_max={new_rmax} "
                    f"WHERE item_type='breakthrough' "
                    f"AND realm_req_min={old_rmin} AND realm_req_max={old_rmax}"
                ))
            # 4. 清空旧境界配置（seed_game_data 启动时会重新补充新结构）
            conn.execute(sa_text("DELETE FROM game_realm_config"))
            conn.commit()
        try:
            from bot.modules.game.game_data import reload_realm_cache
            reload_realm_cache()
        except Exception:
            pass
        LOGGER.info("【游戏迁移 v10】完成：玩家/BOSS/丹药境界已重映射，旧境界配置已清空，等待重新种子")
    except Exception as _e:
        LOGGER.warning(f"【游戏迁移 v10】{_e}")


_migrate_game_v10()


def _migrate_game_v11():
    """v11: game_player 新增 death_exp_lost / death_dropped_item（幂等）"""
    try:
        with engine.connect() as conn:
            cols = [r[0] for r in conn.execute(sa_text("SHOW COLUMNS FROM game_player")).fetchall()]
            if 'death_exp_lost' not in cols:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN `death_exp_lost` INT DEFAULT 0"))
                LOGGER.info("【游戏迁移 v11】game_player 新增 death_exp_lost")
            if 'death_dropped_item' not in cols:
                conn.execute(sa_text("ALTER TABLE game_player ADD COLUMN `death_dropped_item` VARCHAR(100) DEFAULT NULL"))
                LOGGER.info("【游戏迁移 v11】game_player 新增 death_dropped_item")
            conn.commit()
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v11】跳过: {ex}")


_migrate_game_v11()


def sql_get_game_player(tg: int) -> Optional[GamePlayer]:
    with Session() as session:
        return session.query(GamePlayer).filter(GamePlayer.tg == tg).first()


def sql_get_or_create_player(tg: int) -> GamePlayer:
    """获取或初始化玩家档案（首次游戏自动创建，属性取自境界0配置）"""
    with Session() as session:
        p = session.query(GamePlayer).filter(GamePlayer.tg == tg).first()
        if p:
            return p
        # 从境界 0（肉体凡胎）读取初始属性
        init_hp, init_atk, init_def = 50, 5, 3
        try:
            from bot.modules.game.game_data import get_realm
            r = get_realm(0)
            init_hp, init_atk, init_def = r[3], r[4], r[5]
        except Exception:
            pass
        p = GamePlayer(tg=tg, hp=init_hp, max_hp=init_hp, attack=init_atk, defense=init_def, realm=0)
        session.add(p)
        session.commit()
        session.refresh(p)
        return p


def sql_update_game_player(tg: int, **kwargs) -> bool:
    with Session() as session:
        try:
            session.query(GamePlayer).filter(GamePlayer.tg == tg).update(kwargs)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】更新玩家数据失败 tg={tg}: {e}")
            session.rollback()
            return False


def sql_get_realm_ranking(limit: int = 20) -> List[GamePlayer]:
    """获取修为排行榜"""
    with Session() as session:
        return session.query(GamePlayer).order_by(
            GamePlayer.realm.desc(),
            GamePlayer.exp.desc()
        ).limit(limit).all()


# ─────────────────────────── GameInventory CRUD ───────────────────────────────

def sql_get_inventory(tg: int) -> List[GameInventory]:
    with Session() as session:
        return session.query(GameInventory).filter(GameInventory.tg == tg).all()


def sql_get_inventory_item(tg: int, item_id: str, equipped: bool = False) -> Optional[GameInventory]:
    with Session() as session:
        return session.query(GameInventory).filter(
            GameInventory.tg == tg,
            GameInventory.item_id == item_id,
            GameInventory.equipped == equipped
        ).first()


def sql_add_item(tg: int, item_id: str, quantity: int = 1) -> bool:
    """背包增加物品，已有则叠加数量"""
    with Session() as session:
        try:
            inv = session.query(GameInventory).filter(
                GameInventory.tg == tg,
                GameInventory.item_id == item_id,
                GameInventory.equipped == False
            ).first()
            if inv:
                inv.quantity += quantity
            else:
                inv = GameInventory(tg=tg, item_id=item_id, quantity=quantity)
                session.add(inv)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】添加物品失败 tg={tg} item={item_id}: {e}")
            session.rollback()
            return False


def sql_use_item(tg: int, item_id: str, quantity: int = 1) -> bool:
    """消耗背包物品，不足时返回 False"""
    with Session() as session:
        try:
            inv = session.query(GameInventory).filter(
                GameInventory.tg == tg,
                GameInventory.item_id == item_id,
                GameInventory.equipped == False
            ).with_for_update().first()
            if not inv or inv.quantity < quantity:
                return False
            inv.quantity -= quantity
            if inv.quantity == 0:
                session.delete(inv)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】消耗物品失败 tg={tg} item={item_id}: {e}")
            session.rollback()
            return False


def sql_equip_item(tg: int, item_id: str) -> bool:
    """装备道具（从背包取出到装备槽）"""
    with Session() as session:
        try:
            inv = session.query(GameInventory).filter(
                GameInventory.tg == tg,
                GameInventory.item_id == item_id,
                GameInventory.equipped == False
            ).with_for_update().first()
            if not inv or inv.quantity < 1:
                return False
            inv.quantity -= 1
            if inv.quantity == 0:
                session.delete(inv)
            equipped = GameInventory(tg=tg, item_id=item_id, quantity=1, equipped=True)
            session.add(equipped)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】装备物品失败: {e}")
            session.rollback()
            return False


def sql_unequip_item(tg: int, item_id: str) -> bool:
    """卸下装备（放回背包）"""
    with Session() as session:
        try:
            equipped = session.query(GameInventory).filter(
                GameInventory.tg == tg,
                GameInventory.item_id == item_id,
                GameInventory.equipped == True
            ).with_for_update().first()
            if not equipped:
                return False
            session.delete(equipped)
            sql_add_item(tg, item_id, 1)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】卸下装备失败: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameBossConfig CRUD ─────────────────────────────

def sql_get_boss(boss_id: str) -> Optional[GameBossConfig]:
    with Session() as session:
        return session.query(GameBossConfig).filter(
            GameBossConfig.boss_id == boss_id,
            GameBossConfig.enabled == True
        ).first()


def sql_get_all_bosses(include_disabled: bool = False) -> List[GameBossConfig]:
    with Session() as session:
        q = session.query(GameBossConfig)
        if not include_disabled:
            q = q.filter(GameBossConfig.enabled == True)
        return q.order_by(GameBossConfig.recommend_realm).all()


def sql_upsert_boss(boss_id: str, **kwargs) -> bool:
    """插入或更新 BOSS 配置"""
    with Session() as session:
        try:
            boss = session.query(GameBossConfig).filter(
                GameBossConfig.boss_id == boss_id
            ).first()
            if boss:
                for k, v in kwargs.items():
                    setattr(boss, k, v)
            else:
                boss = GameBossConfig(boss_id=boss_id, **kwargs)
                session.add(boss)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert BOSS失败 {boss_id}: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameItemConfig CRUD ─────────────────────────────

def sql_get_item_config(item_id: str) -> Optional[GameItemConfig]:
    with Session() as session:
        return session.query(GameItemConfig).filter(
            GameItemConfig.item_id == item_id,
            GameItemConfig.enabled == True
        ).first()


def sql_get_all_items(include_disabled: bool = False) -> List[GameItemConfig]:
    with Session() as session:
        q = session.query(GameItemConfig)
        if not include_disabled:
            q = q.filter(GameItemConfig.enabled == True)
        return q.all()


def sql_upsert_item(item_id: str, **kwargs) -> bool:
    """插入或更新物品配置"""
    with Session() as session:
        try:
            item = session.query(GameItemConfig).filter(
                GameItemConfig.item_id == item_id
            ).first()
            if item:
                for k, v in kwargs.items():
                    setattr(item, k, v)
            else:
                item = GameItemConfig(item_id=item_id, **kwargs)
                session.add(item)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert 物品失败 {item_id}: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameLootEntry CRUD ──────────────────────────────

def sql_get_loot_table(boss_id: str) -> List[GameLootEntry]:
    with Session() as session:
        return session.query(GameLootEntry).filter(
            GameLootEntry.boss_id == boss_id
        ).all()


def sql_upsert_loot_entry(boss_id: str, item_id: str, drop_rate: float, max_per_kill: int = 1) -> bool:
    with Session() as session:
        try:
            entry = session.query(GameLootEntry).filter(
                GameLootEntry.boss_id == boss_id,
                GameLootEntry.item_id == item_id
            ).first()
            if entry:
                entry.drop_rate = drop_rate
                entry.max_per_kill = max_per_kill
            else:
                entry = GameLootEntry(boss_id=boss_id, item_id=item_id,
                                      drop_rate=drop_rate, max_per_kill=max_per_kill)
                session.add(entry)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert 掉落表失败: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameRaid CRUD ───────────────────────────────────

def sql_create_raid(boss_id: str, chat_id: int, boss_hp: int) -> Optional[GameRaid]:
    with Session() as session:
        try:
            raid = GameRaid(
                boss_id=boss_id,
                chat_id=chat_id,
                boss_hp=boss_hp,
                boss_max_hp=boss_hp,
                status='recruiting'
            )
            session.add(raid)
            session.commit()
            session.refresh(raid)
            return raid
        except Exception as e:
            LOGGER.error(f"【游戏】创建团本失败: {e}")
            session.rollback()
            return None


def sql_get_raid(raid_id: int) -> Optional[GameRaid]:
    with Session() as session:
        return session.query(GameRaid).filter(GameRaid.id == raid_id).first()


def sql_get_active_raid_by_chat(chat_id: int, boss_id: Optional[str] = None):
    """获取群聊中正在进行的团本（recruiting 或 active 状态）"""
    with Session() as session:
        q = session.query(GameRaid).filter(
            GameRaid.chat_id == chat_id,
            GameRaid.status.in_(['recruiting', 'active'])
        )
        if boss_id:
            q = q.filter(GameRaid.boss_id == boss_id)
        return q.order_by(GameRaid.id.desc()).first()


def sql_get_boss_cooldown(boss_id: str, chat_id: int) -> Optional[GameRaid]:
    """获取该 BOSS 当前冷却中的最新记录"""
    with Session() as session:
        return session.query(GameRaid).filter(
            GameRaid.boss_id == boss_id,
            GameRaid.chat_id == chat_id,
            GameRaid.status == 'cooldown'
        ).order_by(GameRaid.id.desc()).first()


def sql_update_raid(raid_id: int, **kwargs) -> bool:
    with Session() as session:
        try:
            session.query(GameRaid).filter(GameRaid.id == raid_id).update(kwargs)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】更新团本失败 id={raid_id}: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameRaidParticipant CRUD ────────────────────────

def sql_add_participant(raid_id: int, tg: int, hp: int, max_hp: int, join_order: int) -> Optional[GameRaidParticipant]:
    with Session() as session:
        try:
            p = GameRaidParticipant(
                raid_id=raid_id, tg=tg,
                hp=hp, max_hp=max_hp,
                join_order=join_order
            )
            session.add(p)
            session.commit()
            session.refresh(p)
            return p
        except Exception as e:
            LOGGER.error(f"【游戏】添加参与者失败: {e}")
            session.rollback()
            return None


def sql_get_participants(raid_id: int) -> List[GameRaidParticipant]:
    with Session() as session:
        return session.query(GameRaidParticipant).filter(
            GameRaidParticipant.raid_id == raid_id
        ).order_by(GameRaidParticipant.join_order).all()


def sql_get_participant(raid_id: int, tg: int) -> Optional[GameRaidParticipant]:
    with Session() as session:
        return session.query(GameRaidParticipant).filter(
            GameRaidParticipant.raid_id == raid_id,
            GameRaidParticipant.tg == tg
        ).first()


def sql_update_participant(raid_id: int, tg: int, **kwargs) -> bool:
    with Session() as session:
        try:
            session.query(GameRaidParticipant).filter(
                GameRaidParticipant.raid_id == raid_id,
                GameRaidParticipant.tg == tg
            ).update(kwargs)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】更新参与者失败: {e}")
            session.rollback()
            return False




# ─────────────────────────── GameShopEntry CRUD ───────────────────────────────

def sql_get_shop_entries() -> List[GameShopEntry]:
    """获取所有已启用商城条目（按 sort_order 排序）"""
    with Session() as session:
        return session.query(GameShopEntry).filter(
            GameShopEntry.enabled == True
        ).order_by(GameShopEntry.sort_order, GameShopEntry.id).all()


def sql_get_all_shop_entries() -> List[GameShopEntry]:
    """获取所有商城条目（含禁用，Admin 用）"""
    with Session() as session:
        return session.query(GameShopEntry).order_by(
            GameShopEntry.sort_order, GameShopEntry.id
        ).all()


def sql_get_shop_entry(shop_id: str) -> Optional[GameShopEntry]:
    with Session() as session:
        return session.query(GameShopEntry).filter(
            GameShopEntry.shop_id == shop_id
        ).first()


def sql_upsert_shop_entry(shop_id: str, **kwargs) -> bool:
    """插入或更新商城条目"""
    with Session() as session:
        try:
            entry = session.query(GameShopEntry).filter(
                GameShopEntry.shop_id == shop_id
            ).first()
            if entry:
                for k, v in kwargs.items():
                    setattr(entry, k, v)
            else:
                entry = GameShopEntry(shop_id=shop_id, **kwargs)
                session.add(entry)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert 商城条目失败 {shop_id}: {e}")
            session.rollback()
            return False


def sql_delete_boss(boss_id: str) -> bool:
    """真正删除 BOSS 配置（不可恢复）"""
    with Session() as session:
        try:
            entry = session.query(GameBossConfig).filter(
                GameBossConfig.boss_id == boss_id
            ).first()
            if entry:
                session.delete(entry)
                session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】删除 BOSS 失败 {boss_id}: {e}")
            session.rollback()
            return False


def sql_delete_item(item_id: str) -> bool:
    """真正删除物品配置（不可恢复）"""
    with Session() as session:
        try:
            entry = session.query(GameItemConfig).filter(
                GameItemConfig.item_id == item_id
            ).first()
            if entry:
                session.delete(entry)
                session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】删除物品失败 {item_id}: {e}")
            session.rollback()
            return False


def sql_delete_shop_entry(shop_id: str) -> bool:
    """删除商城条目"""
    with Session() as session:
        try:
            entry = session.query(GameShopEntry).filter(
                GameShopEntry.shop_id == shop_id
            ).first()
            if entry:
                session.delete(entry)
                session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】删除商城条目失败 {shop_id}: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameRealmConfig CRUD ────────────────────────────

def sql_get_all_realms(include_disabled: bool = False) -> List[GameRealmConfig]:
    """获取所有境界配置"""
    with Session() as session:
        q = session.query(GameRealmConfig)
        if not include_disabled:
            q = q.filter(GameRealmConfig.enabled == True)
        return q.order_by(GameRealmConfig.sort_order, GameRealmConfig.realm_idx).all()


def sql_get_realm_config(realm_idx: int) -> Optional[GameRealmConfig]:
    """获取指定索引境界配置"""
    with Session() as session:
        return session.query(GameRealmConfig).filter(
            GameRealmConfig.realm_idx == realm_idx
        ).first()


def sql_upsert_realm(realm_idx: int, **kwargs) -> bool:
    """插入或更新境界配置"""
    with Session() as session:
        try:
            realm = session.query(GameRealmConfig).filter(
                GameRealmConfig.realm_idx == realm_idx
            ).first()
            if realm:
                for k, v in kwargs.items():
                    setattr(realm, k, v)
            else:
                realm = GameRealmConfig(realm_idx=realm_idx, **kwargs)
                session.add(realm)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert 境界配置失败 idx={realm_idx}: {e}")
            session.rollback()
            return False


def sql_delete_realm(realm_idx: int) -> bool:
    """删除境界配置"""
    with Session() as session:
        try:
            realm = session.query(GameRealmConfig).filter(
                GameRealmConfig.realm_idx == realm_idx
            ).first()
            if realm:
                session.delete(realm)
                session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】删除境界配置失败 idx={realm_idx}: {e}")
            session.rollback()
            return False


# ─────────────────────────── GameMajorRealmConfig CRUD ───────────────────────

def sql_get_all_major_realms(include_disabled: bool = True) -> List[GameMajorRealmConfig]:
    with Session() as session:
        q = session.query(GameMajorRealmConfig)
        if not include_disabled:
            q = q.filter(GameMajorRealmConfig.enabled == True)
        return q.order_by(GameMajorRealmConfig.sort_order, GameMajorRealmConfig.min_idx).all()


def sql_get_major_realm_config(major_realm: str) -> Optional[GameMajorRealmConfig]:
    with Session() as session:
        return session.query(GameMajorRealmConfig).filter(
            GameMajorRealmConfig.major_realm == major_realm
        ).first()


def sql_upsert_major_realm(major_realm: str, **kwargs) -> bool:
    with Session() as session:
        try:
            obj = session.query(GameMajorRealmConfig).filter(
                GameMajorRealmConfig.major_realm == major_realm
            ).first()
            if obj:
                for k, v in kwargs.items():
                    setattr(obj, k, v)
            else:
                obj = GameMajorRealmConfig(major_realm=major_realm, **kwargs)
                session.add(obj)
            session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】upsert 大境界配置失败 {major_realm}: {e}")
            session.rollback()
            return False


def sql_delete_major_realm(major_realm: str) -> bool:
    with Session() as session:
        try:
            obj = session.query(GameMajorRealmConfig).filter(
                GameMajorRealmConfig.major_realm == major_realm
            ).first()
            if obj:
                session.delete(obj)
                session.commit()
            return True
        except Exception as e:
            LOGGER.error(f"【游戏】删除大境界配置失败 {major_realm}: {e}")
            session.rollback()
            return False


def _migrate_game_v12():
    """v12: 初始化 game_major_realm_config 大境界配置（仅在表为空时写入默认值）
    注意：必须在所有 CRUD 函数定义之后调用！
    """
    try:
        with Session() as session:
            cnt = session.query(GameMajorRealmConfig).count()
            if cnt > 0:
                return
        _MAJOR_SEED = [
            dict(major_realm="肉体凡胎", min_idx=0,  layer_count=1,  is_infinite=False, sort_order=0,
                 base_max_exp=50,        step_max_exp=0,
                 base_max_hp=50,         step_max_hp=0,
                 base_attack=5,          step_attack=0,
                 base_defense=3,         step_defense=0),
            dict(major_realm="练气",     min_idx=1,  layer_count=10, is_infinite=False, sort_order=1,
                 base_max_exp=100,       step_max_exp=422,
                 base_max_hp=80,         step_max_hp=12,
                 base_attack=8,          step_attack=1,
                 base_defense=5,         step_defense=1),
            dict(major_realm="筑基",     min_idx=11, layer_count=10, is_infinite=False, sort_order=2,
                 base_max_exp=5500,      step_max_exp=1389,
                 base_max_hp=240,        step_max_hp=37,
                 base_attack=22,         step_attack=3,
                 base_defense=19,        step_defense=3),
            dict(major_realm="金丹",     min_idx=21, layer_count=10, is_infinite=False, sort_order=3,
                 base_max_exp=22000,     step_max_exp=8333,
                 base_max_hp=700,        step_max_hp=106,
                 base_attack=68,         step_attack=10,
                 base_defense=62,        step_defense=9),
            dict(major_realm="元婴",     min_idx=31, layer_count=10, is_infinite=False, sort_order=4,
                 base_max_exp=110000,    step_max_exp=42556,
                 base_max_hp=2050,       step_max_hp=309,
                 base_attack=202,        step_attack=30,
                 base_defense=190,       step_defense=29),
            dict(major_realm="化神",     min_idx=41, layer_count=10, is_infinite=False, sort_order=5,
                 base_max_exp=560000,    step_max_exp=213889,
                 base_max_hp=6000,       step_max_hp=905,
                 base_attack=530,        step_attack=80,
                 base_defense=505,       step_defense=76),
            dict(major_realm="炼虚",     min_idx=51, layer_count=10, is_infinite=False, sort_order=6,
                 base_max_exp=2800000,   step_max_exp=1066667,
                 base_max_hp=17500,      step_max_hp=2640,
                 base_attack=1500,       step_attack=227,
                 base_defense=1425,      step_defense=215),
            dict(major_realm="合体",     min_idx=61, layer_count=10, is_infinite=False, sort_order=7,
                 base_max_exp=14000000,  step_max_exp=5333333,
                 base_max_hp=51000,      step_max_hp=7695,
                 base_attack=4250,       step_attack=641,
                 base_defense=4038,      step_defense=609),
            dict(major_realm="大乘",     min_idx=71, layer_count=10, is_infinite=False, sort_order=8,
                 base_max_exp=71000000,  step_max_exp=26555556,
                 base_max_hp=145000,     step_max_hp=21878,
                 base_attack=12500,      step_attack=1886,
                 base_defense=11875,     step_defense=1792),
            dict(major_realm="渡劫",     min_idx=81, layer_count=10, is_infinite=False, sort_order=9,
                 base_max_exp=360000000, step_max_exp=123000000,
                 base_max_hp=412000,     step_max_hp=62164,
                 base_attack=35500,      step_attack=5357,
                 base_defense=33725,     step_defense=5089),
            dict(major_realm="DP巅峰",   min_idx=91, layer_count=0,  is_infinite=True,  sort_order=10,
                 base_max_exp=2000000000, step_max_exp=500000000,
                 base_max_hp=1200000,     step_max_hp=100000,
                 base_attack=95000,       step_attack=10000,
                 base_defense=90000,      step_defense=9000),
        ]
        for item in _MAJOR_SEED:
            major = item.pop("major_realm")
            sql_upsert_major_realm(major, **item)
        LOGGER.info("【游戏迁移 v12】大境界配置初始化完成（10个大境界 + DP巅峰）")
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v12】跳过: {ex}")


_migrate_game_v12()


def _migrate_game_v13():
    """v13: game_major_realm_config 新增 prereq_enabled/prereq_boss_id；
    禁用旧的4个初始 BOSS（misty_fox/demon_master/ancient_aura/heaven_guardian）"""
    try:
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        insp = sa_inspect(engine)
        # 1. 新增前置任务字段
        mc_cols = [c['name'] for c in insp.get_columns('game_major_realm_config')]
        with engine.connect() as conn:
            if 'prereq_enabled' not in mc_cols:
                conn.execute(sa_text(
                    "ALTER TABLE game_major_realm_config ADD COLUMN prereq_enabled BOOLEAN DEFAULT 0"
                ))
                LOGGER.info("【游戏迁移 v13】game_major_realm_config.prereq_enabled 已添加")
            if 'prereq_boss_id' not in mc_cols:
                conn.execute(sa_text(
                    "ALTER TABLE game_major_realm_config ADD COLUMN prereq_boss_id VARCHAR(100) DEFAULT NULL"
                ))
                LOGGER.info("【游戏迁移 v13】game_major_realm_config.prereq_boss_id 已添加")
            conn.commit()
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v13】跳过: {ex}")


_migrate_game_v13()


def _migrate_game_v14():
    """v14: game_boss_config 新增4个行动权重字段"""
    try:
        insp = inspect(engine)
        boss_cols = [c['name'] for c in insp.get_columns('game_boss_config')]
        with engine.connect() as conn:
            for col, default in [
                ('action_w_attack', 55),
                ('action_w_double', 15),
                ('action_w_defend', 15),
                ('action_w_heal',   15),
            ]:
                if col not in boss_cols:
                    conn.execute(sa_text(
                        f"ALTER TABLE game_boss_config ADD COLUMN {col} INT DEFAULT {default}"
                    ))
                    LOGGER.info(f"【游戏迁移 v14】game_boss_config.{col} 已添加")
            conn.commit()
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v14】跳过: {ex}")


_migrate_game_v14()


def _migrate_game_v15():
    """v15: game_boss_config 新增 def_min/def_max/heal_min/heal_max 字段"""
    try:
        insp = inspect(engine)
        boss_cols = [c['name'] for c in insp.get_columns('game_boss_config')]
        with engine.connect() as conn:
            for col, default in [
                ('def_min',  10),
                ('def_max',  30),
                ('heal_min', 20),
                ('heal_max', 60),
            ]:
                if col not in boss_cols:
                    conn.execute(sa_text(
                        f"ALTER TABLE game_boss_config ADD COLUMN {col} INT DEFAULT {default}"
                    ))
                    LOGGER.info(f"【游戏迁移 v15】game_boss_config.{col} 已添加")
            conn.commit()
    except Exception as ex:
        LOGGER.warning(f"【游戏迁移 v15】跳过: {ex}")


_migrate_game_v15()


# ─────────────────────────── BOSS 击杀 CRUD ───────────────────────────────────

def sql_record_boss_kill(tg: int, boss_id: str) -> bool:
    """记录玩家击杀 BOSS（如已存在则累加 kill_count）"""
    with Session() as session:
        try:
            obj = session.query(GamePlayerBossKill).filter(
                GamePlayerBossKill.tg == tg,
                GamePlayerBossKill.boss_id == boss_id
            ).first()
            if obj:
                obj.kill_count = (obj.kill_count or 0) + 1
                obj.last_kill_at = datetime.now()
            else:
                obj = GamePlayerBossKill(tg=tg, boss_id=boss_id, kill_count=1,
                                         last_kill_at=datetime.now())
                session.add(obj)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            LOGGER.error(f"【游戏】记录 BOSS 击杀失败 tg={tg} boss={boss_id}: {e}")
            return False


def sql_player_has_killed_boss(tg: int, boss_id: str) -> bool:
    """检查玩家是否至少击杀过一次指定 BOSS"""
    with Session() as session:
        try:
            obj = session.query(GamePlayerBossKill).filter(
                GamePlayerBossKill.tg == tg,
                GamePlayerBossKill.boss_id == boss_id
            ).first()
            return obj is not None and (obj.kill_count or 0) > 0
        except Exception:
            return False


def sql_get_major_realm_by_min_idx(min_idx: int):
    """按 min_idx 查找大境界配置（用于突破前置检查）"""
    with Session() as session:
        try:
            return session.query(GameMajorRealmConfig).filter(
                GameMajorRealmConfig.min_idx == min_idx,
                GameMajorRealmConfig.enabled == True
            ).first()
        except Exception:
            return None


def sql_bulk_upsert_loot(boss_id: str, entries: list) -> bool:
    """
    原子更新 BOSS 掉落表（先删后插，保持合计100%不变）。
    :param entries: [{"item_id": str, "drop_rate": float}, ...]  drop_rate 为0~1.0
    """
    with Session() as session:
        try:
            session.query(GameLootEntry).filter(GameLootEntry.boss_id == boss_id).delete()
            for e in entries:
                session.add(GameLootEntry(
                    boss_id=boss_id,
                    item_id=e["item_id"],
                    drop_rate=float(e["drop_rate"]),
                    max_per_kill=1,
                ))
            session.commit()
            return True
        except Exception as ex:
            session.rollback()
            LOGGER.error(f"【游戏】批量更新掉落表失败 boss={boss_id}: {ex}")
            return False
