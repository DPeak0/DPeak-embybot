import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
SQL_GAME = ROOT / "bot" / "sql_helper" / "sql_game.py"


class GameMigrationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SQL_GAME.read_text(encoding="utf-8")

    def test_realm_migrations_use_persistent_markers(self):
        self.assertIn("class GameMigrationMeta(Base):", self.source)
        self.assertIn("def _is_game_migration_applied(key: str) -> bool:", self.source)
        self.assertIn("def _mark_game_migration_applied(key: str, note: str = \"\") -> None:", self.source)
        self.assertIn('migration_key = "game_v7_realm_shift"', self.source)
        self.assertIn('migration_key = "game_v10_realm_expand"', self.source)
        self.assertIn("_is_game_migration_applied(migration_key)", self.source)
        self.assertIn("_mark_game_migration_applied(migration_key, \"skipped on empty realm config\")", self.source)
        self.assertIn("game_realm_config 为空，跳过 realm +1", self.source)
        self.assertIn("game_realm_config 为空，跳过旧境界 remap", self.source)

    def test_dangerous_realm_migrations_do_not_run_on_startup(self):
        self.assertNotIn("\n_migrate_game_v7()\n", self.source)
        self.assertNotIn("\n_migrate_game_v10()\n", self.source)
        self.assertIn("禁止在启动/重部署时自动执行", self.source)


if __name__ == "__main__":
    unittest.main()
