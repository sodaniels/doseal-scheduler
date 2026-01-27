# app/services/social/adapters/tiktok_adapter.py

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests

from ....constants.service_code import HTTP_STATUS_CODES


class TikTokAdapter:
    """
    TikTok Open API helper (OAuth + Content Posting).

    Supports:
      - OAuth2: exchange code -> access_token/refresh_token/open_id  (x-www-form-urlencoded)
      - Refresh token (x-www-form-urlencoded)
      - User info fetch (v2) via Bearer
      - Content Posting:
          - Video Direct Post (init -> upload_url -> PUT upload -> status)
          - Photo Post using image URLs (init -> status)
      - Get publish status + polling helper

    Important:
      - OAuth endpoints require Content-Type: application/x-www-form-urlencoded
      - API endpoints use Authorization: Bearer <access_token>
    """

    OPEN_API_BASE = os.environ.get("TIKTOK_OPEN_API_BASE", "https://open.tiktokapis.com")

    # OAuth
    OAUTH_TOKEN_URL = f"{OPEN_API_BASE}/v2/oauth/token/"
    OAUTH_REFRESH_URL = f"{OPEN_API_BASE}/v2/oauth/token/refresh/"

    # User info
    USER_INFO_URL = f"{OPEN_API_BASE}/v2/user/info/"

    # Content Posting API
    VIDEO_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/video/init/"       # Video Direct Post
    CONTENT_INIT_URL = f"{OPEN_API_BASE}/v2/post/publish/content/init/"   # Photo Post (and other content types)
    STATUS_FETCH_URL = f"{OPEN_API_BASE}/v2/post/publish/status/fetch/"   # Get Post Status

    # ----------------------------
    # Parsing & error helpers
    # ----------------------------
    @classmethod
    def _parse_json(cls, r: requests.Response) -> Dict[str, Any]:
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    @classmethod
    def _raise_if_error(cls, payload: Dict[str, Any], prefix: str) -> None:
        """
        TikTok response style often:
          {"data": {...}, "error": {"code": "ok"|"invalid_params"|..., "message": "...", "log_id": "..."}}

        Only treat as error when code exists AND code != "ok".
        """
        if not isinstance(payload, dict):
            raise Exception(f"{prefix}: invalid payload type: {type(payload)}")

        err = payload.get("error") or {}
        if not isinstance(err, dict):
            return

        code = err.get("code")
        # "ok" means success (even though 'error' key is present)
        if code and str(code).lower() != "ok":
            raise Exception(f"{prefix}: {payload}")

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
        headers: Dict[str, str],
        payload: Dict[str, Any],
        timeout: int = 60,
        prefix: str = "TikTok API error",
    ) -> Dict[str, Any]:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"{prefix} HTTP error: {data}")

        cls._raise_if_error(data, prefix)
        return data

    @classmethod
    def _get(
        cls,
        url: str,
        *,
        headers: Dict[str, str],
        params: Dict[str, Any],
        timeout: int = 60,
        prefix: str = "TikTok API error",
    ) -> Dict[str, Any]:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"{prefix} HTTP error: {data}")

        cls._raise_if_error(data, prefix)
        return data

    # ----------------------------
    # OAuth2 (x-www-form-urlencoded)
    # ----------------------------
    @classmethod
    def exchange_code_for_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        code_verifier: Optional[str] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        POST https://open.tiktokapis.com/v2/oauth/token/
        Content-Type: application/x-www-form-urlencoded
        """
        if not client_key or not client_secret:
            raise Exception("Missing TikTok client_key/client_secret")
        if not code or not redirect_uri:
            raise Exception("Missing TikTok code/redirect_uri")

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

        r = requests.post(cls.OAUTH_TOKEN_URL, headers=headers, data=payload, timeout=timeout)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok OAuth token exchange failed HTTP error: {data}")

        # OAuth responses might not follow the same {"error":{...}} format always,
        # but if they do, handle it.
        cls._raise_if_error(data, "TikTok OAuth token exchange failed")
        return data

    @classmethod
    def refresh_access_token(
        cls,
        *,
        client_key: str,
        client_secret: str,
        refresh_token: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        POST https://open.tiktokapis.com/v2/oauth/token/refresh/
        Content-Type: application/x-www-form-urlencoded
        """
        if not client_key or not client_secret:
            raise Exception("Missing TikTok client_key/client_secret")
        if not refresh_token:
            raise Exception("Missing TikTok refresh_token")

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        r = requests.post(cls.OAUTH_REFRESH_URL, headers=headers, data=payload, timeout=timeout)
        data = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok OAuth refresh failed HTTP error: {data}")

        cls._raise_if_error(data, "TikTok OAuth refresh failed")
        return data

    # ----------------------------
    # User info (v2)
    # ----------------------------
    @classmethod
    def get_user_info(
        cls,
        *,
        access_token: str,
        fields: Optional[List[str]] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        GET https://open.tiktokapis.com/v2/user/info/?fields=...

        NOTE:
          TikTok returns {"error":{"code":"ok"}} even on success.
          Do NOT treat presence of "error" as failure unless code != "ok".
        """
        if not fields:
            fields = ["open_id", "union_id", "display_name", "avatar_url"]

        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"fields": ",".join(fields)}

        r = requests.get(cls.USER_INFO_URL, headers=headers, params=params, timeout=timeout)
        payload = cls._parse_json(r)

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"TikTok user info failed HTTP error: {payload}")

        cls._raise_if_error(payload, "TikTok user info failed")
        return payload

    # ----------------------------
    # Content Posting: VIDEO (Direct Post)
    # ----------------------------
    @classmethod
    def init_video_post(
        cls,
        *,
        access_token: str,
        post_text: str,
        video_size_bytes: int,
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        video_cover_timestamp_ms: int = 0,
        # Optional chunking fields (ONLY include when chunking)
        chunk_size: Optional[int] = None,
        total_chunk_count: Optional[int] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Initializes a video direct post.
        Returns: {"data": {"publish_id": "...", "upload_url": "..."}, "error": {...}}

        Critical:
          - source_info.video_size MUST be present, otherwise you'll get:
              invalid_params: "The video info is empty"
        """
        if not isinstance(video_size_bytes, int) or video_size_bytes <= 0:
            raise Exception("video_size_bytes must be a positive int")

        headers = cls._headers_bearer(access_token)

        source_info: Dict[str, Any] = {
            "source": "FILE_UPLOAD",
            "video_size": int(video_size_bytes),
        }
        # Only include chunk fields if you are actually doing chunked PUT.
        if chunk_size and total_chunk_count:
            source_info["chunk_size"] = int(chunk_size)
            source_info["total_chunk_count"] = int(total_chunk_count)

        payload = {
            "post_info": {
                "title": (post_text or ""),
                "privacy_level": privacy_level,
                "disable_comment": bool(disable_comment),
                "disable_duet": bool(disable_duet),
                "disable_stitch": bool(disable_stitch),
                "video_cover_timestamp_ms": int(video_cover_timestamp_ms or 0),
            },
            "source_info": source_info,
        }

        return cls._post_json(
            cls.VIDEO_INIT_URL,
            headers=headers,
            payload=payload,
            timeout=timeout,
            prefix="TikTok video init failed",
        )

    @classmethod
    def upload_video_put_single(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Upload full video bytes in one PUT.
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not video_bytes:
            raise Exception("video_bytes is empty")

        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(video_bytes)),
        }

        r = requests.put(upload_url, headers=headers, data=video_bytes, timeout=timeout)
        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
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
        chunk_size: int = 16 * 1024 * 1024,
        timeout: int = 180,
    ) -> Dict[str, Any]:
        """
        Chunked PUT using Content-Range.
        Only use if you set chunk_size/total_chunk_count during init.
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not video_bytes:
            raise Exception("video_bytes is empty")
        if chunk_size <= 0:
            raise Exception("chunk_size must be > 0")

        total = len(video_bytes)
        parts = []
        start = 0

        while start < total:
            end = min(start + chunk_size, total) - 1
            chunk = video_bytes[start : end + 1]

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

    # ----------------------------
    # Content Posting: PHOTO (URLs)
    # ----------------------------
    @classmethod
    def init_photo_post(
        cls,
        *,
        access_token: str,
        post_text: str,
        image_urls: List[str],
        privacy_level: str = "PUBLIC_TO_EVERYONE",
        disable_comment: bool = False,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Initializes a photo post using image URLs.

        Uses:
          POST /v2/post/publish/content/init/
          with source_info:
            {
              "source": "PULL_FROM_URL",
              "media_type": "PHOTO",
              "photo_images": [{"image_url": "..."}],
              "photo_cover_index": 0
            }

        Returns: {"data":{"publish_id":"..."},"error":{...}}
        """
        if not image_urls:
            raise Exception("image_urls cannot be empty")

        headers = cls._headers_bearer(access_token)

        photo_images = [{"image_url": u} for u in image_urls if u]
        if not photo_images:
            raise Exception("All image_urls are empty/invalid")

        payload = {
            "post_info": {
                "title": (post_text or ""),
                "privacy_level": privacy_level,
                "disable_comment": bool(disable_comment),
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "media_type": "PHOTO",
                "photo_images": photo_images,
                "photo_cover_index": 0,
            },
        }

        return cls._post_json(
            cls.CONTENT_INIT_URL,
            headers=headers,
            payload=payload,
            timeout=timeout,
            prefix="TikTok photo init failed",
        )

    # ----------------------------
    # Status: fetch + polling
    # ----------------------------
    @classmethod
    def fetch_post_status(
        cls,
        *,
        access_token: str,
        publish_id: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        headers = cls._headers_bearer(access_token)
        payload = {"publish_id": publish_id}

        return cls._post_json(
            cls.STATUS_FETCH_URL,
            headers=headers,
            payload=payload,
            timeout=timeout,
            prefix="TikTok status fetch failed",
        )

    @classmethod
    def wait_for_publish(
        cls,
        *,
        access_token: str,
        publish_id: str,
        max_wait_seconds: int = 240,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Poll status until published/succeeded or failed/error or timeout.
        Returns the last status payload.
        """
        deadline = time.time() + max_wait_seconds
        last: Dict[str, Any] = {}

        while time.time() < deadline:
            last = cls.fetch_post_status(access_token=access_token, publish_id=publish_id)

            data = last.get("data") or {}
            status = (data.get("status") or "").lower()

            if status in ("published", "success", "succeeded"):
                return last
            if status in ("failed", "error"):
                return last

            time.sleep(poll_interval)

        return last