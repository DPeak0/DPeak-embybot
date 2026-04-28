"""
管理员认证模块
- GET  /admin/login   登录页
- POST /admin/login   提交登录（Emby 管理员账号验证）
- GET  /admin/logout  登出
- require_admin       FastAPI Depends，校验 session
"""
import aiohttp
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from bot import emby_url, LOGGER
from bot.sql_helper.sql_audit import log_audit

router = APIRouter()

_tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=_tpl_dir)


async def _verify_emby_admin(username: str, password: str) -> dict:
    """
    调用 Emby API 验证账号密码，并确认 IsAdministrator。
    成功返回用户信息 dict，失败返回 None。
    """
    url = f"{emby_url.rstrip('/')}/emby/Users/AuthenticateByName"
    headers = {
        "X-Emby-Authorization": (
            'MediaBrowser Client="DPeakEmby Admin", Device="Web", '
            'DeviceId="sakura-admin", Version="1.0.0"'
        ),
        "Content-Type": "application/json",
    }
    payload = {"Username": username, "Pw": password}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                user = data.get("User", {})
                policy = user.get("Policy", {})
                if not policy.get("IsAdministrator", False):
                    return None
                return {
                    "user_id": user.get("Id", ""),
                    "username": user.get("Name", username),
                    "access_token": data.get("AccessToken", ""),
                }
    except Exception as e:
        LOGGER.error(f"【Admin】Emby 认证异常: {e}")
        return None


def require_admin(request: Request) -> dict:
    """FastAPI Depends：要求已登录的管理员 session，否则重定向到登录页"""
    admin = request.session.get("admin")
    if not admin:
        # 返回重定向响应
        from fastapi import HTTPException
        raise HTTPException(
            status_code=303,
            headers={"Location": "/admin/login"},
            detail="请先登录"
        )
    return admin


# ── 登录页 ─────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if request.session.get("admin"):
        return RedirectResponse("/admin/", status_code=302)
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": error})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")
    if not username or not password:
        return RedirectResponse("/admin/login?error=请填写用户名和密码", status_code=303)

    user_info = await _verify_emby_admin(username, password)
    if not user_info:
        return RedirectResponse("/admin/login?error=用户名或密码错误，或账号不是管理员", status_code=303)

    request.session["admin"] = user_info
    ip = request.client.host if request.client else None
    log_audit(category="login", action="login", source="web",
              operator_name=user_info["username"], ip=ip,
              detail=f"管理员 {user_info['username']} 登录成功")
    LOGGER.info(f"【Admin】管理员 {username} 登录成功")
    return RedirectResponse("/admin/", status_code=302)


# ── 登出 ───────────────────────────────────────────────────────────────────────

@router.get("/logout")
async def logout(request: Request):
    admin = request.session.get("admin")
    if admin:
        ip = request.client.host if request.client else None
        log_audit(category="login", action="logout", source="web",
                  operator_name=admin.get("username"), ip=ip,
                  detail=f"管理员 {admin.get('username')} 登出")
    request.session.pop("admin", None)
    return RedirectResponse("/admin/login", status_code=302)
