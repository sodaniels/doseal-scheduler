# app/services/social/adapters/tiktok_adapter.py

from __future__ import annotations

import os
import time
import math
from typing import Any, Dict, Optional, List

import requests

from ....constants.service_code import HTTP_STATUS_CODES


class TikTokAdapter:
    """
    TikTok Open API adapter.

    Supports:
      - OAuth refresh
      - Video posting (direct upload)
      - Photo posting
      - Publish status polling
    """

    OPEN_API_BASE = os.environ.get("TIKTOK_OPEN_API_BASE", "https://open.tiktokapis.com")

    # OAuth
    OAUTH_TOKEN_URL = f"{OPEN_API_BASE}/v2/oauth/token/"
    OAUTH_REFRESH_URL = f"{OPEN_API_BASE}/v2/oauth/token/refresh/"

    # Content posting
    VIDEO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/video/init/"
    PHOTO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/content/init/"
    STATUS_FETCH_URL = f"{OPEN_API_BASE}/v2/post/publish/status/fetch/"

    # --------------------------
    # Helpers
    # --------------------------
    @classmethod
    def _parse_json(cls, r: requests.Response) -> Dict[str, Any]:
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    @classmethod
    def _raise_if_error(cls, payload: Dict[str, Any], prefix: str):
        """
        TikTok success === error.code == "ok"
        """
        if not isinstance(payload, dict):
            return

        err = payload.get("error") or {}
        code = err.get("code")

        if code not in (None, "ok", 0, "0"):
            raise Exception(f"{prefix}: {payload}")

    @classmethod
    def _headers_bearer(cls, access_token: str) -> Dict[str, str]:
        if not access_token:
            raise Exception("Missing TikTok access_token")

        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # --------------------------
    # OAuth refresh
    # --------------------------
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

        r = requests.post(cls.OAUTH_REFRESH_URL, json=payload, timeout=30)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok refresh HTTP error: {data}")

        cls._raise_if_error(data, "TikTok refresh failed")
        return data

    # --------------------------
    # VIDEO INIT
    # --------------------------
    @classmethod
    def init_video_post(
        cls,
        *,
        access_token: str,
        post_text: str,
        video_size_bytes: int,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        chunk_size: Optional[int] = None,
        total_chunk_count: Optional[int] = None,
    ) -> Dict[str, Any]:

        url = f"{cls.OPEN_API_BASE}/v2/post/publish/video/init/"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": int(video_size_bytes),
        }

        # ONLY include these when chunking
        if chunk_size and total_chunk_count:
            source_info["chunk_size"] = int(chunk_size)
            source_info["total_chunk_count"] = int(total_chunk_count)

        payload = {
            "post_info": {
                "title": post_text or "",
                "privacy_level": privacy_level,
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 0,
            },
            "source_info": source_info,
        }

        r = requests.post(url, headers=headers, json=payload, timeout=60)

        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= 400:
            raise Exception(f"TikTok video init HTTP error: {data}")

        err = data.get("error") or {}
        if err.get("code") not in (None, "ok"):
            raise Exception(f"TikTok video init API error: {data}")

        return data
    # --------------------------
    # PHOTO INIT
    # --------------------------
    @classmethod
    def init_photo_post(
        cls,
        *,
        access_token: str,
        post_text: str,
        image_urls: List[str],
        privacy_level: str = "PUBLIC_TO_EVERYONE",
    ) -> Dict[str, Any]:

        payload = {
            "post_info": {
                "title": post_text or "",
                "privacy_level": privacy_level,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_urls": image_urls,
            },
        }

        r = requests.post(
            cls.PHOTO_INIT_URL,
            headers=cls._headers_bearer(access_token),
            json=payload,
            timeout=60,
        )

        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok photo init HTTP error: {data}")

        cls._raise_if_error(data, "TikTok photo init failed")

        d = data.get("data") or {}
        if not d.get("publish_id"):
            raise Exception(f"TikTok photo init missing publish_id: {data}")

        return data

    # --------------------------
    # Upload helpers
    # --------------------------
    @classmethod
    def upload_video_put_single(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
    ) -> Dict[str, Any]:

        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(video_bytes)),
        }

        r = requests.put(upload_url, headers=headers, data=video_bytes, timeout=120)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok upload failed: {r.text[:500]}")

        return {
            "status_code": r.status_code,
            "etag": r.headers.get("etag"),
        }

    @classmethod
    def upload_video_put_chunked(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
        chunk_size: int,
    ) -> Dict[str, Any]:

        total = len(video_bytes)
        start = 0
        parts = []

        while start < total:
            end = min(start + chunk_size, total) - 1
            chunk = video_bytes[start:end + 1]

            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{total}",
            }

            r = requests.put(upload_url, headers=headers, data=chunk, timeout=120)

            if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
                raise Exception(f"TikTok chunk upload failed: {r.text[:500]}")

            parts.append({"start": start, "end": end})
            start = end + 1

        return {"parts": parts, "total_bytes": total}

    # --------------------------
    # Status polling
    # --------------------------
    @classmethod
    def fetch_publish_status(
        cls,
        *,
        access_token: str,
        publish_id: str,
    ) -> Dict[str, Any]:

        payload = {"publish_id": publish_id}

        r = requests.post(
            cls.STATUS_FETCH_URL,
            headers=cls._headers_bearer(access_token),
            json=payload,
            timeout=30,
        )

        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok status HTTP error: {data}")

        cls._raise_if_error(data, "TikTok status failed")

        return data

    @classmethod
    def wait_for_publish(
        cls,
        *,
        access_token: str,
        publish_id: str,
        max_wait_seconds: int = 240,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:

        deadline = time.time() + max_wait_seconds
        last = {}

        while time.time() < deadline:
            last = cls.fetch_publish_status(
                access_token=access_token,
                publish_id=publish_id,
            )

            d = last.get("data") or {}
            status = (d.get("status") or "").lower()

            if status in ("published", "success", "succeeded"):
                return last

            if status in ("failed", "error"):
                return last

            time.sleep(poll_interval)

        return last