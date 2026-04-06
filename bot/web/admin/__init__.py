"""
Admin 模块入口 - 聚合所有子路由
挂载到 /admin 前缀下
"""
from fastapi import APIRouter

from .auth import router as auth_router
from .views import router as views_router
from .api_requests import router as api_requests_router
from .api_users import router as api_users_router
from .api_dashboard import router as api_dashboard_router
from .api_settings import router as api_settings_router
from .api_audit import router as api_audit_router
from .api_codes import router as api_codes_router
from .api_commands import router as api_commands_router
from .api_game import router as api_game_router

admin_router = APIRouter(prefix="/admin", tags=["Admin"])

admin_router.include_router(auth_router)
admin_router.include_router(views_router)
admin_router.include_router(api_requests_router)
admin_router.include_router(api_users_router)
admin_router.include_router(api_dashboard_router)
admin_router.include_router(api_settings_router)
admin_router.include_router(api_audit_router)
admin_router.include_router(api_codes_router)
admin_router.include_router(api_commands_router)
admin_router.include_router(api_game_router)
