"""
命令管理 API
GET  /admin/api/commands          - 获取所有命令及当前覆盖配置
POST /admin/api/commands          - 保存命令覆盖配置并刷新 Telegram 命令列表
POST /admin/api/commands/refresh  - 仅刷新 Telegram 命令列表（不保存配置）
"""
import asyncio
from typing import List, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .auth import require_admin

router = APIRouter(prefix="/api/commands")

# ── 所有命令的主列表（name, description, default_level） ───────────────────────
# default_level: "user" / "admin" / "owner"
MASTER_COMMANDS: List[Dict[str, str]] = [
    # ── 用户命令 ──
    {"name": "start",               "description": "[私聊] 开启用户面板",                   "default_level": "user"},
    {"name": "myinfo",              "description": "[用户] 查看状态",                       "default_level": "user"},
    {"name": "count",               "description": "[用户] 媒体库数量",                     "default_level": "user"},
    {"name": "red",                 "description": "[用户/禁言] 发红包",                    "default_level": "user"},
    {"name": "srank",               "description": "[用户/禁言] 查看计分",                  "default_level": "user"},
    # ── 管理员命令 ──
    {"name": "kk",                  "description": "管理用户 [管理]",                       "default_level": "admin"},
    {"name": "score",               "description": "加/减积分 [管理]",                      "default_level": "admin"},
    {"name": "coins",               "description": "加/减货币 [管理]",                      "default_level": "admin"},
    {"name": "deleted",             "description": "清理死号 [管理]",                       "default_level": "admin"},
    {"name": "kick_not_emby",       "description": "踢出当前群内无号崽 [管理]",              "default_level": "admin"},
    {"name": "renew",               "description": "调整到期时间 [管理]",                   "default_level": "admin"},
    {"name": "rmemby",              "description": "删除用户[包括非tg] [管理]",             "default_level": "admin"},
    {"name": "prouser",             "description": "增加白名单 [管理]",                     "default_level": "admin"},
    {"name": "revuser",             "description": "减少白名单 [管理]",                     "default_level": "admin"},
    {"name": "rev_white_channel",   "description": "移除皮套人白名单 [管理]",               "default_level": "admin"},
    {"name": "white_channel",       "description": "添加皮套人白名单 [管理]",               "default_level": "admin"},
    {"name": "unban_channel",       "description": "解封皮套人 [管理]",                     "default_level": "admin"},
    {"name": "syncgroupm",          "description": "消灭不在群的人 [管理]",                 "default_level": "admin"},
    {"name": "syncunbound",         "description": "消灭未绑定bot的emby账户 [管理]",        "default_level": "admin"},
    {"name": "scan_embyname",       "description": "扫描同名的用户记录 [管理]",             "default_level": "admin"},
    {"name": "low_activity",        "description": "手动运行活跃检测 [管理]",               "default_level": "admin"},
    {"name": "check_ex",            "description": "手动到期检测 [管理]",                   "default_level": "admin"},
    {"name": "uranks",              "description": "召唤观影时长榜，失效时用 [管理]",        "default_level": "admin"},
    {"name": "days_ranks",          "description": "召唤播放次数日榜，失效时用 [管理]",      "default_level": "admin"},
    {"name": "week_ranks",          "description": "召唤播放次数周榜，失效时用 [管理]",      "default_level": "admin"},
    {"name": "sync_favorites",      "description": "同步收藏记录 [管理]",                   "default_level": "admin"},
    {"name": "embyadmin",           "description": "开启emby控制台权限 [管理]",             "default_level": "admin"},
    {"name": "ucr",                 "description": "私聊创建非tg的emby用户 [管理]",         "default_level": "admin"},
    {"name": "uinfo",               "description": "查询指定用户名 [管理]",                 "default_level": "admin"},
    {"name": "urm",                 "description": "删除指定用户名 [管理]",                 "default_level": "admin"},
    {"name": "userip",              "description": "查询指定用户播放过的设备&ip [管理]",    "default_level": "admin"},
    {"name": "udeviceid",           "description": "查询指定设备ID [管理]",                 "default_level": "admin"},
    {"name": "auditip",             "description": "根据IP地址审计用户活动 [管理]",         "default_level": "admin"},
    {"name": "auditdevice",         "description": "根据设备名审计用户 [管理]",             "default_level": "admin"},
    {"name": "auditclient",         "description": "根据客户端名审计用户 [管理]",           "default_level": "admin"},
    {"name": "renewall",            "description": "一键派送天数给所有未封禁的用户 [管理]", "default_level": "admin"},
    {"name": "coinsall",            "description": "一键派送币币给指定等级的用户 [管理]",   "default_level": "admin"},
    {"name": "coinsclear",          "description": "一键清除所有用户的币币 [管理]",         "default_level": "admin"},
    {"name": "callall",             "description": "群发消息给每个人 [管理]",               "default_level": "admin"},
    {"name": "only_rm_emby",        "description": "删除指定的Emby账号 [管理]",             "default_level": "admin"},
    {"name": "only_rm_record",      "description": "删除指定的tgid数据库记录 [管理]",       "default_level": "admin"},
    {"name": "restart",             "description": "重启bot [管理]",                        "default_level": "admin"},
    {"name": "update_bot",          "description": "更新bot [管理]",                        "default_level": "admin"},
    # ── Owner 命令 ──
    {"name": "proadmin",            "description": "添加bot管理 [owner]",                   "default_level": "owner"},
    {"name": "revadmin",            "description": "移除bot管理 [owner]",                   "default_level": "owner"},
    {"name": "bindall_id",          "description": "一键更新用户们Embyid [owner]",          "default_level": "owner"},
    {"name": "backup_db",           "description": "手动备份数据库 [owner]",                "default_level": "owner"},
    {"name": "unbanall",            "description": "解除所有用户的禁用状态 [owner]",        "default_level": "owner"},
    {"name": "banall",              "description": "禁用所有用户 [owner]",                  "default_level": "owner"},
    {"name": "paolu",               "description": "跑路!!!删除所有用户 [owner]",           "default_level": "owner"},
    {"name": "restore_from_db",     "description": "恢复Emby账户 [owner]",                  "default_level": "owner"},
    {"name": "config",              "description": "开启bot高级控制面板 [owner]",            "default_level": "owner"},
    {"name": "embylibs_unblockall", "description": "一键开启所有用户的媒体库 [owner]",      "default_level": "owner"},
    {"name": "embylibs_blockall",   "description": "一键关闭所有用户的媒体库 [owner]",      "default_level": "owner"},
    {"name": "extraembylibs_blockall",   "description": "一键关闭所有用户的额外媒体库 [owner]", "default_level": "owner"},
    {"name": "extraembylibs_unblockall", "description": "一键开启所有用户的额外媒体库 [owner]", "default_level": "owner"},
]

