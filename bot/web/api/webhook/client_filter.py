from fastapi import APIRouter, Request, HTTPException
from bot.sql_helper.sql_emby import Emby, sql_get_emby, sql_update_emby
from bot import LOGGER, bot, config
from bot.func_helper.emby import emby
import json
import re
from typing import Dict, List
from datetime import datetime

router = APIRouter()

# 默认的被拦截的客户端模式列表
DEFAULT_BLOCKED_CLIENTS = [
    r".*网易爆米花.*",
    r".*netease.*popcorn.*",
    r".*curl.*",
    r".*wget.*",
    r".*python.*",
    r".*spider.*",
    r".*crawler.*",
    r".*scraper.*",
    r".*downloader.*",
    r".*aria2.*",
    r".*youtube-dl.*",
    r".*yt-dlp.*",
    r".*ffmpeg.*",
    r".*vlc.*",
]


async def get_blocked_clients() -> List[str]:
    """获取被拦截的客户端模式列表"""
    try:
        # 从配置中获取，如果没有则使用默认值
        blocked_agents = getattr(config, "blocked_clients", DEFAULT_BLOCKED_CLIENTS)
        return blocked_agents if blocked_agents else DEFAULT_BLOCKED_CLIENTS
    except Exception as e:
        LOGGER.error(f"获取被拦截客户端列表失败: {str(e)}")
        return DEFAULT_BLOCKED_CLIENTS


async def is_client_blocked(client: str) -> bool:
    """检查客户端是否被拦截"""
    if not client:
        return False

    blocked_clients = await get_blocked_clients()
    client_lower = client.lower()

    for pattern in blocked_clients:
        try:
            if re.search(pattern.lower(), client_lower):
                return True
        except re.error as e:
            LOGGER.error(f"正则表达式错误: {pattern} - {str(e)}")
            continue

    return False


def _normalize_event_name(event: str) -> str:
    return str(event or "").strip().lower()


