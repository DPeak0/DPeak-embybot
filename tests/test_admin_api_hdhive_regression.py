import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
SDK_PY = ROOT / "bot" / "integrations" / "hdhive_openapi.py"
SCHEMAS_PY = ROOT / "bot" / "schemas" / "schemas.py"
API_SETTINGS_PY = ROOT / "bot" / "web" / "admin" / "api_settings.py"
API_REQUESTS_PY = ROOT / "bot" / "web" / "admin" / "api_requests.py"
SETTINGS_HTML = ROOT / "bot" / "web" / "templates" / "admin" / "settings.html"
REQUESTS_HTML = ROOT / "bot" / "web" / "templates" / "admin" / "requests.html"


class AdminApiAndHDHiveRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas_source = SCHEMAS_PY.read_text(encoding="utf-8")
        cls.sdk_source = SDK_PY.read_text(encoding="utf-8")
        cls.api_settings_source = API_SETTINGS_PY.read_text(encoding="utf-8")
        cls.api_requests_source = API_REQUESTS_PY.read_text(encoding="utf-8")
        cls.settings_html = SETTINGS_HTML.read_text(encoding="utf-8")
        cls.requests_html = REQUESTS_HTML.read_text(encoding="utf-8")

    def test_schema_tracks_hdhive_settings(self):
        self.assertIn('hdhive_base_url: Optional[str] = "https://hdhive.com"', self.schemas_source)
        self.assertIn('hdhive_api_key: Optional[str] = "1d1a58d25cd7ccfec8e3da685e45821a"', self.schemas_source)
        self.assertIn('cms_base_url: Optional[str] = "https://cms.dpeak.cn"', self.schemas_source)
        self.assertIn('cms_api_token: Optional[str] = ""', self.schemas_source)

    def test_admin_settings_exposes_api_fields(self):
        for needle in [
            '"api_status": getattr(config.api, "status", False)',
            '"api_http_url": getattr(config.api, "http_url", "0.0.0.0")',
            '"api_http_port": getattr(config.api, "http_port", 8838)',
            '"api_allow_origins": ", ".join(getattr(config.api, "allow_origins", ["*"]) or ["*"])',
            '"hdhive_base_url": getattr(config, "hdhive_base_url", "https://hdhive.com") or "https://hdhive.com"',
            '"hdhive_api_key": getattr(config, "hdhive_api_key", "") or ""',
            '"cms_base_url": getattr(config, "cms_base_url", "https://cms.dpeak.cn") or "https://cms.dpeak.cn"',
            '"cms_api_token": getattr(config, "cms_api_token", "") or ""',
            '"request_credit_cost": getattr(config.open, "request_credit_cost", 0)',
        ]:
            self.assertIn(needle, self.api_settings_source)

    def test_admin_settings_template_has_api_section(self):
        for needle in [
            'href="#sec-api"',
            'id="sec-api"',
            'id="api_status_btn"',
            'id="api_http_url"',
            'id="api_http_port"',
            'id="api_allow_origins"',
            'id="tmdb_api_key"',
            'id="hdhive_base_url"',
            'id="hdhive_api_key"',
            'id="cms_base_url"',
            'id="cms_api_token"',
            'id="request_credit_cost"',
            'function applySettings(s)',
            'if (data.settings) applySettings(data.settings);',
        ]:
            self.assertIn(needle, self.settings_html)

    def test_sdk_preserves_rate_limit_context(self):
        for needle in [
            'DEFAULT_USER_AGENT = "python-requests/2.31.0"',
            '"User-Agent": self.user_agent or DEFAULT_USER_AGENT',
            "self.retry_after = self.headers.get(\"Retry-After\")",
            'self.limit_scope = self.response_data.get("limit_scope")',
            'self.retry_after_seconds = self.response_data.get("retry_after_seconds")',
            'str(data.get("code", data.get("error_code", exc.code)))',
            'str(data.get("description") or data.get("detail") or data.get("title") or "")',
            "headers=headers",
            "response_data=data",
        ]:
            self.assertIn(needle, self.sdk_source)

    def test_sdk_handles_non_json_success_responses_gracefully(self):
        for needle in [
            "def _decode_json_response(",
            '"empty_response"',
            '"invalid_json"',
            '"raw_preview": preview',
            '"cloudflare_error": "<html" in text.lower() or "cloudflare" in text.lower()',
            "return self._decode_json_response(",
            "fallback_message: str = \"HDHive 返回了非 JSON 响应\"",
        ]:
            self.assertIn(needle, self.sdk_source)

    def test_requests_api_has_hdhive_lookup_route(self):
        self.assertIn('@router.get("/api/requests/{request_id}/hdhive")', self.api_requests_source)
        self.assertIn('@router.post("/api/requests/sync_status")', self.api_requests_source)
        self.assertIn("from bot.integrations.hdhive_openapi import HDHiveClient, HDHiveOpenAPIError", self.api_requests_source)
        self.assertIn("from bot.web.miniapp_notify import (", self.api_requests_source)
        self.assertIn("send_request_completed_notification", self.api_requests_source)
        self.assertIn("def _normalize_hdhive_query", self.api_requests_source)
        self.assertIn("def _query_hdhive_resources_sync", self.api_requests_source)
        self.assertIn("return client.query_resources(media_type, tmdb_id)", self.api_requests_source)
        self.assertIn("def _unlock_hdhive_resource_sync", self.api_requests_source)
        self.assertIn("def _cms_add_share_download", self.api_requests_source)
        self.assertIn('@router.post("/api/requests/{request_id}/hdhive/transfer")', self.api_requests_source)
        self.assertIn('threading.Thread(', self.api_requests_source)
        self.assertIn('cms_transfer_pending', self.api_requests_source)
        self.assertIn("return JSONResponse(error_payload, status_code=status_code)", self.api_requests_source)
        self.assertIn("\"retry_after\": headers.get(\"Retry-After\")", self.api_requests_source)
        self.assertIn('"query_media_type": media_type', self.api_requests_source)
        self.assertIn('"query_tmdb_id": tmdb_id', self.api_requests_source)
        self.assertIn('"pan_type": item.get("pan_type") or ""', self.api_requests_source)
        self.assertIn('"share_size": item.get("share_size") or ""', self.api_requests_source)
        self.assertIn('"subtitle_language": item.get("subtitle_language") or []', self.api_requests_source)
        self.assertIn('"is_unlocked": bool(item.get("is_unlocked"))', self.api_requests_source)
        self.assertIn('"total": (payload.get("meta") or {}).get("total", len(items))', self.api_requests_source)
        self.assertIn("await sync_all_incomplete_requests()", self.api_requests_source)
        self.assertIn("await sync_pending_requests_by_tmdb_ids(pending_tmdb_ids)", self.api_requests_source)
        self.assertIn('f"已完成真实状态刷新，本次同步 {synced} 条申请"', self.api_requests_source)
        self.assertIn('return f"/miniapp/tmdb_image?path={urllib.parse.quote(poster_path, safe=\'\')}&w=300"', self.api_requests_source)

    def test_requests_notifications_skip_approve_only(self):
        self.assertIn('"""审批通过：status → processing（仅改状态，不通知用户）"""', self.api_requests_source)
        self.assertIn('"""拒绝：status → rejected，通知用户"""', self.api_requests_source)
        self.assertIn('return JSONResponse({"ok": True, "msg": "已拒绝并通知用户"})', self.api_requests_source)
        self.assertIn("# approve 不通知；complete / reject 才发送最终结果通知", self.api_requests_source)
        self.assertIn("await send_request_completed_notification(", self.api_requests_source)

    def test_requests_template_has_hdhive_button(self):
        self.assertIn("真实状态刷新", self.requests_html)
        self.assertIn("syncRequestStatuses()", self.requests_html)
        self.assertIn("toggleHDHivePanel", self.requests_html)
        self.assertIn("查询影巢", self.requests_html)
        self.assertIn("影巢查询中", self.requests_html)
        self.assertIn("buildHDHivePanel", self.requests_html)
        self.assertIn("请求参数", self.requests_html)
        self.assertIn("ray_id", self.requests_html)
        self.assertIn("function joinValues", self.requests_html)
        self.assertIn("function parseHDHiveSize", self.requests_html)
        self.assertIn("function getHDHiveTransferKind", self.requests_html)
        self.assertIn("function sortHDHiveItems", self.requests_html)
        self.assertIn("formatHDHivePanType", self.requests_html)
        self.assertIn("片源:", self.requests_html)
        self.assertIn("字幕:", self.requests_html)
        self.assertIn("submitHDHiveTransfer", self.requests_html)
        self.assertIn("解锁并转存", self.requests_html)
        self.assertIn("转存到CMS", self.requests_html)
        self.assertIn("综合排序", self.requests_html)
        self.assertIn("积分升序", self.requests_html)
        self.assertIn("大小降序", self.requests_html)
        self.assertIn("分辨率降序", self.requests_html)
        self.assertIn("仅显示 CMS 支持的 115分享、磁力链接、ed2k、阿里云盘分享", self.requests_html)


if __name__ == "__main__":
    unittest.main()
