import re
import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
MINIAPP_API = ROOT / "bot" / "web" / "miniapp_api.py"
MINIAPP_HTML = ROOT / "bot" / "web" / "templates" / "miniapp.html"
MINIAPP_NOTIFY = ROOT / "bot" / "web" / "miniapp_notify.py"
WEB_INIT = ROOT / "bot" / "web" / "__init__.py"
TMDB_SCHED = ROOT / "bot" / "scheduler" / "prewarm_tmdb_cache.py"


class MiniAppTmdbRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_source = MINIAPP_API.read_text(encoding="utf-8")
        cls.html_source = MINIAPP_HTML.read_text(encoding="utf-8")
        cls.notify_source = MINIAPP_NOTIFY.read_text(encoding="utf-8")
        cls.web_init_source = WEB_INIT.read_text(encoding="utf-8")
        cls.tmdb_sched_source = TMDB_SCHED.read_text(encoding="utf-8")

    def test_tmdb_api_uses_reachable_domain(self):
        self.assertIn('TMDB_BASE = "https://api.tmdb.org/3"', self.api_source)
        self.assertNotIn("api.themoviedb.org/3", self.api_source)
        self.assertIn("TMDB_SEARCH_TTL = 600", self.api_source)
        self.assertIn("TMDB_TRENDING_TTL = 1800", self.api_source)
        self.assertIn("TMDB_MIN_QUERY_LENGTH = 2", self.api_source)
        self.assertIn("TMDB_IMAGE_TTL = 604800", self.api_source)
        self.assertIn("def _tmdb_get_json", self.api_source)
        self.assertIn("def _split_tmdb_query_year", self.api_source)
        self.assertIn("def _build_tmdb_search_context", self.api_source)
        self.assertIn('return f"/miniapp/tmdb_image?path={quote(str(poster_path), safe=\'\')}&w={safe_width}"', self.api_source)
        self.assertIn('headers={"Cache-Control": f"public, max-age={TMDB_IMAGE_TTL}"}', self.api_source)

    def test_search_endpoint_keeps_network_fallback(self):
        self.assertIn('@router.get("/search")', self.api_source)
        self.assertIn('search_ctx = _build_tmdb_search_context(q)', self.api_source)
        self.assertIn('if len(search_ctx["normalized_title"] or normalized_q) < TMDB_MIN_QUERY_LENGTH', self.api_source)
        self.assertIn('cache_key = f"tmdb:search:zh-CN:{search_ctx[\'cache_key\']}"', self.api_source)
        self.assertIn('"query": search_ctx["request_query"]', self.api_source)
        self.assertIn('return JSONResponse({"results": [], "error": "TMDB网络不可达"})', self.api_source)

    def test_trending_endpoint_keeps_network_fallback(self):
        self.assertIn('@router.get("/trending")', self.api_source)
        self.assertIn('cache_key = "tmdb:trending:all:week:zh-CN"', self.api_source)
        self.assertIn('return JSONResponse({"results": [], "error": "TMDB网络不可达"})', self.api_source)
        self.assertIn("async def prewarm_tmdb_hot_cache(force_refresh: bool = True)", self.api_source)
        self.assertIn("await _prefetch_tmdb_images_from_results(data, limit=12, width=300)", self.api_source)

    def test_request_page_shows_graceful_empty_state(self):
        self.assertIn("const resp = await fetch('/miniapp/trending'", self.html_source)
        self.assertIn("影视数据暂不可用", self.html_source)
        self.assertIn("加载失败", self.html_source)
        self.assertIn("const searchCache = new Map()", self.html_source)
        self.assertIn("function normalizeSearchCacheKey(q)", self.html_source)
        self.assertIn("请输入至少 2 个字符后再搜索", self.html_source)
        self.assertIn("const cacheKey = normalizeSearchCacheKey(normalizedQ);", self.html_source)
        self.assertIn("searchCache.set(cacheKey, data.results || []);", self.html_source)
        self.assertIn("setTimeout(() => doSearch(q), 700)", self.html_source)

    def test_bootstrap_endpoint_and_frontend_fast_path_exist(self):
        self.assertIn('@router.post("/bootstrap")', self.api_source)
        self.assertIn("status_map, trending_payload = await asyncio.gather(", self.api_source)
        self.assertIn("payload[\"trending\"] = trending_payload.get(\"results\", [])", self.api_source)
        self.assertIn("async function initBootstrap()", self.html_source)
        self.assertIn("const resp = await fetch('/miniapp/bootstrap', { method: 'POST', headers: apiHeaders() });", self.html_source)
        self.assertIn("loadMyStatus();", self.html_source)

    def test_static_html_and_emby_checks_are_cached_or_batched(self):
        self.assertIn("@lru_cache(maxsize=8)", self.api_source)
        self.assertIn("def _render_static_html", self.api_source)
        self.assertIn("_STATIC_HTML_CACHE_CONTROL = \"public, max-age=300\"", self.api_source)
        self.assertIn("async def bulk_check_in_emby_by_tmdb", self.notify_source)
        self.assertIn("library_map = await bulk_check_in_emby_by_tmdb(list(groups.keys()))", self.notify_source)

    def test_miniapp_profile_includes_request_quota_info(self):
        self.assertIn("def _get_request_quota_info", self.api_source)
        self.assertIn('"request_quota_remaining": remaining', self.api_source)
        self.assertIn('"request_credit_cost": request_credit_cost', self.api_source)

    def test_request_page_renders_quota_and_second_confirmation(self):
        self.assertNotIn('id="requestQuotaSummary"', self.html_source)
        self.assertNotIn("function renderRequestQuotaSummary()", self.html_source)
        self.assertIn("提交后将消耗 <strong style=\"color:var(--warning);\">${requestCost}</strong>", self.html_source)
        self.assertIn("本次将消耗 ${requestCost}", self.html_source)
        self.assertIn("并占用 1 次求片额度", self.html_source)

    def test_request_status_syncs_with_emby_and_only_mentions_library_notification(self):
        self.assertIn("sync_pending_requests_by_tmdb_ids", self.notify_source)
        self.assertIn("sql_get_incomplete_requests_by_tmdb_ids", self.notify_source)
        self.assertIn("sql_get_incomplete_requests()", self.notify_source)
        self.assertIn("pending_tmdb_ids", self.api_source)
        self.assertIn('await sync_pending_requests_by_tmdb_ids(pending_tmdb_ids)', self.api_source)
        self.assertIn('status in {"pending", "processing", "rejected"}', self.api_source)
        self.assertIn("处理结果将通过 Bot 通知您", self.api_source)

    def test_completed_notifications_include_media_poster_and_brief(self):
        self.assertIn("async def send_request_completed_notification(", self.notify_source)
        self.assertIn("await _resolve_emby_media_item(", self.notify_source)
        self.assertIn('info_parts.append(f"大小 {size_text}")', self.notify_source)
        self.assertIn('info_parts.append(f"分辨率 {resolution_text}")', self.notify_source)
        self.assertIn('info_parts.append(f"码率 {bitrate_text}")', self.notify_source)
        self.assertIn("await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)", self.notify_source)
        self.assertIn('lines = ["🎉 **已入库**"]', self.notify_source)

    def test_tmdb_prewarm_is_hooked_to_startup_and_scheduler(self):
        self.assertIn("self.app.add_event_handler(\"startup\", prewarm_tmdb_hot_cache)", self.web_init_source)
        self.assertIn("scheduler.add_job(", self.tmdb_sched_source)
        self.assertIn('id="prewarm_tmdb_hot_cache"', self.tmdb_sched_source)
        self.assertIn('hour="*/6"', self.tmdb_sched_source)
        self.assertIn("loop.call_later(20, lambda: loop.create_task(scheduled_prewarm_tmdb_cache()))", self.tmdb_sched_source)


if __name__ == "__main__":
    unittest.main()
