"""
游戏配置 JSON API
GET  /admin/api/game/config        返回全局游戏配置
POST /admin/api/game/config        更新全局游戏配置
GET  /admin/api/game/bosses        返回所有 BOSS 配置
POST /admin/api/game/bosses/{id}   更新指定 BOSS 配置
GET  /admin/api/game/items         返回所有物品配置
POST /admin/api/game/items/{id}    更新指定物品配置
GET  /admin/api/game/loot/{boss}   返回 BOSS 掉落表
POST /admin/api/game/loot          更新掉落表条目
GET  /admin/api/game/stats         游戏统计信息（玩家数量、境界分布）
"""
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bot import config, save_config, LOGGER
from bot.sql_helper.sql_audit import log_audit
from bot.sql_helper.sql_game import (
    sql_get_all_bosses, sql_get_boss, sql_upsert_boss, sql_delete_boss,
    sql_get_all_items, sql_get_item_config, sql_upsert_item, sql_delete_item,
    sql_get_loot_table, sql_upsert_loot_entry,
    sql_get_realm_ranking,
    sql_get_all_shop_entries, sql_get_shop_entry,
    sql_upsert_shop_entry, sql_delete_shop_entry,
    sql_get_all_realms, sql_get_realm_config, sql_upsert_realm, sql_delete_realm,
    sql_get_all_major_realms, sql_get_major_realm_config,
    sql_upsert_major_realm, sql_delete_major_realm,
)
from bot.modules.game.game_data import (
    DEFAULT_GAME_CONFIG, reload_game_config, REALMS, RARITY_DISPLAY,
    reload_realm_cache, reload_major_realm_cache
)
from .auth import require_admin

router = APIRouter()


# ─────────────────────────── 全局游戏配置 ────────────────────────────────────

@router.get("/api/game/config")
async def get_game_config_api(admin=Depends(require_admin)):
    """读取当前游戏全局配置"""
    game_cfg = getattr(config, 'game', None) or {}
    merged = {**DEFAULT_GAME_CONFIG, **game_cfg}
    return {"ok": True, "config": merged}


class GameConfigUpdate(BaseModel):
    config: Dict[str, Any]


