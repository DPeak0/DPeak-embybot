import unittest
from pathlib import Path


ROOT = Path("/dpeak/bot")
CLIENT_FILTER = ROOT / "bot" / "web" / "api" / "webhook" / "client_filter.py"
EMBY_HELPER = ROOT / "bot" / "func_helper" / "emby.py"


class ClientFilterRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_filter_source = CLIENT_FILTER.read_text(encoding="utf-8")
        cls.emby_helper_source = EMBY_HELPER.read_text(encoding="utf-8")

    def test_client_filter_extracts_multiple_payload_fields(self):
        self.assertIn("def _extract_client_context(webhook_data: dict) -> Dict[str, str]:", self.client_filter_source)
        self.assertIn('r".*网易爆米花.*"', self.client_filter_source)
        self.assertIn('r".*netease.*popcorn.*"', self.client_filter_source)
        self.assertIn('webhook_data.get("AppName")', self.client_filter_source)
        self.assertIn('session_info.get("DeviceName")', self.client_filter_source)
        self.assertIn('session_info.get("UserAgent")', self.client_filter_source)
        self.assertIn('detection_text = " | ".join(candidates)', self.client_filter_source)
        self.assertIn('session_info.get("UserId")', self.client_filter_source)
        self.assertIn('session_info.get("DeviceId")', self.client_filter_source)

    def test_client_filter_normalizes_events_and_supports_session_created(self):
        self.assertIn("def _normalize_event_name(event: str) -> str:", self.client_filter_source)
        self.assertIn('"session.created",', self.client_filter_source)
        self.assertIn('event = ctx["event"]', self.client_filter_source)

    def test_client_filter_revokes_device_and_keeps_json_serializable_response(self):
        self.assertIn("async def revoke_blocked_device(device_id: str, client_name: str) -> bool:", self.client_filter_source)
        self.assertIn("await emby.delete_device(device_id)", self.client_filter_source)
        self.assertIn('"matched_text": detection_text', self.client_filter_source)
        self.assertIn('"terminated": terminated', self.client_filter_source)
        self.assertIn('"revoked": revoked', self.client_filter_source)
        self.assertIn('"user_details": {', self.client_filter_source)
        self.assertNotIn('"user_details": user_details', self.client_filter_source)

    def test_emby_helper_uses_command_and_device_delete(self):
        self.assertIn("f'/emby/Sessions/{session_id}/Command'", self.emby_helper_source)
        self.assertIn('"Name": "DisplayMessage"', self.emby_helper_source)
        self.assertIn("async def delete_device(self, device_id: str) -> bool:", self.emby_helper_source)
        self.assertIn("await self._request('DELETE', f'/emby/Devices?Id={device_id}')", self.emby_helper_source)


if __name__ == "__main__":
    unittest.main()
