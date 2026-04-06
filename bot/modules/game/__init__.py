"""
修仙游戏模块 — 注册所有回调 handler
"""
# 导入各子模块以注册 Pyrogram handlers
from bot.modules.game import cultivation    # noqa: F401 — 修行+商城+排行+主菜单
from bot.modules.game import breakthrough   # noqa: F401 — 境界突破
from bot.modules.game import inventory      # noqa: F401 — 背包
from bot.modules.game import raid           # noqa: F401 — 团本系统

# 初始化游戏数据
from bot.modules.game.game_data import seed_game_data
seed_game_data()