@router.post("/api/game/config")
async def update_game_config_api(body: GameConfigUpdate, admin=Depends(require_admin)):
    """更新游戏全局配置并写入 config.json"""
    try:
        allowed_keys = set(DEFAULT_GAME_CONFIG.keys())
        updates = {k: v for k, v in body.config.items() if k in allowed_keys}

        # 类型校验（cultivation_events 保留为 dict，其余按原始类型转换）
        for key, val in updates.items():
            if isinstance(val, dict):
                continue  # 嵌套 dict（如 cultivation_events）直接保留
            expected = type(DEFAULT_GAME_CONFIG[key])
            if expected == bool:
                updates[key] = bool(val)
            elif expected == int:
                updates[key] = int(val)
            elif expected == float:
                updates[key] = float(val)

        # 写入 config
        if not hasattr(config, 'game') or config.game is None:
            config.game = {}
        config.game.update(updates)
        save_config()

        # 清除游戏配置缓存
        reload_game_config()

        log_audit(
            category="settings",
            action="update",
            source="web",
            operator_tg=admin.tg if hasattr(admin, 'tg') else None,
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新游戏全局配置：{list(updates.keys())}"
        )
        return {"ok": True, "updated": updates}
    except Exception as e:
        LOGGER.error(f"【Admin】更新游戏配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── BOSS 配置 ───────────────────────────────────────

@router.get("/api/game/bosses")
async def get_all_bosses_api(admin=Depends(require_admin)):
    bosses = sql_get_all_bosses(include_disabled=True)
    data = []
    from bot.modules.game.game_data import get_realm_name
    for b in bosses:
        data.append({
            "id": b.id,
            "boss_id": b.boss_id,
            "name": b.name,
            "recommend_realm": b.recommend_realm,
            "recommend_realm_name": get_realm_name(b.recommend_realm),
            "hp": b.hp,
            "shield": b.shield,
            "atk_min": b.atk_min,
            "atk_max": b.atk_max,
            "cd_hours": b.cd_hours,
            "min_players": getattr(b, 'min_players', 2) or 2,
            "max_players": getattr(b, 'max_players', 4) or 4,
            "action_w_attack": getattr(b, 'action_w_attack', 55) or 55,
            "action_w_double": getattr(b, 'action_w_double', 15) or 15,
            "action_w_defend": getattr(b, 'action_w_defend', 15) or 15,
            "action_w_heal":   getattr(b, 'action_w_heal',   15) or 15,
            "def_min":  getattr(b, 'def_min',  10) or 10,
            "def_max":  getattr(b, 'def_max',  30) or 30,
            "heal_min": getattr(b, 'heal_min', 20) or 20,
            "heal_max": getattr(b, 'heal_max', 60) or 60,
            "enabled": b.enabled,
        })
    return {"ok": True, "bosses": data}


class BossUpdate(BaseModel):
    name: Optional[str] = None
    recommend_realm: Optional[int] = None
    hp: Optional[int] = None
    shield: Optional[int] = None
    atk_min: Optional[int] = None
    atk_max: Optional[int] = None
    cd_hours: Optional[int] = None
    min_players: Optional[int] = None
    max_players: Optional[int] = None
    action_w_attack: Optional[int] = None
    action_w_double: Optional[int] = None
    action_w_defend: Optional[int] = None
    action_w_heal:   Optional[int] = None
    def_min:  Optional[int] = None
    def_max:  Optional[int] = None
    heal_min: Optional[int] = None
    heal_max: Optional[int] = None
    enabled: Optional[bool] = None


@router.post("/api/game/bosses/{boss_id}")
async def update_boss_api(boss_id: str, body: BossUpdate, admin=Depends(require_admin)):
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")

        sql_upsert_boss(boss_id, **updates)
        log_audit(
            category="settings",
            action="update",
            source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新 BOSS 配置 {boss_id}：{list(updates.keys())}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 物品配置 ────────────────────────────────────────

@router.get("/api/game/items")
async def get_all_items_api(admin=Depends(require_admin)):
    items = sql_get_all_items(include_disabled=True)
    type_names = {
        "potion": "消耗品",
        "breakthrough": "突破丹药",
        "equipment": "装备",
        "stamina": "体力道具",
    }
    data = []
    for item in items:
        data.append({
            "id": item.id,
            "item_id": item.item_id,
            "name": item.name,
            "item_type": item.item_type,
            "item_type_name": type_names.get(item.item_type, item.item_type),
            "rarity": item.rarity,
            "rarity_name": RARITY_DISPLAY.get(item.rarity, item.rarity),
            "heal_min": item.heal_min,
            "heal_max": item.heal_max,
            "shield_min": item.shield_min,
            "shield_max": item.shield_max,
            "atk_bonus": item.atk_bonus,
            "def_bonus": item.def_bonus,
            "hp_bonus": item.hp_bonus,
            "break_boost": item.break_boost,
            "slot": item.slot,
            "realm_req_min": item.realm_req_min,
            "realm_req_max": item.realm_req_max,
            "usable_in_bag": item.usable_in_bag or False,
            "description": item.description or "",
            "enabled": item.enabled,
        })
    return {"ok": True, "items": data}


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    rarity: Optional[str] = None
    heal_min: Optional[int] = None
    heal_max: Optional[int] = None
    shield_min: Optional[int] = None
    shield_max: Optional[int] = None
    atk_bonus: Optional[int] = None
    def_bonus: Optional[int] = None
    hp_bonus: Optional[int] = None
    break_boost: Optional[int] = None
    realm_req_min: Optional[int] = None
    realm_req_max: Optional[int] = None
    usable_in_bag: Optional[bool] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


@router.post("/api/game/items/{item_id}")
async def update_item_api(item_id: str, body: ItemUpdate, admin=Depends(require_admin)):
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        sql_upsert_item(item_id, **updates)
        log_audit(
            category="settings",
            action="update",
            source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新物品配置 {item_id}：{list(updates.keys())}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 掉落表配置 ──────────────────────────────────────

@router.get("/api/game/loot/{boss_id}")
async def get_loot_table_api(boss_id: str, admin=Depends(require_admin)):
    entries = sql_get_loot_table(boss_id)
    data = []
    for e in entries:
        item_cfg = sql_get_item_config(e.item_id)
        data.append({
            "id": e.id,
            "boss_id": e.boss_id,
            "item_id": e.item_id,
            "item_name": item_cfg.name if item_cfg else e.item_id,
            "drop_rate": e.drop_rate,
            "drop_rate_pct": round(e.drop_rate * 100, 1),
            "max_per_kill": e.max_per_kill,
        })
    return {"ok": True, "loot": data}


class LootUpdate(BaseModel):
    boss_id: str
    item_id: str
    drop_rate: float  # 0.0~1.0，为该条目在权重池中的占比


@router.post("/api/game/loot")
async def update_loot_api(body: LootUpdate, admin=Depends(require_admin)):
    try:
        sql_upsert_loot_entry(body.boss_id, body.item_id, body.drop_rate, 1)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LootBulkEntry(BaseModel):
    item_id: str
    drop_rate: float  # 0.0~1.0


class LootBulkUpdate(BaseModel):
    entries: List[LootBulkEntry]


@router.put("/api/game/loot/{boss_id}/bulk")
async def bulk_update_loot_api(boss_id: str, body: LootBulkUpdate, admin=Depends(require_admin)):
    """原子替换 BOSS 掉落表（所有条目一次提交，确保权重合计正确）"""
    from bot.sql_helper.sql_game import sql_bulk_upsert_loot
    try:
        entries = [{"item_id": e.item_id, "drop_rate": e.drop_rate} for e in body.entries]
        ok = sql_bulk_upsert_loot(boss_id, entries)
        if not ok:
            raise HTTPException(status_code=500, detail="批量更新失败")
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"批量更新 BOSS {boss_id} 掉落表，共 {len(entries)} 条"
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 游戏统计 ────────────────────────────────────────

@router.get("/api/game/stats")
async def get_game_stats_api(admin=Depends(require_admin)):
    """游戏玩家统计信息"""
    from bot.sql_helper.sql_game import sql_get_realm_ranking, GamePlayer, Session
    from bot.sql_helper import Session as DBSession
    from bot.modules.game.game_data import REALMS

    try:
        with DBSession() as session:
            total = session.query(GamePlayer).count()

            # 境界分布
            realm_dist = {}
            for realm_id, name, *_ in REALMS:
                count = session.query(GamePlayer).filter(
                    GamePlayer.realm == realm_id
                ).count()
                if count > 0:
                    realm_dist[name] = count

        top10 = sql_get_realm_ranking(10)
        from bot.sql_helper.sql_emby import sql_get_emby
        leaders = []
        for p in top10:
            e = sql_get_emby(tg=p.tg)
            from bot.modules.game.game_data import get_realm_name
            leaders.append({
                "name": e.name if e else str(p.tg),
                "realm": get_realm_name(p.realm),
                "exp": p.exp,
            })

        return {
            "ok": True,
            "total_players": total,
            "realm_distribution": realm_dist,
            "top_players": leaders,
        }
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))


# ─────────────────────────── 商城条目管理 ─────────────────────────────────────

@router.get("/api/game/shop")
async def get_shop_entries_api(admin=Depends(require_admin)):
    """获取所有商城条目（含禁用）"""
    entries = sql_get_all_shop_entries()
    data = []
    type_names = {"stamina": "体力补充", "item": "游戏道具"}
    for e in entries:
        data.append({
            "id": e.id,
            "shop_id": e.shop_id,
            "name": e.name or "",
            "item_type": e.item_type,
            "item_type_name": type_names.get(e.item_type, e.item_type),
            "item_id": e.item_id or "",
            "min_qty": getattr(e, 'min_qty', 1),
            "max_qty": e.max_qty,
            "qty_step": getattr(e, 'qty_step', 1),
            "price_stones": e.price_stones,
            "sort_order": e.sort_order,
            "enabled": e.enabled,
        })
    return {"ok": True, "entries": data}


class ShopEntryCreate(BaseModel):
    item_type: str                   # "stamina" / "item"
    item_id: Optional[str] = None
    min_qty: int = 1
    max_qty: int = 1
    qty_step: int = 1
    price_stones: int
    sort_order: int = 0
    enabled: bool = True


class ShopEntryUpdate(BaseModel):
    item_type: Optional[str] = None
    item_id: Optional[str] = None
    min_qty: Optional[int] = None
    max_qty: Optional[int] = None
    qty_step: Optional[int] = None
    price_stones: Optional[int] = None
    sort_order: Optional[int] = None
    enabled: Optional[bool] = None


@router.post("/api/game/shop")
async def create_shop_entry_api(body: ShopEntryCreate, admin=Depends(require_admin)):
    """新增商城条目（shop_id 自动生成，名称自动取物品名）"""
    try:
        # 自动生成数字 shop_id
        all_entries = sql_get_all_shop_entries()
        used_ids = set()
        for e in all_entries:
            try:
                used_ids.add(int(e.shop_id))
            except (ValueError, TypeError):
                pass
        next_id = 1
        while next_id in used_ids:
            next_id += 1
        shop_id = str(next_id)

        # 自动取名称
        if body.item_type == "item" and body.item_id:
            item_cfg = sql_get_item_config(body.item_id)
            name = item_cfg.name if item_cfg else body.item_id
        else:
            name = "体力补充"

        kwargs = {k: v for k, v in body.dict().items()}
        kwargs["name"] = name
        sql_upsert_shop_entry(shop_id, **kwargs)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"新增游戏商城条目 {shop_id}：{name}"
        )
        return {"ok": True, "shop_id": shop_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/game/shop/{shop_id}")
async def update_shop_entry_api(shop_id: str, body: ShopEntryUpdate, admin=Depends(require_admin)):
    """更新商城条目"""
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        sql_upsert_shop_entry(shop_id, **updates)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新游戏商城条目 {shop_id}：{list(updates.keys())}"
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/game/shop/{shop_id}")
async def delete_shop_entry_api(shop_id: str, admin=Depends(require_admin)):
    """删除商城条目"""
    try:
        sql_delete_shop_entry(shop_id)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"删除游戏商城条目 {shop_id}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── BOSS 删除 / 禁用 ────────────────────────────────

@router.delete("/api/game/bosses/{boss_id}")
async def delete_boss_api(boss_id: str, admin=Depends(require_admin)):
    """彻底删除 BOSS 配置（不可恢复）"""
    try:
        sql_delete_boss(boss_id)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"删除 BOSS {boss_id}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/game/bosses/{boss_id}/toggle")
