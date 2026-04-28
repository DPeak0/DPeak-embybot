from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


DEFAULT_USER_AGENT = "python-requests/2.31.0"


class HDHiveOpenAPIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        description: str = "",
        *,
        status_code: Optional[int] = None,
        headers: Optional[dict[str, Any]] = None,
        response_data: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(description or message or code)
        self.code = code
        self.message = message
        self.description = description
        self.status_code = status_code
        self.headers = headers or {}
        self.response_data = response_data or {}
        self.retry_after = self.headers.get("Retry-After")
        self.limit_scope = self.response_data.get("limit_scope")
        self.retry_after_seconds = self.response_data.get("retry_after_seconds")


@dataclass
class HDHiveClient:
    base_url: str
    api_key: str
    access_token: Optional[str] = None
    timeout: int = 30
    user_agent: str = DEFAULT_USER_AGENT

    def with_access_token(self, token: str) -> "HDHiveClient":
        self.access_token = token
        return self

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/open/ping")

    def get_quota(self) -> dict[str, Any]:
        return self._request("GET", "/api/open/quota")

    def get_usage_today(self) -> dict[str, Any]:
        return self._request("GET", "/api/open/usage/today")

    def query_resources(self, media_type: str, tmdb_id: str) -> dict[str, Any]:
        path = "/api/open/resources/{}/{}".format(
            urllib.parse.quote(media_type, safe=""),
            urllib.parse.quote(tmdb_id, safe=""),
        )
        return self._request("GET", path)

    def unlock_resource(self, slug: str) -> dict[str, Any]:
        return self._request("POST", "/api/open/resources/unlock", {"slug": slug})

    def _decode_json_response(
        self,
        raw: bytes,
        *,
        status_code: Optional[int] = None,
        headers: Optional[dict[str, Any]] = None,
        fallback_message: str = "HDHive 返回了非 JSON 响应",
    ) -> dict[str, Any]:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            raise HDHiveOpenAPIError(
                "empty_response",
                fallback_message,
                "影巢接口返回了空响应，可能是上游服务异常或反代拦截。",
                status_code=status_code,
                headers=headers,
                response_data={"raw_preview": ""},
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            preview = text[:300]
            description = (
                f"影巢返回了无法解析的内容，可能不是 JSON。"
                f" Content-Type={headers.get('Content-Type', '') if headers else ''}"
                f" Body={preview}"
            )
            raise HDHiveOpenAPIError(
                "invalid_json",
                fallback_message,
                description,
                status_code=status_code,
                headers=headers,
                response_data={
                    "raw_preview": preview,
                    "cloudflare_error": "<html" in text.lower() or "cloudflare" in text.lower(),
                },
            ) from exc

    def _request(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if not self.base_url:
            raise ValueError("base_url is required")
        if not self.api_key:
            raise ValueError("api_key is required")

        url = self.base_url.rstrip("/") + path
        payload = None
        headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": self.user_agent or DEFAULT_USER_AGENT,
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_headers = dict(response.headers.items()) if response.headers else {}
                return self._decode_json_response(
                    response.read(),
                    status_code=getattr(response, "status", None),
                    headers=response_headers,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            headers = dict(exc.headers.items()) if exc.headers else {}
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                raise HDHiveOpenAPIError(
                    str(exc.code),
                    exc.reason,
                    raw,
                    status_code=exc.code,
                    headers=headers,
                ) from exc
            raise HDHiveOpenAPIError(
                str(data.get("code", data.get("error_code", exc.code))),
                str(data.get("message", data.get("title", exc.reason))),
                str(data.get("description") or data.get("detail") or data.get("title") or ""),
                status_code=exc.code,
                headers=headers,
                response_data=data,
            ) from exc
