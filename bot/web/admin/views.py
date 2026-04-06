"""
页面路由（服务端渲染，返回 Jinja2 模板）
GET /admin/            → dashboard
GET /admin/requests    → 求片管理
GET /admin/users       → 用户管理
GET /admin/settings    → 系统设置
"""
import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .auth import require_admin

router = APIRouter()

_tpl_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
templates = Jinja2Templates(directory=_tpl_dir)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "admin": admin,
        "page": "dashboard",
    })


@router.get("/requests", response_class=HTMLResponse)
async def admin_requests(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/requests.html", {
        "request": request,
        "admin": admin,
        "page": "requests",
    })


@router.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "admin": admin,
        "page": "users",
    })


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/settings.html", {
        "request": request,
        "admin": admin,
        "page": "settings",
    })


@router.get("/audit", response_class=HTMLResponse)
async def admin_audit(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/audit.html", {
        "request": request,
        "admin": admin,
        "page": "audit",
    })


@router.get("/codes", response_class=HTMLResponse)
async def admin_codes(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/codes.html", {
        "request": request,
        "admin": admin,
        "page": "codes",
    })


@router.get("/commands", response_class=HTMLResponse)
async def admin_commands(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/commands.html", {
        "request": request,
        "admin": admin,
        "page": "commands",
    })


@router.get("/game", response_class=HTMLResponse)
async def admin_game(request: Request, admin=Depends(require_admin)):
    return templates.TemplateResponse("admin/game.html", {
        "request": request,
        "admin": admin,
        "page": "game",
    })
