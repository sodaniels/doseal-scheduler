# app/services/social/adapters/x_adapter.py

from __future__ import annotations

import base64
import math
import os
from typing import Any, Dict, Optional, Tuple, List
import time
from requests_oauthlib import OAuth1

from ....constants.service_code import HTTP_STATUS_CODES

import requests
from requests_oauthlib import OAuth1


class XAdapter:
    """
    X (Twitter) API helper using OAuth 1.0a User Context.

    Supports:
      - OAuth1a 3-legged flow (request token -> authorize -> access token)
      - Upload media (chunked INIT/APPEND/FINALIZE) to upload.x.com v1.1
      - Post tweet with media via X API v2 POST /2/tweets

    Notes:
      - For media upload, we use https://upload.x.com/1.1/media/upload.json
      - For tweet creation, we use https://api.x.com/2/tweets
    """
    

    API_BASE = os.environ.get("X_API_BASE_URL", "https://api.x.com")
    UPLOAD_BASE = os.environ.get("X_UPLOAD_BASE_URL", "https://upload.twitter.com")

    REQUEST_TOKEN_URL = f"{API_BASE}/oauth/request_token"
    AUTHORIZE_URL = f"{API_BASE}/oauth/authorize"
    ACCESS_TOKEN_URL = f"{API_BASE}/oauth/access_token"

    CREATE_TWEET_URL = f"{API_BASE}/2/tweets"
    MEDIA_UPLOAD_URL = f"{UPLOAD_BASE}/1.1/media/upload.json"

    # ----------------------------
    # OAuth 1.0a flow
    # ----------------------------
    @classmethod
    def get_request_token(
        cls,
        *,
        consumer_key: str,
        consumer_secret: str,
        callback_url: str,
    ) -> Tuple[str, str]:
        """
        Returns: (oauth_token, oauth_token_secret)
        """
        auth = OAuth1(
            consumer_key,
            client_secret=consumer_secret,
            callback_uri=callback_url,
        )
        r = requests.post(cls.REQUEST_TOKEN_URL, auth=auth, timeout=30)
        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X request_token failed: {r.text}")

        # response is querystring: oauth_token=...&oauth_token_secret=...&oauth_callback_confirmed=true
        data = dict([p.split("=", 1) for p in r.text.split("&") if "=" in p])
        oauth_token = data.get("oauth_token")
        oauth_token_secret = data.get("oauth_token_secret")
        if not oauth_token or not oauth_token_secret:
            raise Exception(f"X request_token missing fields: {data}")
        return oauth_token, oauth_token_secret

    @classmethod
    def build_authorize_url(cls, oauth_token: str) -> str:
        return f"{cls.AUTHORIZE_URL}?oauth_token={oauth_token}"

    @classmethod
    def exchange_access_token(
        cls,
        *,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
        oauth_verifier: str,
    ) -> Dict[str, str]:
        """
        Returns dict:
          {
            "oauth_token": "...",
            "oauth_token_secret": "...",
            "user_id": "...",
            "screen_name": "..."
          }
        """
        auth = OAuth1(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_token_secret,
            verifier=oauth_verifier,
        )
        r = requests.post(cls.ACCESS_TOKEN_URL, auth=auth, timeout=30)
        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X access_token exchange failed: {r.text}")

        data = dict([p.split("=", 1) for p in r.text.split("&") if "=" in p])
        if not data.get("oauth_token") or not data.get("oauth_token_secret"):
            raise Exception(f"X access_token missing fields: {data}")
        return data

    @classmethod
    def verify_credentials(
        cls,
        *,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
    ) -> Dict[str, Any]:
        """
        v1.1 verify credentials (useful to fetch username/id reliably)
        """
        url = f"{cls.API_BASE}/1.1/account/verify_credentials.json"
        auth = OAuth1(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_token_secret,
        )
        r = requests.get(url, auth=auth, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X verify_credentials failed: {data}")
        return data

    # ----------------------------
    # Media Upload (chunked)
    # ----------------------------
    @classmethod
    def upload_media(
        cls,
        *,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
        media_url: str,
        media_type: str,  # "image" | "video"
        media_category: Optional[str] = None,  # e.g. "tweet_image" | "tweet_video"
        chunk_size: int = 1024 * 1024 * 2,  # 2MB
        status_max_wait_seconds: int = 60,
        status_poll_interval: float = 2.0,
    ) -> str:
        """
        Downloads media_url, uploads it to X, returns media_id_string.

        Uses INIT/APPEND/FINALIZE and polls STATUS for video processing.
        """
        if media_type not in ("image", "video"):
            raise Exception("media_type must be image or video")

        # 1) download the file
        dl = requests.get(media_url, timeout=60)
        if dl.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"Failed to download media_url: {dl.status_code}")

        content = dl.content
        total_bytes = len(content)
        if total_bytes <= 0:
            raise Exception("Downloaded media is empty")

        # Best-effort mime type detection (important!)
        content_type = (dl.headers.get("content-type") or "").split(";")[0].strip().lower()

        # 2) INIT
        auth = OAuth1(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_token_secret,
        )

        init_data = {
            "command": "INIT",
            "total_bytes": str(total_bytes),
        }

        if media_type == "image":
            # try to keep correct type if server provides it
            init_data["media_type"] = content_type if content_type.startswith("image/") else "image/png"
            init_data["media_category"] = media_category or "tweet_image"
        else:
            init_data["media_type"] = content_type if content_type.startswith("video/") else "video/mp4"
            init_data["media_category"] = media_category or "tweet_video"

        r_init = requests.post(cls.MEDIA_UPLOAD_URL, data=init_data, auth=auth, timeout=60)
        init_payload = (
            r_init.json()
            if r_init.headers.get("content-type", "").startswith("application/json")
            else {"raw": r_init.text}
        )
        if r_init.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X media INIT failed: {init_payload}")

        media_id = str(init_payload.get("media_id_string") or init_payload.get("media_id") or "")
        if not media_id:
            raise Exception(f"X media INIT missing media_id: {init_payload}")

        # 3) APPEND chunks
        num_segments = int(math.ceil(total_bytes / float(chunk_size)))
        for seg in range(num_segments):
            start = seg * chunk_size
            end = min(start + chunk_size, total_bytes)
            chunk = content[start:end]

            append_data = {
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": str(seg),
            }
            files = {"media": chunk}

            r_app = requests.post(
                cls.MEDIA_UPLOAD_URL,
                data=append_data,
                files=files,
                auth=auth,
                timeout=120,
            )
            if r_app.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
                try:
                    ap = r_app.json()
                except Exception:
                    ap = {"raw": r_app.text}
                raise Exception(f"X media APPEND failed (seg={seg}): {ap}")

        # 4) FINALIZE
        fin_data = {"command": "FINALIZE", "media_id": media_id}
        r_fin = requests.post(cls.MEDIA_UPLOAD_URL, data=fin_data, auth=auth, timeout=60)
        fin_payload = (
            r_fin.json()
            if r_fin.headers.get("content-type", "").startswith("application/json")
            else {"raw": r_fin.text}
        )
        if r_fin.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X media FINALIZE failed: {fin_payload}")

        # 5) STATUS poll (CRITICAL for videos; sometimes for GIF too)
        processing_info = fin_payload.get("processing_info")
        if processing_info:
            deadline = time.time() + status_max_wait_seconds

            while True:
                state = (processing_info.get("state") or "").lower()

                if state == "succeeded":
                    break

                if state == "failed":
                    raise Exception(f"X media processing failed: {processing_info}")

                if time.time() > deadline:
                    raise Exception(f"X media processing timeout: {processing_info}")

                # X can tell us how long to wait
                wait_secs = processing_info.get("check_after_secs")
                time.sleep(float(wait_secs) if wait_secs is not None else status_poll_interval)

                # refresh status
                status_params = {"command": "STATUS", "media_id": media_id}
                r_status = requests.get(cls.MEDIA_UPLOAD_URL, params=status_params, auth=auth, timeout=30)
                status_payload = (
                    r_status.json()
                    if r_status.headers.get("content-type", "").startswith("application/json")
                    else {"raw": r_status.text}
                )
                if r_status.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
                    raise Exception(f"X media STATUS failed: {status_payload}")

                processing_info = status_payload.get("processing_info") or processing_info

        return media_id
    
    # ----------------------------
    # Create Tweet (v2)
    # ----------------------------
    @classmethod
    def create_tweet(
        cls,
        *,
        consumer_key: str,
        consumer_secret: str,
        oauth_token: str,
        oauth_token_secret: str,
        text: str,
        media_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        auth = OAuth1(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_token_secret,
        )

        payload: Dict[str, Any] = {"text": text or ""}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}

        r = requests.post(cls.CREATE_TWEET_URL, json=payload, auth=auth, timeout=60)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
            raise Exception(f"X create_tweet failed: {data}")
        return data