async def toggle_boss_api(boss_id: str, admin=Depends(require_admin)):
    """切换 BOSS 启用/禁用状态"""
    try:
        boss = sql_get_boss(boss_id)
        if not boss:
            raise HTTPException(status_code=404, detail="BOSS 不存在")
        new_state = not boss.enabled
        sql_upsert_boss(boss_id, enabled=new_state)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"{'启用' if new_state else '禁用'} BOSS {boss_id}"
        )
        return {"ok": True, "enabled": new_state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 物品删除 / 禁用 ─────────────────────────────────

@router.delete("/api/game/items/{item_id}")
async def delete_item_api(item_id: str, admin=Depends(require_admin)):
    """彻底删除物品配置（不可恢复）"""
    try:
        sql_delete_item(item_id)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"删除物品 {item_id}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/game/items/{item_id}/toggle")
async def toggle_item_api(item_id: str, admin=Depends(require_admin)):
    """切换物品启用/禁用状态"""
    try:
        item = sql_get_item_config(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="物品不存在")
        new_state = not item.enabled
        sql_upsert_item(item_id, enabled=new_state)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"{'启用' if new_state else '禁用'}物品 {item_id}"
        )
        return {"ok": True, "enabled": new_state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── BOSS 新增 ───────────────────────────────────────

class BossCreate(BaseModel):
    boss_id: str
    name: str
    recommend_realm: int = 0
    hp: int
    shield: int = 0
    atk_min: int
    atk_max: int
    cd_hours: int = 6
    min_players: int = 2
    max_players: int = 4
    action_w_attack: int = 55
    action_w_double: int = 15
    action_w_defend: int = 15
    action_w_heal:   int = 15
    def_min:  int = 10
    def_max:  int = 30
    heal_min: int = 20
    heal_max: int = 60
    enabled: bool = True


@router.post("/api/game/bosses")
async def create_boss_api(body: BossCreate, admin=Depends(require_admin)):
    """新增 BOSS"""
    try:
        kwargs = {k: v for k, v in body.dict().items() if k != "boss_id"}
        sql_upsert_boss(body.boss_id, **kwargs)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"新增 BOSS {body.boss_id}：{body.name}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 物品新增 ────────────────────────────────────────

class ItemCreate(BaseModel):
    item_id: str
    name: str
    item_type: str
    rarity: str = "common"
    heal_min: int = 0
    heal_max: int = 0
    shield_min: int = 0
    shield_max: int = 0
    atk_bonus: int = 0
    def_bonus: int = 0
    hp_bonus: int = 0
    break_boost: int = 0
    slot: Optional[str] = None
    realm_req_min: int = 0
    realm_req_max: int = 100
    description: Optional[str] = None
    enabled: bool = True


@router.post("/api/game/items")
async def create_item_api(body: ItemCreate, admin=Depends(require_admin)):
    """新增物品"""
    try:
        kwargs = {k: v for k, v in body.dict().items() if k != "item_id"}
        sql_upsert_item(body.item_id, **kwargs)
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"新增物品 {body.item_id}：{body.name}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 掉落表删除 ──────────────────────────────────────

@router.delete("/api/game/loot/{entry_id}")
async def delete_loot_entry_api(entry_id: int, admin=Depends(require_admin)):
    """删除掉落表条目"""
    from bot.sql_helper.sql_game import GameLootEntry, Session as DBSession
    try:
        with DBSession() as session:
            entry = session.query(GameLootEntry).filter(GameLootEntry.id == entry_id).first()
            if entry:
                session.delete(entry)
                session.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 境界配置管理 ─────────────────────────────────────

@router.get("/api/game/realms")
async def get_all_realms_api(admin=Depends(require_admin)):
    """获取所有境界配置"""
    realms = sql_get_all_realms(include_disabled=True)
    data = []
    for r in realms:
        data.append({
            "id": r.id,
            "realm_idx": r.realm_idx,
            "name": r.name,
            "major_realm": r.major_realm or "",
            "max_exp": r.max_exp,
            "base_max_hp": r.base_max_hp,
            "base_attack": r.base_attack,
            "base_defense": r.base_defense,
            "enabled": r.enabled,
            "sort_order": r.sort_order,
        })
    return {"ok": True, "realms": data}


class RealmUpsert(BaseModel):
    name: str
    major_realm: Optional[str] = None
    max_exp: int = 0
    base_max_hp: int = 80
    base_attack: int = 8
    base_defense: int = 5
    enabled: bool = True
    sort_order: int = 0


class RealmCreate(RealmUpsert):
    realm_idx: int


@router.post("/api/game/realms")
async def create_realm_api(body: RealmCreate, admin=Depends(require_admin)):
    """新增境界"""
    try:
        kwargs = {k: v for k, v in body.dict().items() if k != "realm_idx"}
        sql_upsert_realm(body.realm_idx, **kwargs)
        reload_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"新增境界 idx={body.realm_idx}：{body.name}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/game/realms/{realm_idx}")
