from __future__ import annotations

import os
import time
import math
from typing import Dict, Any, Optional, List

import requests

from ....constants.service_code import HTTP_STATUS_CODES


class TikTokAdapter:
    """
    TikTok Open API helper.

    Supports:
      - OAuth2 token exchange
      - Token refresh
      - User info fetch
      - Video direct post
      - Photo post
      - Upload (single or chunked)
      - Publish status polling
      - Webhook parsing
    """

    OPEN_API_BASE = os.getenv("TIKTOK_OPEN_API_BASE", "https://open.tiktokapis.com")

    # OAuth
    OAUTH_TOKEN_URL = f"{OPEN_API_BASE}/v2/oauth/token/"
    OAUTH_REFRESH_URL = f"{OPEN_API_BASE}/v2/oauth/token/refresh/"

    # User info
    USER_INFO_URL = f"{OPEN_API_BASE}/v2/user/info/"

    # Publishing
    VIDEO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/video/init/"
    PHOTO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/photo/init/"
    STATUS_FETCH_URL = f"{OPEN_API_BASE}/v2/post/publish/status/fetch/"

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse_json(cls, r: requests.Response) -> Dict[str, Any]:
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    @classmethod
    def _raise_if_error(cls, payload: Dict[str, Any], prefix: str):
        """
        TikTok ALWAYS includes `error` even on success.
        Only fail if error.code != ok.
        """
        err = payload.get("error") or {}
        code = err.get("code")

        if code in (None, "ok", 0, "0"):
            return

        raise Exception(f"{prefix}: {payload}")

    @classmethod
    def _headers_bearer(cls, access_token: str) -> Dict[str, str]:
        if not access_token:
            raise Exception("Missing TikTok access_token")

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    @classmethod
    def exchange_code_for_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:

        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        r = requests.post(cls.OAUTH_TOKEN_URL, json=payload, timeout=60)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok OAuth HTTP error: {data}")

        cls._raise_if_error(data, "TikTok OAuth failed")
        return data

    @classmethod
    def refresh_access_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        refresh_token: str,
    ) -> Dict[str, Any]:

        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        r = requests.post(cls.OAUTH_REFRESH_URL, json=payload, timeout=60)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok refresh HTTP error: {data}")

        cls._raise_if_error(data, "TikTok refresh failed")
        return data

    # ------------------------------------------------------------------
    # User info
    # ------------------------------------------------------------------

    @classmethod
    def get_user_info(cls, *, access_token: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        if not fields:
            fields = ["open_id", "union_id", "display_name", "avatar_url"]

        headers = cls._headers_bearer(access_token)
        params = {"fields": ",".join(fields)}

        r = requests.get(cls.USER_INFO_URL, headers=headers, params=params, timeout=60)
        payload = cls._parse_json(r)

        # Hard HTTP failure
        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok user info HTTP error: {payload}")

        # TikTok API returns { error: { code: "ok" } } on success
        err = (payload.get("error") or {})
        code = err.get("code")

        if code not in (None, "ok", 0, "0"):
            raise Exception(f"TikTok user info failed: {payload}")

        return payload
    # ------------------------------------------------------------------
    # VIDEO POSTING
    # ------------------------------------------------------------------

    @classmethod
    def init_video_post(
        cls,
        *,
        access_token: str,
        caption: str,
        video_size: int,
        chunk_size: Optional[int] = None,
        total_chunk_count: Optional[int] = None,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> Dict[str, Any]:

        headers = cls._headers_bearer(access_token)

        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
        }

        if chunk_size and total_chunk_count:
            source_info["chunk_size"] = chunk_size
            source_info["total_chunk_count"] = total_chunk_count

        payload = {
            "post_info": {
                "title": caption or "",
                "privacy_level": privacy_level,
            },
            "source_info": source_info,
        }

        r = requests.post(cls.VIDEO_INIT_URL, headers=headers, json=payload, timeout=60)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok init video HTTP error: {data}")

        cls._raise_if_error(data, "TikTok init video failed")
        return data

    # ------------------------------------------------------------------
    # PHOTO POSTING
    # ------------------------------------------------------------------

    @classmethod
    def init_photo_post(
        cls,
        *,
        access_token: str,
        caption: str,
        image_urls: List[str],
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> Dict[str, Any]:

        headers = cls._headers_bearer(access_token)

        payload = {
            "post_info": {
                "title": caption or "",
                "privacy_level": privacy_level,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_urls": image_urls,
            },
        }

        r = requests.post(cls.PHOTO_INIT_URL, headers=headers, json=payload, timeout=60)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok init photo HTTP error: {data}")

        cls._raise_if_error(data, "TikTok init photo failed")
        return data

    # ------------------------------------------------------------------
    # Upload helpers
    # ------------------------------------------------------------------

    @classmethod
    def upload_put_single(cls, *, upload_url: str, blob: bytes) -> Dict[str, Any]:

        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(blob)),
        }

        r = requests.put(upload_url, headers=headers, data=blob, timeout=300)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok upload PUT failed: {r.text[:500]}")

        return {
            "status_code": r.status_code,
            "etag": r.headers.get("etag"),
        }

    @classmethod
    def upload_put_chunked(
        cls,
        *,
        upload_url: str,
        blob: bytes,
        chunk_size: int,
    ) -> Dict[str, Any]:

        total = len(blob)
        start = 0

        while start < total:
            end = min(start + chunk_size, total) - 1
            part = blob[start:end + 1]

            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(part)),
                "Content-Range": f"bytes {start}-{end}/{total}",
            }

            r = requests.put(upload_url, headers=headers, data=part, timeout=300)

            if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
                raise Exception(f"TikTok chunk upload failed: {r.text[:500]}")

            start = end + 1

        return {"total_bytes": total}

    # ------------------------------------------------------------------
    # Status polling
    # ------------------------------------------------------------------

    @classmethod
    def fetch_post_status(cls, *, access_token: str, publish_id: str) -> Dict[str, Any]:

        headers = cls._headers_bearer(access_token)
        payload = {"publish_id": publish_id}

        r = requests.post(cls.STATUS_FETCH_URL, headers=headers, json=payload, timeout=60)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok status HTTP error: {data}")

        cls._raise_if_error(data, "TikTok fetch status failed")
        return data

    @classmethod
    def wait_for_publish(
        cls,
        *,
        access_token: str,
        publish_id: str,
        max_wait_seconds: int = 180,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:

        deadline = time.time() + max_wait_seconds
        last = {}

        while time.time() < deadline:
            last = cls.fetch_post_status(access_token=access_token, publish_id=publish_id)

            status = (last.get("data") or {}).get("status", "").lower()

            if status in ("published", "success", "succeeded"):
                return last

            if status in ("failed", "error"):
                return last

            time.sleep(poll_interval)

        return last

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    @classmethod
    def parse_webhook_event(cls, raw: Dict[str, Any]) -> Dict[str, Any]:

        if not isinstance(raw, dict):
            return {"type": None, "raw": raw}

        etype = raw.get("event") or raw.get("event_type") or raw.get("type")

        return {
            "type": etype,
            "raw": raw,
        }