def _extract_client_context(webhook_data: dict) -> Dict[str, str]:
    """尽可能兼容不同 webhook 负载结构，提取客户端与用户上下文。"""
    session_info = webhook_data.get("Session")
    if not isinstance(session_info, dict):
        session_info = {}

    user_info = webhook_data.get("User")
    if not isinstance(user_info, dict):
        user_info = {}

    candidates = []
    for value in [
        session_info.get("Client"),
        webhook_data.get("Client"),
        webhook_data.get("AppName"),
        session_info.get("DeviceName"),
        webhook_data.get("DeviceName"),
        session_info.get("UserAgent"),
        webhook_data.get("UserAgent"),
    ]:
        normalized = str(value or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    detection_text = " | ".join(candidates)
    client_name = candidates[0] if candidates else ""

    return {
        "event": _normalize_event_name(webhook_data.get("Event", "")),
        "user_name": str(
            user_info.get("Name")
            or session_info.get("UserName")
            or webhook_data.get("UserName")
            or ""
        ).strip(),
        "emby_id": str(
            user_info.get("Id")
            or session_info.get("UserId")
            or webhook_data.get("UserId")
            or ""
        ).strip(),
        "session_id": str(
            session_info.get("Id")
            or webhook_data.get("SessionId")
            or ""
        ).strip(),
        "device_id": str(
            session_info.get("DeviceId")
            or webhook_data.get("DeviceId")
            or ""
        ).strip(),
        "client_name": client_name,
        "detection_text": detection_text,
    }


async def log_blocked_request(
    user_id: str = None,
    user_name: str = None,
    session_id: str = None,
    client_name: str = None,
    tg_id: int = None,
    block_success: bool = False,
):
    """记录被拦截的请求"""
    try:
        action = "拦截可疑请求"
        block_action = "封禁用户" if block_success else "不封禁用户"
        log_message = (
            f"🚫 {action}\n"
            f"用户ID: {user_id or 'Unknown'}\n"
            f"用户名称: {user_name or 'Unknown'}\n"
            f"会话ID: {session_id or 'Unknown'}\n"
            f"客户端: {client_name or 'Unknown'}\n"
            f"TG ID: {tg_id or 'Unknown'}\n"
            f"是否封禁用户: {block_action}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        LOGGER.warning(log_message)

        # 如果配置了管理员群组，发送通知
        if hasattr(config, "group") and config.group:
            try:
                await bot.send_message(chat_id=config.group[0], text=log_message)
            except Exception as e:
                LOGGER.error(f"发送拦截通知失败: {str(e)}")

    except Exception as e:
        LOGGER.error(f"记录拦截请求失败: {str(e)}")


async def terminate_blocked_session(session_id: str, client_name: str) -> bool:
    """终止被拦截的会话"""
    try:
        reason = f"检测到可疑客户端: {client_name}"
        success = await emby.terminate_session(session_id, reason)
        if success:
            LOGGER.info(f"成功终止可疑会话 {session_id}")
        else:
            LOGGER.error(f"终止会话失败 {session_id}")
        return success
    except Exception as e:
        LOGGER.error(f"终止会话异常 {session_id}: {str(e)}")
        return False


async def revoke_blocked_device(device_id: str, client_name: str) -> bool:
    """删除违规设备登录态，防止客户端立即复用旧 token 重连。"""
    try:
        if not device_id:
            return False
        success = await emby.delete_device(device_id)
        if success:
            LOGGER.info(f"成功移除违规设备登录态 {device_id} ({client_name})")
        else:
            LOGGER.error(f"移除违规设备登录态失败 {device_id} ({client_name})")
        return success
    except Exception as e:
        LOGGER.error(f"移除违规设备登录态异常 {device_id}: {str(e)}")
        return False


@router.post("/webhook/client-filter")
async def handle_client_filter_webhook(request: Request):
    """处理Emby用户代理拦截webhook"""
    try:
        # 检查Content-Type
        content_type = request.headers.get("content-type", "").lower()

        if "application/json" in content_type:
            # 处理JSON格式
            webhook_data = await request.json()
        else:
            # 处理form-data格式
            form_data = await request.form()
            form = dict(form_data)
            webhook_data = json.loads(form["data"]) if "data" in form else None

        if not webhook_data:
            return {"status": "error", "message": "No data received"}

        ctx = _extract_client_context(webhook_data)
        event = ctx["event"]

        # 只处理播放相关事件
        if event not in [
            "user.authenticated",
            "user.authenticationfailed",
            "playback.start",
            "playback.progress",
            "playback.stop",
            "session.start",
            "session.created",
        ]:
            return {
                "status": "ignored",
                "message": "Not listen event",
                "event": event,
            }

        user_name = ctx["user_name"]
        emby_id = ctx["emby_id"]
        session_id = ctx["session_id"]
        device_id = ctx["device_id"]
        client_name = ctx["client_name"]
        detection_text = ctx["detection_text"]

        if not detection_text:
            return {"status": "ignored", "message": "No Client info found", "event": event}

        # 检查Client是否被拦截
        is_blocked = await is_client_blocked(detection_text)

        if is_blocked:
            # 根据配置决定是否终止会话
            terminated = False
            revoked = False
            if getattr(config, "client_filter_terminate_session", True):
                if session_id:
                    terminated = await terminate_blocked_session(session_id, client_name or detection_text)
                if device_id:
                    revoked = await revoke_blocked_device(device_id, client_name or detection_text)
            block_success = False

            user_details = sql_get_emby(emby_id) if emby_id else None
            if getattr(config, "client_filter_block_user", False) and emby_id:
                block_success = await emby.emby_change_policy(emby_id=emby_id, disable=True)
                if block_success:
                    if user_details:
                        sql_update_emby(Emby.tg == user_details.tg, lv="c")

            # 记录拦截信息
            await log_blocked_request(
                user_id=emby_id,
                user_name=user_name,
                session_id=session_id,
                client_name=detection_text,
                tg_id=user_details.tg if user_details else None,
                block_success=block_success,
            )

            return {
                "status": "blocked",
                "message": "Client blocked",
                "data": {
                    "user_id": emby_id,
                    "user_name": user_name,
                    "session_id": session_id,
                    "device_id": device_id,
                    "client_name": client_name or detection_text,
                    "matched_text": detection_text,
                    "terminated": terminated,
                    "revoked": revoked,
                    "user_details": {
                        "tg": user_details.tg,
                        "embyid": user_details.embyid,
                        "name": user_details.name,
                    } if user_details else None,
                    "event": event,
                    "timestamp": datetime.now().isoformat(),
                },
            }

        return {
            "status": "allowed",
            "message": "Client allowed",
            "data": {"client": client_name, "user_id": emby_id, "event": event},
        }

    except Exception as e:
        LOGGER.error(f"处理Client拦截webhook失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Webhook处理失败: {str(e)}")
