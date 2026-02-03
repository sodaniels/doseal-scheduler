# app/services/social/adapters/youtube_adapter.py

from __future__ import annotations

import time
import json
from typing import Any, Dict, List, Optional, Tuple

import requests

from ....utils.logger import Log


class YouTubeAdapter:
    """
    YouTube Data API v3 + Google OAuth2 helper.

    Supports:
      - OAuth2 exchange code -> access_token (+ refresh_token on first consent with prompt=consent)
      - Refresh token
      - Fetch "my channels" (mine=true)
      - Resumable upload video (uploadType=resumable)

    Notes:
      - For refresh tokens: your OAuth start MUST include:
          access_type=offline
          prompt=consent   (at least first time)
      - Upload requires scope:
          https://www.googleapis.com/auth/youtube.upload
    """

    GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    YT_API_BASE = "https://www.googleapis.com/youtube/v3"
    YT_UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"

    # ----------------------------
    # Core helpers
    # ----------------------------
    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            t = getattr(resp, "text", "") or ""
            return {"raw": t[:1500]} if t else {}

    @staticmethod
    def _bearer_headers(access_token: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        if not access_token:
            raise Exception("Missing YouTube access_token")
        h = {"Authorization": f"Bearer {access_token}"}
        if extra:
            h.update(extra)
        return h

    @classmethod
    def _raise_if_http_error(cls, resp: requests.Response, log_tag: str, prefix: str) -> Dict[str, Any]:
        data = cls._safe_json(resp)
        if resp.status_code >= 400:
            Log.info(f"{log_tag} {prefix} http={resp.status_code} body={getattr(resp,'text','')[:1500]}")
            raise Exception(f"{prefix}: {data}")
        return data

    # ----------------------------
    # OAuth2: exchange code
    # ----------------------------
    @classmethod
    def exchange_code_for_token(
        cls,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        log_tag: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        POST https://oauth2.googleapis.com/token
        Content-Type: application/x-www-form-urlencoded
        """
        if not client_id or not client_secret:
            raise Exception("Missing YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET")
        if not code or not redirect_uri:
            raise Exception("Missing code/redirect_uri")

        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        resp = requests.post(cls.GOOGLE_OAUTH_TOKEN_URL, data=payload, headers=headers, timeout=timeout)
        data = cls._safe_json(resp)

        if resp.status_code >= 400:
            Log.info(f"{log_tag} youtube token exchange failed: {resp.status_code} {resp.text[:1500]}")
            raise Exception(f"YouTube token exchange failed: {data}")

        if not data.get("access_token"):
            raise Exception(f"YouTube token exchange missing access_token: {data}")

        # refresh_token might be absent if user already consented and prompt not set
        return data

    # ----------------------------
    # OAuth2: refresh token
    # ----------------------------
    @classmethod
    def refresh_access_token(
        cls,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        log_tag: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        POST https://oauth2.googleapis.com/token
        Content-Type: application/x-www-form-urlencoded
        """
        if not refresh_token:
            raise Exception("Missing refresh_token")
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        resp = requests.post(cls.GOOGLE_OAUTH_TOKEN_URL, data=payload, headers=headers, timeout=timeout)
        data = cls._safe_json(resp)

        if resp.status_code >= 400:
            Log.info(f"{log_tag} youtube token refresh failed: {resp.status_code} {resp.text[:1500]}")
            raise Exception(f"YouTube token refresh failed: {data}")

        if not data.get("access_token"):
            raise Exception(f"YouTube token refresh missing access_token: {data}")

        return data

    # ----------------------------
    # YouTube: list my channels
    # ----------------------------
    @classmethod
    def list_my_channels(
        cls,
        *,
        access_token: str,
        log_tag: str,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        GET /channels?part=snippet,contentDetails,statistics&mine=true
        """
        url = f"{cls.YT_API_BASE}/channels"
        params = {
            "part": "snippet",
            "mine": "true",
            "maxResults": 50,
        }

        resp = requests.get(url, headers=cls._bearer_headers(access_token), params=params, timeout=timeout)
        data = cls._raise_if_http_error(resp, log_tag, "YouTube list_my_channels failed")

        items = data.get("items") or []
        out: List[Dict[str, Any]] = []
        for it in items:
            cid = it.get("id")
            sn = it.get("snippet") or {}
            title = sn.get("title")
            out.append({
                "channel_id": str(cid or ""),
                "title": title,
                "custom_url": sn.get("customUrl"),
                "thumb": ((sn.get("thumbnails") or {}).get("default") or {}).get("url"),
            })
        return [x for x in out if x.get("channel_id")]

    # ----------------------------
    # YouTube: Resumable upload (init)
    # ----------------------------
    @classmethod
    def init_resumable_upload(
        cls,
        *,
        access_token: str,
        title: str,
        description: str,
        tags: Optional[List[str]],
        category_id: str = "22",  # People & Blogs (safe default)
        privacy_status: str = "public",  # public|unlisted|private
        log_tag: str = "",
        timeout: int = 60,
    ) -> str:
        """
        Initiate resumable upload:
          POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status
        Returns: upload_url (Location header)
        """
        url = f"{cls.YT_UPLOAD_BASE}/videos"
        params = {"uploadType": "resumable", "part": "snippet,status"}

        payload = {
            "snippet": {
                "title": (title or "").strip()[:100] or "Untitled",
                "description": (description or "").strip()[:5000],
                "categoryId": str(category_id),
            },
            "status": {
                "privacyStatus": privacy_status,
            },
        }
        if tags:
            payload["snippet"]["tags"] = tags[:30]  # YouTube tags limit

        headers = cls._bearer_headers(access_token, extra={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
        })

        resp = requests.post(url, headers=headers, params=params, json=payload, timeout=timeout)

        if resp.status_code >= 400:
            data = cls._safe_json(resp)
            Log.info(f"{log_tag} youtube init upload failed: {resp.status_code} {resp.text[:1500]}")
            raise Exception(f"YouTube init resumable upload failed: {data}")

        upload_url = resp.headers.get("Location") or resp.headers.get("location")
        if not upload_url:
            # Sometimes body contains error details only; but for success Location should exist.
            raise Exception("YouTube resumable init succeeded but Location header missing")

        return upload_url

    # ----------------------------
    # YouTube: upload bytes to resumable URL
    # ----------------------------
    @classmethod
    def upload_video_bytes_resumable(
        cls,
        *,
        upload_url: str,
        video_bytes: bytes,
        content_type: str = "video/mp4",
        log_tag: str = "",
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        PUT upload_url with video bytes.
        On success, YouTube returns JSON with video resource (id, etc.)
        """
        if not upload_url:
            raise Exception("Missing upload_url")
        if not video_bytes:
            raise Exception("video_bytes is empty")

        headers = {
            "Content-Type": content_type or "application/octet-stream",
            "Content-Length": str(len(video_bytes)),
        }

        resp = requests.put(upload_url, headers=headers, data=video_bytes, timeout=timeout)

        # 200/201 = success; 308 = resumable incomplete (chunking). We do single-shot upload here.
        if resp.status_code in (200, 201):
            return cls._safe_json(resp)

        if resp.status_code == 308:
            # chunking not implemented in this helper
            raise Exception("YouTube upload returned 308 (resume incomplete). Implement chunk upload or reduce size/timeouts.")

        data = cls._safe_json(resp)
        Log.info(f"{log_tag} youtube upload failed: {resp.status_code} {resp.text[:1500]}")
        raise Exception(f"YouTube upload failed: {data}")

    # ----------------------------
    # Convenience: full publish
    # ----------------------------
    @classmethod
    def publish_video(
        cls,
        *,
        access_token: str,
        title: str,
        description: str,
        video_bytes: bytes,
        content_type: str,
        tags: Optional[List[str]],
        privacy_status: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        1) init resumable upload
        2) PUT bytes
        """
        upload_url = cls.init_resumable_upload(
            access_token=access_token,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy_status,
            log_tag=log_tag,
        )

        resp = cls.upload_video_bytes_resumable(
            upload_url=upload_url,
            video_bytes=video_bytes,
            content_type=content_type or "video/mp4",
            log_tag=log_tag,
        )

        return resp