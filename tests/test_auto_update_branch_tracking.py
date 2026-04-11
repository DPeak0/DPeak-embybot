import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
CONFIG_JSON = ROOT / "config.json"
SCHEMAS_PY = ROOT / "bot" / "schemas" / "schemas.py"
SCHED_PANEL_PY = ROOT / "bot" / "modules" / "panel" / "sched_panel.py"


class AutoUpdateBranchTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_source = CONFIG_JSON.read_text(encoding="utf-8")
        cls.schemas_source = SCHEMAS_PY.read_text(encoding="utf-8")
        cls.sched_source = SCHED_PANEL_PY.read_text(encoding="utf-8")

    def test_config_tracks_main_branch(self):
        self.assertIn('"branch": "main"', self.config_source)

    def test_schema_defaults_to_main_branch(self):
        self.assertIn('branch: Optional[str] = "main"', self.schemas_source)

    def test_update_logic_uses_explicit_branch_for_github_and_git(self):
        self.assertIn('commit_url = f"https://api.github.com/repos/{auto_update.git_repo}/commits/{track_branch}"', self.sched_source)
        self.assertIn('await execute(f"git fetch origin {quoted_branch}")', self.sched_source)
        self.assertIn('await execute(f"git reset --hard origin/{quoted_branch}")', self.sched_source)
        self.assertIn('await execute(f"git pull --ff-only origin {quoted_branch}")', self.sched_source)
        self.assertNotIn("origin/master", self.sched_source)
        self.assertNotIn("git pull --all", self.sched_source)


if __name__ == "__main__":
    unittest.main()
