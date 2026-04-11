import re
import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
MINIAPP_API = ROOT / "bot" / "web" / "miniapp_api.py"
MINIAPP_HTML = ROOT / "bot" / "web" / "templates" / "miniapp.html"


class MiniAppTmdbRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api_source = MINIAPP_API.read_text(encoding="utf-8")
        cls.html_source = MINIAPP_HTML.read_text(encoding="utf-8")

    def test_tmdb_api_uses_reachable_domain(self):
        self.assertIn('TMDB_BASE = "https://api.tmdb.org/3"', self.api_source)
        self.assertNotIn("api.themoviedb.org/3", self.api_source)

    def test_search_endpoint_keeps_network_fallback(self):
        self.assertRegex(
            self.api_source,
            re.compile(
                r'@router\.get\("/search"\).*?except Exception:\s+'
                r'return JSONResponse\(\{"results": \[\], "error": "TMDB网络不可达"\}\)',
                re.S,
            ),
        )

    def test_trending_endpoint_keeps_network_fallback(self):
        self.assertRegex(
            self.api_source,
            re.compile(
                r'@router\.get\("/trending"\).*?except Exception:\s+'
                r'return JSONResponse\(\{"results": \[\], "error": "TMDB网络不可达"\}\)',
                re.S,
            ),
        )

    def test_request_page_shows_graceful_empty_state(self):
        self.assertIn("const resp = await fetch('/miniapp/trending'", self.html_source)
        self.assertIn("影视数据暂不可用", self.html_source)
        self.assertIn("加载失败", self.html_source)


if __name__ == "__main__":
    unittest.main()