_LEVEL_LABEL = {"user": "普通用户", "admin": "管理员", "owner": "Owner"}


def _get_effective_level(name: str, overrides: dict) -> str:
    ov = overrides.get(name)
    if ov and isinstance(ov, dict):
        return ov.get("min_level", "")
    if hasattr(ov, "min_level"):
        return ov.min_level
    return ""


def build_command_lists(overrides: dict):
    """根据 overrides 构建 (user_p, admin_p, owner_p) BotCommand 列表"""
    from pyrogram.types import BotCommand
    from bot import sakura_b

    user_p, admin_p, owner_p = [], [], []

    for cmd in MASTER_COMMANDS:
        name = cmd["name"]
        desc = cmd["description"].replace("货币", sakura_b) if name == "coins" else cmd["description"]
        default_lv = cmd["default_level"]

        ov = overrides.get(name)
        if ov is None:
            visible = True
            min_level = default_lv
        elif isinstance(ov, dict):
            visible = ov.get("visible", True)
            min_level = ov.get("min_level", default_lv)
        else:
            visible = getattr(ov, "visible", True)
            min_level = getattr(ov, "min_level", default_lv)

        if not visible:
            continue

        bc = BotCommand(name, desc)
        if min_level == "user":
            user_p.append(bc)
            admin_p.append(bc)
            owner_p.append(bc)
        elif min_level == "admin":
            admin_p.append(bc)
            owner_p.append(bc)
        else:  # owner
            owner_p.append(bc)

    return user_p, admin_p, owner_p