async def update_realm_api(realm_idx: int, body: RealmUpsert, admin=Depends(require_admin)):
    """更新境界配置"""
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        sql_upsert_realm(realm_idx, **updates)
        reload_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新境界 idx={realm_idx}：{list(updates.keys())}"
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/game/realms/{realm_idx}")
async def delete_realm_api(realm_idx: int, admin=Depends(require_admin)):
    """删除境界配置"""
    try:
        sql_delete_realm(realm_idx)
        reload_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"删除境界 idx={realm_idx}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/api/game/realms/{realm_idx}/toggle")
async def toggle_realm_api(realm_idx: int, admin=Depends(require_admin)):
    """切换境界启用/禁用状态"""
    try:
        realm = sql_get_realm_config(realm_idx)
        if not realm:
            raise HTTPException(status_code=404, detail="境界不存在")
        new_state = not realm.enabled
        sql_upsert_realm(realm_idx, enabled=new_state)
        reload_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"{'启用' if new_state else '禁用'}境界 idx={realm_idx}"
        )
        return {"ok": True, "enabled": new_state}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 境界批量操作 ─────────────────────────────────────


class RealmBatchItem(BaseModel):
    realm_idx: int
    name: str
    major_realm: Optional[str] = None
    max_exp: int = 0
    base_max_hp: int = 80
    base_attack: int = 8
    base_defense: int = 5
    enabled: bool = True


