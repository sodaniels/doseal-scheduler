# app/services/social/adapters/threads_adapter.py

from __future__ import annotations

import requests
from typing import Any, Dict, Optional

from ....utils.logger import Log


class ThreadsAdapter:
    """
    Threads publishing via Meta Graph API.

    Assumptions:
      - You have a Threads access token.
      - You have threads_user_id (destination_id).
      - You publish by:
          1) POST /{threads_user_id}/threads (create container)
          2) POST /{threads_user_id}/threads_publish (publish container)

    Notes:
      - Endpoint names/fields can vary by Graph version & access.
      - This adapter is built to fail safely and log useful debug details.
    """

    GRAPH_BASE = "https://graph.facebook.com"
    GRAPH_VERSION = "v19.0"

    @classmethod
    def _url(cls, path: str) -> str:
        return f"{cls.GRAPH_BASE}/{cls.GRAPH_VERSION}/{path.lstrip('/')}"

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            txt = getattr(resp, "text", None)
            return {"text": txt} if txt else {}

    @classmethod
    def _post(cls, path: str, data: Dict[str, Any], *, timeout: int = 60) -> Dict[str, Any]:
        url = cls._url(path)
        r = requests.post(url, data=data, timeout=timeout)
        payload = cls._safe_json(r)

        if r.status_code >= 400:
            raise Exception(f"Threads API error: {payload}")

        return payload

    @classmethod
    def create_thread(
        cls,
        *,
        threads_user_id: str,
        access_token: str,
        text: str,
        link: Optional[str] = None,
        is_reply: bool = False,
        reply_to_id: Optional[str] = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Creates a thread "container" (like IG container).
        Returns something like: {"id": "<creation_id>"}

        Fields differ depending on Meta/Threads rollout.
        We keep it conservative: "text" + optional "link".
        """
        if not threads_user_id:
            raise Exception("Missing threads_user_id")
        if not access_token:
            raise Exception("Missing Threads access_token")

        final_text = (text or "").strip()
        if link:
            final_text = (final_text + "\n\n" + link).strip()

        if not final_text:
            raise Exception("Threads requires text")

        payload: Dict[str, Any] = {
            "access_token": access_token,
            "text": final_text,
        }

        # Optional reply support (if you later use it)
        if is_reply and reply_to_id:
            payload["reply_to_id"] = reply_to_id

        return cls._post(f"/{threads_user_id}/threads", payload, timeout=timeout)

    @classmethod
    def publish_thread(
        cls,
        *,
        threads_user_id: str,
        access_token: str,
        creation_id: str,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Publishes the created container.
        Returns something like: {"id": "<post_id>"} or {"post_id": "..."} depending on API.
        """
        if not threads_user_id:
            raise Exception("Missing threads_user_id")
        if not access_token:
            raise Exception("Missing Threads access_token")
        if not creation_id:
            raise Exception("Missing creation_id")

        payload = {
            "access_token": access_token,
            "creation_id": creation_id,
        }

        return cls._post(f"/{threads_user_id}/threads_publish", payload, timeout=timeout)

    @classmethod
    def publish_post(
        cls,
        *,
        threads_user_id: str,
        access_token: str,
        text: str,
        link: Optional[str],
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        One-shot publish helper.
        """
        try:
            create_resp = cls.create_thread(
                threads_user_id=threads_user_id,
                access_token=access_token,
                text=text,
                link=link,
            )
            creation_id = create_resp.get("id")
            if not creation_id:
                return {
                    "success": False,
                    "provider_post_id": None,
                    "raw": {"create": create_resp},
                    "error": "Threads create missing id",
                }

            pub_resp = cls.publish_thread(
                threads_user_id=threads_user_id,
                access_token=access_token,
                creation_id=creation_id,
            )

            provider_post_id = pub_resp.get("id") or pub_resp.get("post_id")
            return {
                "success": True,
                "provider_post_id": provider_post_id,
                "raw": {"create": create_resp, "publish": pub_resp},
                "error": None,
            }

        except Exception as e:
            Log.info(f"{log_tag} threads publish exception: {e}")
            return {
                "success": False,
                "provider_post_id": None,
                "raw": None,
                "error": str(e),
            }