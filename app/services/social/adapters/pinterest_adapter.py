# app/services/social/adapters/pinterest_adapter.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests

from ....utils.logger import Log


class PinterestAdapter:
    """
    Pinterest API v5 helper.

    OAuth:
      - Authorize: https://www.pinterest.com/oauth/
      - Token:     https://api.pinterest.com/v5/oauth/token

    API:
      - Base: https://api.pinterest.com/v5
      - Boards: GET /boards
      - Create Pin: POST /pins

    Notes:
      - Pinterest token endpoint uses v5/oauth/token.  [oai_citation:2‡docs.squiz.net](https://docs.squiz.net/connect/latest/components/connectors/pinterest.html?utm_source=chatgpt.com)
      - v5 endpoints include pins/boards resources.  [oai_citation:3‡Pinterest Developers](https://developers.pinterest.com/docs/api/v5/multi_pins-analytics/?utm_source=chatgpt.com)
    """

    API_BASE = "https://api.pinterest.com/v5"
    AUTH_BASE = "https://www.pinterest.com/oauth/"
    TOKEN_URL = "https://api.pinterest.com/v5/oauth/token"

    # ------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------
    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            return {"raw": getattr(resp, "text", "")}

    @classmethod
    def _get(cls, path: str, *, access_token: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
        if not access_token:
            raise Exception("Missing Pinterest access_token")
        url = f"{cls.API_BASE}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {access_token}"}
        r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        data = cls._safe_json(r)
        if r.status_code >= 400:
            raise Exception(f"Pinterest GET {path} error {r.status_code}: {data}")
        return data

    @classmethod
    def _post_json(cls, path: str, *, access_token: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        if not access_token:
            raise Exception("Missing Pinterest access_token")
        url = f"{cls.API_BASE}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        data = cls._safe_json(r)
        if r.status_code >= 400:
            raise Exception(f"Pinterest POST {path} error {r.status_code}: {data}")
        return data

    # ------------------------------------------------------------
    # OAuth: exchange + refresh
    # ------------------------------------------------------------
    @classmethod
    def exchange_code_for_token(
        cls,
        *,
        client_id: str,
        client_secret: str,
        code: str,
        redirect_uri: str,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        POST https://api.pinterest.com/v5/oauth/token
        grant_type=authorization_code
        """
        if not client_id or not client_secret:
            raise Exception("Missing Pinterest client_id/client_secret")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        r = requests.post(
            cls.TOKEN_URL,
            data=data,
            auth=(client_id, client_secret),
            timeout=30,
        )
        payload = cls._safe_json(r)
        if r.status_code >= 400:
            raise Exception(f"{log_tag} Pinterest token exchange failed {r.status_code}: {payload}")
        if not payload.get("access_token"):
            raise Exception(f"{log_tag} Pinterest token exchange missing access_token: {payload}")
        return payload

    @classmethod
    def refresh_access_token(
        cls,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        POST https://api.pinterest.com/v5/oauth/token
        grant_type=refresh_token
        """
        if not refresh_token:
            raise Exception("Missing Pinterest refresh_token")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        r = requests.post(
            cls.TOKEN_URL,
            data=data,
            auth=(client_id, client_secret),
            timeout=30,
        )
        payload = cls._safe_json(r)
        if r.status_code >= 400:
            raise Exception(f"{log_tag} Pinterest refresh failed {r.status_code}: {payload}")
        if not payload.get("access_token"):
            raise Exception(f"{log_tag} Pinterest refresh missing access_token: {payload}")
        return payload

    # ------------------------------------------------------------
    # Account discovery
    # ------------------------------------------------------------
    @classmethod
    def get_user_account(cls, *, access_token: str) -> Dict[str, Any]:
        # Pinterest v5 typically exposes user account info
        return cls._get("/user_account", access_token=access_token, params={}, timeout=30)

    @classmethod
    def list_boards(cls, *, access_token: str, page_size: int = 50) -> List[Dict[str, Any]]:
        # GET /boards
        data = cls._get("/boards", access_token=access_token, params={"page_size": page_size}, timeout=30)
        return data.get("items") or data.get("data") or []

    # ------------------------------------------------------------
    # Publish: Create Pin (image/video by URL)
    # ------------------------------------------------------------
    @classmethod
    def create_pin(
        cls,
        *,
        access_token: str,
        board_id: str,
        title: str,
        description: str,
        link: Optional[str],
        media_url: str,
        media_type: str,  # "image" or "video"
        alt_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /pins

        Common payload pattern (Pinterest v5):
          {
            "board_id": "...",
            "title": "...",
            "description": "...",
            "link": "...",
            "alt_text": "...",
            "media_source": {
              "source_type": "image_url" | "video_url",
              "url": "https://..."
            }
          }
        """
        if not board_id:
            raise Exception("Missing board_id")
        if not media_url:
            raise Exception("Missing media_url")

        mt = (media_type or "").lower().strip()
        if mt not in ("image", "video"):
            raise Exception("Pinterest create_pin supports media_type in {'image','video'}")

        source_type = "image_url" if mt == "image" else "video_url"

        payload: Dict[str, Any] = {
            "board_id": board_id,
            "title": title,
            "description": description,
            "media_source": {
                "source_type": source_type,
                "url": media_url,
            },
        }

        if link:
            payload["link"] = link
        if alt_text:
            payload["alt_text"] = alt_text

        return cls._post_json("/pins", access_token=access_token, payload=payload, timeout=60)