class RealmBatchUpdate(BaseModel):
    realms: List[RealmBatchItem]


@router.post("/api/game/realms/batch")
async def batch_update_realms_api(body: RealmBatchUpdate, admin=Depends(require_admin)):
    """批量更新境界配置（一次保存整组）"""
    try:
        for item in body.realms:
            kwargs = item.dict()
            realm_idx = kwargs.pop("realm_idx")
            sql_upsert_realm(realm_idx, **kwargs)
        reload_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"批量保存境界配置，共 {len(body.realms)} 条"
        )
        return {"ok": True, "count": len(body.realms)}
    except Exception as e:
        LOGGER.error(f"【Admin】批量保存境界失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RealmResetRequest(BaseModel):
    major_realm: Optional[str] = None  # None = 全部重置，否则按大境界名重置


@router.post("/api/game/realms/reset")
async def reset_realms_api(body: RealmResetRequest, admin=Depends(require_admin)):
    """将境界数据重置为硬编码默认值（可按大境界过滤）"""
    from bot.modules.game.game_data import REALMS, MAJOR_REALM_RANGES
    try:
        if body.major_realm:
            # 只重置指定大境界
            major = body.major_realm
            if major not in MAJOR_REALM_RANGES and major != "肉体凡胎":
                raise HTTPException(status_code=400, detail=f"未知大境界: {major}")
            if major == "肉体凡胎":
                target_idxes = {0}
            else:
                rmin, rmax = MAJOR_REALM_RANGES[major]
                target_idxes = set(range(rmin, rmax + 1))
            to_reset = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in REALMS if r[0] in target_idxes]
        else:
            to_reset = REALMS

        for realm_id, name, max_exp, base_max_hp, base_attack, base_defense in to_reset:
            major_name = "肉体凡胎"
            for prefix in ['练气', '筑基', '金丹', '元婴', '化神', '炼虚', '合体', '大乘', '渡劫']:
                if name.startswith(prefix):
                    major_name = prefix
                    break
            sql_upsert_realm(
                realm_id,
                name=name, major_realm=major_name, max_exp=max_exp,
                base_max_hp=base_max_hp, base_attack=base_attack,
                base_defense=base_defense, sort_order=realm_id, enabled=True
            )
        reload_realm_cache()

        scope = body.major_realm or "全部"
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"重置境界为默认值，范围: {scope}，共 {len(to_reset)} 条"
        )
        return {"ok": True, "count": len(to_reset), "scope": scope}
    except HTTPException:
        raise
    except Exception as e:
        LOGGER.error(f"【Admin】重置境界失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── 大境界配置管理 ──────────────────────────────────

@router.get("/api/game/major_realms")
async def get_all_major_realms_api(admin=Depends(require_admin)):
    """获取所有大境界配置"""
    rows = sql_get_all_major_realms(include_disabled=True)
    data = []
    for r in rows:
        data.append({
            "id": r.id,
            "major_realm": r.major_realm,
            "min_idx": r.min_idx,
            "layer_count": r.layer_count,
            "is_infinite": r.is_infinite,
            "base_max_exp": r.base_max_exp,
            "step_max_exp": r.step_max_exp,
            "base_max_hp": r.base_max_hp,
            "step_max_hp": r.step_max_hp,
            "base_attack": r.base_attack,
            "step_attack": r.step_attack,
            "base_defense": r.base_defense,
            "step_defense": r.step_defense,
            "sort_order": r.sort_order,
            "enabled": r.enabled,
            "prereq_enabled": getattr(r, 'prereq_enabled', False) or False,
            "prereq_boss_id": getattr(r, 'prereq_boss_id', None) or "",
        })
    return {"ok": True, "major_realms": data}


class MajorRealmUpsert(BaseModel):
    min_idx: Optional[int] = None
    layer_count: Optional[int] = None
    is_infinite: Optional[bool] = None
    base_max_exp: Optional[int] = None
    step_max_exp: Optional[int] = None
    base_max_hp: Optional[int] = None
    step_max_hp: Optional[int] = None
    base_attack: Optional[int] = None
    step_attack: Optional[int] = None
    base_defense: Optional[int] = None
    step_defense: Optional[int] = None
    sort_order: Optional[int] = None
    enabled: Optional[bool] = None
    prereq_enabled: Optional[bool] = None
    prereq_boss_id: Optional[str] = None


class MajorRealmCreate(MajorRealmUpsert):
    major_realm: str
    min_idx: int
    layer_count: int = 10
    is_infinite: bool = False
    base_max_exp: int = 0
    step_max_exp: int = 0
    base_max_hp: int = 80
    step_max_hp: int = 10
    base_attack: int = 8
    step_attack: int = 1
    base_defense: int = 5
    step_defense: int = 1


@router.post("/api/game/major_realms")
async def create_major_realm_api(body: MajorRealmCreate, admin=Depends(require_admin)):
    """新增大境界配置"""
    try:
        kwargs = {k: v for k, v in body.dict().items() if k != "major_realm" and v is not None}
        sql_upsert_major_realm(body.major_realm, **kwargs)
        reload_major_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"新增大境界配置：{body.major_realm}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/game/major_realms/{major_realm}")
async def update_major_realm_api(major_realm: str, body: MajorRealmUpsert, admin=Depends(require_admin)):
    """更新大境界配置"""
    try:
        updates = {k: v for k, v in body.dict().items() if v is not None}
        # prereq_enabled=False is filtered out by "if v is not None" (False != None, so it's kept)
        # but prereq_boss_id=None (empty select) is filtered out — handle explicitly
        if body.prereq_enabled is not None:
            updates['prereq_enabled'] = body.prereq_enabled
        if body.prereq_boss_id is not None:
            updates['prereq_boss_id'] = body.prereq_boss_id or None
        if not updates:
            raise HTTPException(status_code=400, detail="无更新字段")
        sql_upsert_major_realm(major_realm, **updates)
        reload_major_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"更新大境界配置 {major_realm}：{list(updates.keys())}"
        )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/game/major_realms/{major_realm}")
async def delete_major_realm_api(major_realm: str, admin=Depends(require_admin)):
    """删除大境界配置（慎用）"""
    try:
        sql_delete_major_realm(major_realm)
        reload_major_realm_cache()
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if hasattr(admin, 'username') else "Admin",
            detail=f"删除大境界配置：{major_realm}"
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
