# app/services/social/adapters/tiktok_adapter.py

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple, List

import requests

from ....constants.service_code import HTTP_STATUS_CODES


class TikTokAdapter:
    """
    TikTok Open API helper (OAuth + Content Posting).

    What this adapter supports:
      - OAuth2: exchange code -> access_token/refresh_token/open_id
      - Refresh token
      - User info fetch (requires user.info.basic)
      - Content Posting (Direct Post):
          1) init video publish (returns upload_url + publish_id)
          2) upload video bytes to upload_url
          3) poll status/fetch to confirm publishing result

    Notes:
      - TikTok access_token MUST be sent in Authorization: Bearer <token>
      - Tokens expire. If you store tokens, you must refresh when expired.
      - For video publishing you typically need: video.upload + video.publish
    """

    OPEN_API_BASE = os.environ.get("TIKTOK_OPEN_API_BASE", "https://open.tiktokapis.com")

    # OAuth endpoints (OpenAPI v2)
    OAUTH_TOKEN_URL = f"{OPEN_API_BASE}/v2/oauth/token/"
    OAUTH_REFRESH_URL = f"{OPEN_API_BASE}/v2/oauth/token/refresh/"

    # User info endpoint
    USER_INFO_URL = f"{OPEN_API_BASE}/v2/user/info/"

    # Content Posting (Direct Post)
    VIDEO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/video/init/"
    STATUS_FETCH_URL = f"{OPEN_API_BASE}/v2/post/publish/status/fetch/"

    # ----------------------------
    # Low-level HTTP helpers
    # ----------------------------
    @classmethod
    def _headers_bearer(cls, access_token: str) -> Dict[str, str]:
        if not access_token:
            raise Exception("Missing TikTok access_token")
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    @classmethod
    def _post_json(
        cls,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        r = requests.post(url, headers=headers, json=payload or {}, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok API error: {data}")
        return data

    @classmethod
    def _get(
        cls,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok API error: {data}")
        return data

    # ----------------------------
    # OAuth2
    # ----------------------------
    @classmethod
    def exchange_code_for_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
    ) -> Dict[str, Any]:
        """
        Exchange authorization 'code' for tokens.

        Returns payload like:
          {
            "access_token": "...",
            "expires_in": 86400,
            "open_id": "...",
            "refresh_token": "...",
            "refresh_expires_in": ...,
            "scope": "user.info.basic,video.upload,video.publish",
            "token_type": "Bearer"
          }
        """
        if not client_key or not client_secret:
            raise Exception("Missing TikTok client_key/client_secret")
        if not code or not redirect_uri:
            raise Exception("Missing TikTok code/redirect_uri")

        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        return cls._post_json(cls.OAUTH_TOKEN_URL, payload=payload)

    @classmethod
    def refresh_access_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        refresh_token: str,
    ) -> Dict[str, Any]:
        """
        Refresh access token.
        """
        if not client_key or not client_secret:
            raise Exception("Missing TikTok client_key/client_secret")
        if not refresh_token:
            raise Exception("Missing TikTok refresh_token")

        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return cls._post_json(cls.OAUTH_REFRESH_URL, payload=payload)

    # ----------------------------
    # User info (requires user.info.basic)
    # ----------------------------
    @classmethod
    def get_user_info(
        cls,
        *,
        access_token: str,
        fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch user information.

        If fields is None, we request a safe default set.
        """
        if not fields:
            # Keep this minimal. Add more fields if TikTok app has them approved.
            fields = ["open_id", "union_id", "display_name", "avatar_url"]

        params = {
            "fields": ",".join(fields),
        }
        headers = cls._headers_bearer(access_token)
        return cls._get(cls.USER_INFO_URL, headers=headers, params=params)

    # ----------------------------
    # Content Posting: Direct Post (Video)
    # ----------------------------
    @classmethod
    def init_direct_post_video(
        cls,
        *,
        access_token: str,
        post_text: str,
        video_size_bytes: int,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        brand_content_toggle: bool = False,
        brand_organic_toggle: bool = False,
    ) -> Dict[str, Any]:
        """
        Initialize a direct-post video upload.

        Returns typically includes:
          data: { publish_id, upload_url }
        """
        if not post_text:
            post_text = ""

        if not isinstance(video_size_bytes, int) or video_size_bytes <= 0:
            raise Exception("video_size_bytes must be a positive int")

        headers = cls._headers_bearer(access_token)

        payload = {
            "post_info": {
                "title": post_text,
                "privacy_level": privacy_level,
                "disable_comment": bool(disable_comment),
                "disable_duet": bool(disable_duet),
                "disable_stitch": bool(disable_stitch),
                "video_cover_timestamp_ms": 0,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": int(video_size_bytes),
                # Some docs use "chunk_size" / "total_chunk_count". We will upload as a single PUT by default.
                # If you want chunked PUTs, set these and use upload_video_put_chunked().
            },
            "brand_content_toggle": bool(brand_content_toggle),
            "brand_organic_toggle": bool(brand_organic_toggle),
        }

        resp = cls._post_json(cls.VIDEO_INIT_URL, headers=headers, payload=payload)

        # TikTok returns:
        # { "data": { "publish_id": "...", "upload_url": "..." }, "error": { "code": "ok", ... } }
        err = (resp.get("error") or {})
        if err.get("code") not in (None, "ok"):
            raise Exception(f"TikTok API error (init): {resp}")

        data = resp.get("data") or {}
        if not data.get("upload_url") or not data.get("publish_id"):
            raise Exception(f"TikTok init missing upload_url/publish_id: {resp}")

        return resp

    @classmethod
    def upload_video_put_single(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """
        Upload the full video in a single PUT to upload_url.

        Returns dict with status_code and response headers snippet.
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not video_bytes:
            raise Exception("video_bytes is empty")

        # TikTok upload_url expects raw bytes
        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(video_bytes)),
        }

        r = requests.put(upload_url, headers=headers, data=video_bytes, timeout=timeout)
        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            # sometimes not JSON
            raise Exception(f"TikTok upload PUT failed: status={r.status_code} body={r.text[:500]}")

        return {
            "status_code": r.status_code,
            "etag": r.headers.get("etag"),
            "request_id": r.headers.get("x-request-id") or r.headers.get("x-tt-trace-id"),
        }

    @classmethod
    def upload_video_put_chunked(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
        chunk_size: int = 8 * 1024 * 1024,  # 8MB
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """
        Chunked PUT using Content-Range. Use this if TikTok requires chunked upload for large files.

        Returns: {"parts": [...], "total_bytes": int}
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not video_bytes:
            raise Exception("video_bytes is empty")

        total = len(video_bytes)
        parts = []
        start = 0

        while start < total:
            end = min(start + chunk_size, total) - 1
            chunk = video_bytes[start:end + 1]

            headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{total}",
            }

            r = requests.put(upload_url, headers=headers, data=chunk, timeout=timeout)
            if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
                raise Exception(f"TikTok chunk upload failed: status={r.status_code} body={r.text[:500]}")

            parts.append({"start": start, "end": end, "status_code": r.status_code})
            start = end + 1

        return {"parts": parts, "total_bytes": total}

    @classmethod
    def fetch_post_status(
        cls,
        *,
        access_token: str,
        publish_id: str,
    ) -> Dict[str, Any]:
        """
        Fetch post status after init/upload.

        Typical usage: poll until status indicates success/failure.
        """
        headers = cls._headers_bearer(access_token)
        payload = {"publish_id": publish_id}

        resp = cls._post_json(cls.STATUS_FETCH_URL, headers=headers, payload=payload)
        err = (resp.get("error") or {})
        if err.get("code") not in (None, "ok"):
            raise Exception(f"TikTok API error (status): {resp}")
        return resp

    @classmethod
    def wait_for_publish(
        cls,
        *,
        access_token: str,
        publish_id: str,
        max_wait_seconds: int = 120,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Poll status until success/failure or timeout.
        """
        deadline = time.time() + max_wait_seconds
        last = {}

        while time.time() < deadline:
            last = cls.fetch_post_status(access_token=access_token, publish_id=publish_id)

            data = last.get("data") or {}
            status = (data.get("status") or "").lower()

            # TikTok may return statuses like: PROCESSING / PUBLISHED / FAILED (depends on API)
            if status in ("published", "success", "succeeded"):
                return last
            if status in ("failed", "error"):
                return last

            time.sleep(poll_interval)

        return last

    # ----------------------------
    # Webhooks (basic handler helpers)
    # ----------------------------
    @classmethod
    def parse_webhook_event(cls, raw_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        TikTok webhooks payloads vary by product.
        Keep this as a minimal normalizer so your resource can route events.
        """
        if not isinstance(raw_json, dict):
            return {"type": None, "raw": raw_json}

        event_type = raw_json.get("event") or raw_json.get("type") or raw_json.get("event_type")
        return {"type": event_type, "raw": raw_json}
    