async def _do_set_commands(overrides: dict):
    """调用 Pyrogram 刷新 Telegram 命令列表"""
    from bot import bot, owner, admins, group, LOGGER
    from pyrogram.types import (BotCommandScopeChatMember, BotCommandScopeChat,
                                BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats)

    user_p, admin_p, owner_p = build_command_lists(overrides)
    try:
        try:
            await bot.delete_bot_commands(scope=BotCommandScopeAllGroupChats())
        except Exception:
            pass
        try:
            await bot.delete_bot_commands(scope=BotCommandScopeAllPrivateChats())
        except Exception:
            pass
        try:
            await bot.set_bot_commands(user_p, scope=BotCommandScopeAllPrivateChats())
        except Exception:
            pass
        try:
            await bot.set_bot_commands(user_p, scope=BotCommandScopeAllGroupChats())
        except Exception:
            pass
        for admin_id in admins:
            try:
                await bot.set_bot_commands(admin_p, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                pass
            for g in group:
                try:
                    await bot.set_bot_commands(admin_p, scope=BotCommandScopeChatMember(chat_id=g, user_id=admin_id))
                except Exception:
                    pass
        try:
            await bot.set_bot_commands(owner_p, scope=BotCommandScopeChat(chat_id=owner))
        except Exception:
            pass
        for g in group:
            try:
                await bot.set_bot_commands(owner_p, scope=BotCommandScopeChatMember(chat_id=g, user_id=owner))
            except Exception:
                pass
        LOGGER.info("命令管理后台：已刷新 Telegram 命令列表")
    except Exception as e:
        LOGGER.error(f"命令管理后台：刷新命令列表失败 {e}")


# ── Request 模型 ─────────────────────────────────────────────────────────────
class CmdItem(BaseModel):
    name: str
    visible: bool
    min_level: str


class SavePayload(BaseModel):
    commands: List[CmdItem]


# ── 路由 ──────────────────────────────────────────────────────────────────────
@router.get("")
async def get_commands(admin=Depends(require_admin)):
    """返回所有命令及当前配置"""
    from bot import config

    overrides = config.cmd_overrides or {}
    result = []
    for cmd in MASTER_COMMANDS:
        name = cmd["name"]
        ov = overrides.get(name)
        if ov is None:
            visible = True
            min_level = cmd["default_level"]
        elif isinstance(ov, dict):
            visible = ov.get("visible", True)
            min_level = ov.get("min_level", cmd["default_level"])
        else:
            visible = getattr(ov, "visible", True)
            min_level = getattr(ov, "min_level", cmd["default_level"])

        result.append({
            "name": name,
            "description": cmd["description"],
            "default_level": cmd["default_level"],
            "default_level_label": _LEVEL_LABEL.get(cmd["default_level"], cmd["default_level"]),
            "visible": visible,
            "min_level": min_level,
            "min_level_label": _LEVEL_LABEL.get(min_level, min_level),
        })
    return {"ok": True, "commands": result}


@router.post("")
async def save_commands(payload: SavePayload, request: Request, admin=Depends(require_admin)):
    """保存命令覆盖配置并刷新 Telegram 命令列表"""
    from bot import config, save_config
    from bot.schemas.schemas import CmdOverride

    new_overrides: Dict[str, CmdOverride] = {}
    for item in payload.commands:
        cmd_default = next((c for c in MASTER_COMMANDS if c["name"] == item.name), None)
        if cmd_default is None:
            continue
        # 只保存与默认值不同的配置，以减少 config.json 体积
        if item.visible and item.min_level == cmd_default["default_level"]:
            continue
        new_overrides[item.name] = CmdOverride(visible=item.visible, min_level=item.min_level)

    config.cmd_overrides = new_overrides
    try:
        save_config()
    except Exception as e:
        return {"ok": False, "msg": f"保存配置失败: {e}"}

    # 异步刷新 Telegram 命令列表（不阻塞响应）
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_set_commands(new_overrides))
    except Exception:
        pass

    # 审计日志
    try:
        from bot.sql_helper.sql_audit import log_audit
        log_audit(
            category="settings", action="update", source="web",
            operator_name=admin.username if admin else "",
            detail=f"更新命令显示/权限配置，共 {len(new_overrides)} 条覆盖项",
            ip=request.client.host if request.client else "",
        )
    except Exception:
        pass

    return {"ok": True, "msg": f"已保存，共 {len(new_overrides)} 条覆盖配置，Telegram 命令刷新中…"}


@router.post("/refresh")
async def refresh_commands(admin=Depends(require_admin)):
    """仅刷新 Telegram 命令列表"""
    from bot import config

    overrides = config.cmd_overrides or {}
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_set_commands(overrides))
    except Exception as e:
        return {"ok": False, "msg": f"刷新失败: {e}"}
    return {"ok": True, "msg": "Telegram 命令列表刷新中…"}
