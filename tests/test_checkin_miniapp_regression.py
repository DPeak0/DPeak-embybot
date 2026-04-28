import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
MINIAPP_API = ROOT / "bot" / "web" / "miniapp_api.py"
CHECKIN_HTML = ROOT / "bot" / "web" / "templates" / "checkin_miniapp.html"
SQL_AUDIT = ROOT / "bot" / "sql_helper" / "sql_audit.py"


class CheckinMiniAppRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_source = MINIAPP_API.read_text(encoding="utf-8")
        cls.html_source = CHECKIN_HTML.read_text(encoding="utf-8")
        cls.audit_source = SQL_AUDIT.read_text(encoding="utf-8")

    def test_backend_exposes_checkin_overview_from_audit_logs(self):
        self.assertIn("def get_user_checkin_logs", self.audit_source)
        self.assertIn('@router.get("/checkin_bootstrap")', self.api_source)
        self.assertIn('@router.post("/checkin_bootstrap")', self.api_source)
        self.assertIn('async def miniapp_checkin_bootstrap(request: Request):', self.api_source)
        self.assertIn("def _build_checkin_auth_payload", self.api_source)
        self.assertIn("def _build_checkin_status_payload", self.api_source)
        self.assertIn('@router.get("/checkin_overview")', self.api_source)
        self.assertIn('async def miniapp_checkin_overview(request: Request, month: str = "")', self.api_source)
        self.assertIn('"overview": _build_checkin_overview_payload(tg_id, month)', self.api_source)
        self.assertIn('"overview": _build_checkin_overview_payload(tg_id),', self.api_source)
        self.assertIn("def _build_checkin_overview_payload", self.api_source)
        self.assertIn("def _resolve_checkin_month", self.api_source)
        self.assertIn("def _calc_max_checkin_streak", self.api_source)
        self.assertIn('"max_streak": max_monthly_streak,', self.api_source)
        self.assertIn('"checked_days": checked_days,', self.api_source)
        self.assertIn('"records": monthly_records,', self.api_source)
        self.assertIn('cache_control="no-store", use_cache=False', self.api_source)

    def test_checkin_page_uses_month_overview_and_records_modal(self):
        self.assertIn('class="overview-card"', self.html_source)
        self.assertIn('id="rewardRange"', self.html_source)
        self.assertIn('id="rewardRangeLabel"', self.html_source)
        self.assertIn('id="monthChecked"', self.html_source)
        self.assertIn('id="monthMaxStreak"', self.html_source)
        self.assertIn('id="monthRewardTotal"', self.html_source)
        self.assertIn('id="recordsOverlay"', self.html_source)
        self.assertIn('id="recordsMonthTrigger"', self.html_source)
        self.assertIn('id="recordsMonthPanel"', self.html_source)
        self.assertIn('id="recordsMonthGrid"', self.html_source)
        self.assertIn('id="recordsMonthYear"', self.html_source)
        self.assertIn('>本月</button>', self.html_source)
        self.assertIn("function renderCheckinOverview(overview)", self.html_source)
        self.assertIn("function resolveTodayReward(overview)", self.html_source)
        self.assertIn("function renderRecords(", self.html_source)
        self.assertIn("async function openRecordsModal()", self.html_source)
        self.assertIn("async function applyRecordsMonth(month = '')", self.html_source)
        self.assertIn("async function loadLegacyCheckinBootstrap()", self.html_source)
        self.assertIn("function loadRecordsOverview(month = '')", self.html_source)
        self.assertIn("function toggleRecordsMonthPanel(force)", self.html_source)
        self.assertIn("function shiftRecordsPickerYear(delta)", self.html_source)
        self.assertIn("async function goToCurrentRecordsMonth()", self.html_source)
        self.assertIn("function getCurrentMonthValue()", self.html_source)
        self.assertIn("async function selectRecordsMonth(month)", self.html_source)
        self.assertIn("function renderRecordsMonthOptions()", self.html_source)
        self.assertIn("fetch('/miniapp/checkin_bootstrap', {", self.html_source)
        self.assertIn("method: 'POST'", self.html_source)
        self.assertIn("fetch(`/miniapp/checkin_overview${query}`", self.html_source)
        self.assertIn('onclick="toggleRecordsMonthPanel()"', self.html_source)
        self.assertIn("function syncRecordsMonthPicker(month)", self.html_source)
        self.assertIn("async function loadCheckinOverview(month = '')", self.html_source)
        self.assertNotIn('id="calendarCard"', self.html_source)
        self.assertNotIn('id="creditsVal"', self.html_source)
        self.assertNotIn('records-apply', self.html_source)
        self.assertNotIn('id="recordsMonthLabel"', self.html_source)
        self.assertNotIn('records-filter', self.html_source)
        self.assertNotIn('type="month"', self.html_source)
        self.assertNotIn('fonts.googleapis.com', self.html_source)
        self.assertNotIn('cdnjs.cloudflare.com', self.html_source)
        self.assertIn("fetch('/miniapp/auth'", self.html_source)
        self.assertIn("fetch('/miniapp/checkin_status'", self.html_source)


if __name__ == "__main__":
    unittest.main()
