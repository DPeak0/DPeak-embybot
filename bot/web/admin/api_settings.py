"""
系统设置 JSON API
GET  /admin/api/settings    返回可展示的配置字段（隐藏敏感信息）
POST /admin/api/settings    保存部分字段到内存 config 并写入 config.json
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from bot import config, save_config, LOGGER
from bot.schemas.schemas import API, Ranks
from bot.sql_helper.sql_audit import log_audit
from .auth import require_admin

router = APIRouter()

# ── 字段路由分类 ─────────────────────────────────────────────────────────────

# 保存到 config.open（Open 模型）的布尔字段
_OPEN_BOOL_FIELDS = {
    "stat", "checkin", "exchange", "whitelist", "invite", "leave_ban", "uplays",
}
# 保存到 config.open 的整数字段
_OPEN_INT_FIELDS = {
    "all_user", "open_us",
    "all_user_b", "all_user_e", "all_user_a",
    "exchange_cost", "whitelist_cost", "invite_cost", "srank_cost",
    "request_quota_a", "request_quota_b", "request_quota_e", "request_quota_days",
    "request_credit_cost",
}
# 保存到 config.open 的字符串字段
_OPEN_STR_FIELDS = {"checkin_lv", "invite_lv"}

# 保存到 config.schedall 的布尔字段（前缀 schedall_）
_SCHEDALL_BOOL_FIELDS = {
    "schedall_check_ex", "schedall_low_activity",
    "schedall_dayrank", "schedall_weekrank",
    "schedall_dayplayrank", "schedall_weekplayrank",
    "schedall_backup_db", "schedall_partition_check",
}

# 保存到 config.api 的字段（前缀 api_）
_API_BOOL_FIELDS = {"api_status"}
_API_INT_FIELDS = {"api_http_port"}
_API_STR_FIELDS = {"api_http_url", "api_allow_origins"}

# 顶层布尔字段
_TOP_BOOL_FIELDS = {
    "fuxx_pitao", "client_filter_terminate_session", "client_filter_block_user",
}
# 顶层整数字段
_TOP_INT_FIELDS = {"kk_gift_days", "activity_check_days", "freeze_days"}
# 顶层字符串字段（直接 setattr）
_TOP_STR_FIELDS = {
    "money", "bot_photo", "emby_url", "emby_line", "emby_whitelist_line",
    "miniapp_url", "tmdb_api_key", "hdhive_base_url", "hdhive_api_key",
    "cms_base_url", "cms_api_token", "ranks_logo",
}

# 所有允许修改的字段（白名单）
_EDITABLE_FIELDS = (
    _OPEN_BOOL_FIELDS | _OPEN_INT_FIELDS | _OPEN_STR_FIELDS
    | _SCHEDALL_BOOL_FIELDS
    | _API_BOOL_FIELDS | _API_INT_FIELDS | _API_STR_FIELDS
    | _TOP_BOOL_FIELDS | _TOP_INT_FIELDS | _TOP_STR_FIELDS
)


def _safe_config() -> dict:
    """返回安全的配置字段（不含密钥/密码）"""
    if not getattr(config, "api", None):
        config.api = API()
    if not getattr(config, "ranks", None):
        config.ranks = Ranks()
    cr = getattr(config.open, "checkin_reward", [1, 10]) or [1, 10]
    return {
        # ── Bot 基础 ───────────────────────────────────────────
        "bot_name": config.bot_name,
        "money": config.money or "石子",
        "bot_photo": config.bot_photo or "",
        # ── Emby ──────────────────────────────────────────────
        "emby_url": config.emby_url,
        "emby_line": config.emby_line,
        "emby_whitelist_line": config.emby_whitelist_line or "",
        # ── MiniApp / TMDB ─────────────────────────────────────
        "miniapp_url": config.miniapp_url or "",
        "tmdb_api_key": config.tmdb_api_key or "",
        # ── API 设置 ───────────────────────────────────────────
        "api_status": getattr(config.api, "status", False),
        "api_http_url": getattr(config.api, "http_url", "0.0.0.0"),
        "api_http_port": getattr(config.api, "http_port", 8838),
        "api_allow_origins": ", ".join(getattr(config.api, "allow_origins", ["*"]) or ["*"]),
        "hdhive_base_url": getattr(config, "hdhive_base_url", "https://hdhive.com") or "https://hdhive.com",
        "hdhive_api_key": getattr(config, "hdhive_api_key", "") or "",
        "cms_base_url": getattr(config, "cms_base_url", "https://cms.dpeak.cn") or "https://cms.dpeak.cn",
        "cms_api_token": getattr(config, "cms_api_token", "") or "",
        # ── 注册设置 ───────────────────────────────────────────
        "stat": getattr(config.open, "stat", False),
        "all_user": getattr(config.open, "all_user", 0),
        "open_us": getattr(config.open, "open_us", 30),
        "all_user_b": getattr(config.open, "all_user_b", 0),
        "all_user_e": getattr(config.open, "all_user_e", 0),
        "all_user_a": getattr(config.open, "all_user_a", 0),
        # ── 功能开关 ───────────────────────────────────────────
        "checkin": getattr(config.open, "checkin", True),
        "exchange": getattr(config.open, "exchange", True),
        "whitelist": getattr(config.open, "whitelist", False),
        "invite": getattr(config.open, "invite", False),
        "leave_ban": getattr(config.open, "leave_ban", False),
        "uplays": getattr(config.open, "uplays", False),
        "checkin_lv": getattr(config.open, "checkin_lv", "d"),
        "invite_lv": getattr(config.open, "invite_lv", "a"),
        # ── 积分消耗 ───────────────────────────────────────────
        "exchange_cost": getattr(config.open, "exchange_cost", 100),
        "whitelist_cost": getattr(config.open, "whitelist_cost", 9999),
        "invite_cost": getattr(config.open, "invite_cost", 1000),
        "srank_cost": getattr(config.open, "srank_cost", 5),
        "checkin_reward_min": cr[0] if len(cr) > 0 else 1,
        "checkin_reward_max": cr[1] if len(cr) > 1 else 10,
        # ── 运营参数 ───────────────────────────────────────────
        "kk_gift_days": config.kk_gift_days,
        "activity_check_days": config.activity_check_days,
        "freeze_days": config.freeze_days,
        "fuxx_pitao": config.fuxx_pitao,
        # ── 求片额度 ───────────────────────────────────────────
        "request_quota_a": getattr(config.open, "request_quota_a", 999),
        "request_quota_b": getattr(config.open, "request_quota_b", 10),
        "request_quota_e": getattr(config.open, "request_quota_e", 5),
        "request_quota_days": getattr(config.open, "request_quota_days", 30),
        "request_credit_cost": getattr(config.open, "request_credit_cost", 0),
        # ── 计划任务 ───────────────────────────────────────────
        "schedall_check_ex": getattr(config.schedall, "check_ex", True),
        "schedall_low_activity": getattr(config.schedall, "low_activity", False),
        "schedall_dayrank": getattr(config.schedall, "dayrank", False),
        "schedall_weekrank": getattr(config.schedall, "weekrank", False),
        "schedall_dayplayrank": getattr(config.schedall, "dayplayrank", False),
        "schedall_weekplayrank": getattr(config.schedall, "weekplayrank", False),
        "schedall_backup_db": getattr(config.schedall, "backup_db", False),
        "schedall_partition_check": getattr(config.schedall, "partition_check", True),
        # ── 客户端过滤 ─────────────────────────────────────────
        "client_filter_terminate_session": getattr(config, "client_filter_terminate_session", True),
        "client_filter_block_user": getattr(config, "client_filter_block_user", False),
        # ── Ranks ──────────────────────────────────────────────
        "ranks_logo": config.ranks.logo if hasattr(config, "ranks") and config.ranks else "DPeakEmby",
    }


@router.get("/api/settings")
async def get_settings(admin=Depends(require_admin)):
    return JSONResponse({"ok": True, "settings": _safe_config()})


@router.post("/api/settings")
async def save_settings(request: Request, admin=Depends(require_admin)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "msg": "请求体解析失败"}, status_code=400)

    if not getattr(config, "api", None):
        config.api = API()
    if not getattr(config, "ranks", None):
        config.ranks = Ranks()

    updated = []
    before_parts = []
    after_parts = []
    invalid = []

    for key, value in body.items():
        if key not in _EDITABLE_FIELDS:
            continue
        try:
            if key in _OPEN_BOOL_FIELDS:
                old_val = getattr(config.open, key, None)
                new_val = bool(value)
                setattr(config.open, key, new_val)
            elif key in _OPEN_INT_FIELDS:
                old_val = getattr(config.open, key, None)
                new_val = int(value)
                setattr(config.open, key, new_val)
            elif key in _OPEN_STR_FIELDS:
                old_val = getattr(config.open, key, None)
                new_val = str(value)
                setattr(config.open, key, new_val)
            elif key in _SCHEDALL_BOOL_FIELDS:
                attr = key[len("schedall_"):]
                old_val = getattr(config.schedall, attr, None)
                new_val = bool(value)
                setattr(config.schedall, attr, new_val)
            elif key in _API_BOOL_FIELDS:
                attr = key[len("api_"):]
                old_val = getattr(config.api, attr, None)
                new_val = bool(value)
                setattr(config.api, attr, new_val)
            elif key in _API_INT_FIELDS:
                attr = key[len("api_"):]
                old_val = getattr(config.api, attr, None)
                new_val = int(value)
                setattr(config.api, attr, new_val)
            elif key in _API_STR_FIELDS:
                attr = key[len("api_"):]
                old_val = getattr(config.api, attr, None)
                if key == "api_allow_origins":
                    raw = str(value or "").strip()
                    if not raw or raw == "*":
                        new_val = ["*"]
                    else:
                        new_val = [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]
                else:
                    new_val = str(value)
                setattr(config.api, attr, new_val)
            elif key in _TOP_BOOL_FIELDS:
                old_val = getattr(config, key, None)
                new_val = bool(value)
                setattr(config, key, new_val)
            elif key in _TOP_INT_FIELDS:
                old_val = getattr(config, key, None)
                new_val = int(value)
                setattr(config, key, new_val)
            elif key == "ranks_logo":
                old_val = config.ranks.logo if hasattr(config, "ranks") and config.ranks else None
                new_val = str(value)
                config.ranks.logo = new_val
            else:
                old_val = getattr(config, key, None)
                new_val = value
                setattr(config, key, new_val)
            updated.append(key)
            before_parts.append(f"{key}={old_val}")
            after_parts.append(f"{key}={new_val}")
        except Exception as e:
            invalid.append(key)
            LOGGER.warning(f"【Admin】设置字段 {key} 失败: {e}")

    # 特殊处理 checkin_reward（两个字段合并为 list）
    if "checkin_reward_min" in body or "checkin_reward_max" in body:
        try:
            cr = getattr(config.open, "checkin_reward", [1, 10]) or [1, 10]
            old_cr = list(cr)
            mn = int(body.get("checkin_reward_min", cr[0]))
            mx = int(body.get("checkin_reward_max", cr[1] if len(cr) > 1 else 10))
            config.open.checkin_reward = [mn, mx]
            updated.append("checkin_reward")
            before_parts.append(f"checkin_reward={old_cr}")
            after_parts.append(f"checkin_reward=[{mn},{mx}]")
        except Exception as e:
            LOGGER.warning(f"【Admin】设置 checkin_reward 失败: {e}")

    if not updated:
        if invalid:
            return JSONResponse({"ok": False, "msg": f"以下字段保存失败: {', '.join(invalid)}", "settings": _safe_config()})
        return JSONResponse({"ok": False, "msg": "没有可更新的字段", "settings": _safe_config()})

    try:
        save_config()
        ip = request.client.host if request.client else None
        log_audit(category="settings", action="update", source="web",
                  operator_name=admin.get("username"), ip=ip,
                  before_val='; '.join(before_parts),
                  after_val='; '.join(after_parts),
                  detail=f"更新配置: {', '.join(updated)}")
        LOGGER.info(f"【Admin】管理员 {admin.get('username')} 更新了配置: {updated}")
        return JSONResponse({"ok": True, "msg": f"已保存: {', '.join(updated)}", "settings": _safe_config()})
    except Exception as e:
        LOGGER.error(f"【Admin】保存配置失败: {e}")
        return JSONResponse({"ok": False, "msg": f"保存失败: {e}"}, status_code=500)
