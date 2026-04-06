"""
命令执行权限拦截器

在所有命令 handler 之前（group=-1）运行，检查：
1. 命令是否已开启（visible=True）
2. 用户等级是否满足 min_level 要求

不满足条件时调用 stop_propagation()，阻止后续所有 handler 执行，
用户不会收到任何响应。
"""
from pyrogram import filters
from bot import bot, owner, admins, config, LOGGER
from bot.web.admin.api_commands import MASTER_COMMANDS

_ALL_CMD_NAMES = [c["name"] for c in MASTER_COMMANDS]


@bot.on_message(filters.command(_ALL_CMD_NAMES), group=-1)
async def cmd_gate(client, message):
    """命令权限拦截器：关闭的命令或等级不足时停止事件传播"""
    if not message.from_user:
        return

    cmd_name = message.command[0].lower()
    uid = message.from_user.id

    # 获取命令默认配置
    master = next((c for c in MASTER_COMMANDS if c["name"] == cmd_name), None)
    if not master:
        return  # 未知命令，放行

    default_level = master["default_level"]

    # 读取覆盖配置
    overrides = config.cmd_overrides or {}
    ov = overrides.get(cmd_name)

    if ov is None:
        enabled = True
        min_level = default_level
    elif isinstance(ov, dict):
        enabled = ov.get("visible", True)
        min_level = ov.get("min_level", default_level)
    else:
        enabled = getattr(ov, "visible", True)
        min_level = getattr(ov, "min_level", default_level)

    # ① 命令已关闭 → 拦截
    if not enabled:
        LOGGER.debug(f"[cmd_gate] /{cmd_name} 已关闭，拦截 uid={uid}")
        message.stop_propagation()

    # ② 等级不足 → 拦截
    is_owner = uid == owner
    is_admin = uid in admins

    if min_level == "owner" and not is_owner:
        LOGGER.debug(f"[cmd_gate] /{cmd_name} 需要 owner 权限，拦截 uid={uid}")
        message.stop_propagation()
    elif min_level == "admin" and not (is_owner or is_admin):
        LOGGER.debug(f"[cmd_gate] /{cmd_name} 需要 admin 权限，拦截 uid={uid}")
        message.stop_propagation()
