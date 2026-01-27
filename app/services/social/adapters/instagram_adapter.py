# app/services/social/adapters/instagram_adapter.py

from __future__ import annotations
import time
from typing import Any, Dict, List
import requests

from ....utils.logger import Log


class InstagramAdapter:
    """
    Instagram Graph API helper.

    Includes:
      - Publishing helpers (containers + publish)
      - Account discovery:
          user_access_token -> pages -> /{page-id}/instagram_accounts -> ig_user_id, username

    Notes:
      - ig_user_id will be NULL if the Facebook Page has no linked Instagram Professional account.
      - Publishing typically uses a Page token (or a valid token with required permissions).
    """

    GRAPH_BASE = "https://graph.facebook.com"
    GRAPH_VERSION = "v19.0"  # keep consistent with your existing pinned version

    # ------------------------------------------------------------------
    # Core HTTP helpers
    # ------------------------------------------------------------------
    @classmethod
    def _url(cls, path: str) -> str:
        return f"{cls.GRAPH_BASE}/{cls.GRAPH_VERSION}/{path.lstrip('/')}"

    @classmethod
    def _get(cls, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = cls._url(path)
        r = requests.get(url, params=params, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}

        if r.status_code >= 400:
            raise Exception(f"Instagram API error: {data}")
        return data

    @classmethod
    def _post(cls, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        url = cls._url(path)
        r = requests.post(url, data=data, timeout=60)
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text}

        if r.status_code >= 400:
            raise Exception(f"Instagram API error: {payload}")
        return payload

    @classmethod
    def _get_all_pages(cls, user_access_token: str) -> List[Dict[str, Any]]:
        """
        Paged fetch for /me/accounts to return all pages the user can manage.
        Each page item typically includes page access_token (if permitted).
        """
        pages: List[Dict[str, Any]] = []
        log_tag = "[InstagramAdapter][_get_all_pages]"

        if not user_access_token:
            return pages

        first = cls._get(
            "/me/accounts",
            params={
                "access_token": user_access_token,
                "fields": "id,name,access_token,tasks",
                "limit": 100,
            },
        )
        pages.extend(first.get("data") or [])
        next_url = ((first.get("paging") or {}).get("next") or "").strip()

        while next_url:
            r = requests.get(next_url, timeout=30)
            try:
                d = r.json()
            except Exception:
                d = {"raw": r.text}

            if r.status_code >= 400:
                raise Exception(f"{log_tag} paging error: {d}")

            pages.extend(d.get("data") or [])
            next_url = ((d.get("paging") or {}).get("next") or "").strip()

        return pages


    # -------------------------
    # NEW: container status
    # -------------------------
    @classmethod
    def get_container_status(cls, creation_id: str, access_token: str) -> Dict[str, Any]:
        # fields commonly used by IG Graph
        return cls._get(
            f"/{creation_id}",
            params={
                "access_token": access_token,
                "fields": "id,status_code,status",
            },
        )


    # ------------------------------------------------------------------
    # Publishing helpers
    # ------------------------------------------------------------------
    # Feed containers (single)
    @classmethod
    def create_feed_container_image(
        cls,
        ig_user_id: str,
        access_token: str,
        image_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token,
            },
        )

    @classmethod
    def create_feed_container_video(
        cls,
        ig_user_id: str,
        access_token: str,
        video_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "video_url": video_url,
                "caption": caption,
                "access_token": access_token,
            },
        )

    # Reels container
    @classmethod
    def create_reel_container(
        cls,
        ig_user_id: str,
        access_token: str,
        video_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "access_token": access_token,
            },
        )

    # Story containers
    @classmethod
    def create_story_container_image(
        cls,
        ig_user_id: str,
        access_token: str,
        image_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "media_type": "STORIES",
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token,
            },
        )

    @classmethod
    def create_story_container_video(
        cls,
        ig_user_id: str,
        access_token: str,
        video_url: str,
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "media_type": "STORIES",
                "video_url": video_url,
                "caption": caption,
                "access_token": access_token,
            },
        )

    # Carousel flow
    @classmethod
    def create_carousel_item_image(
        cls,
        ig_user_id: str,
        access_token: str,
        image_url: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "image_url": image_url,
                "is_carousel_item": "true",
                "access_token": access_token,
            },
        )

    @classmethod
    def create_carousel_item_video(
        cls,
        ig_user_id: str,
        access_token: str,
        video_url: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "video_url": video_url,
                "is_carousel_item": "true",
                "access_token": access_token,
            },
        )

    @classmethod
    def create_carousel_container(
        cls,
        ig_user_id: str,
        access_token: str,
        children: List[str],
        caption: str,
    ) -> Dict[str, Any]:
        return cls._post(
            f"/{ig_user_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": access_token,
            },
        )

    
    @classmethod
    def wait_until_container_ready(
        cls,
        creation_id: str,
        access_token: str,
        *,
        max_attempts: int = 10,
        sleep_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Polls until status_code == FINISHED.
        Returns last status payload.
        Raises if ERROR.
        """
        last = {}
        for i in range(max_attempts):
            last = cls.get_container_status(creation_id, access_token)
            status_code = (last.get("status_code") or "").upper()

            if status_code == "FINISHED":
                return last

            if status_code == "ERROR":
                raise Exception(f"Instagram container status ERROR: {last}")

            time.sleep(sleep_seconds)

        # still not ready
        return last

    # -------------------------
    # Publish
    # -------------------------
    @classmethod
    def publish_container(cls, ig_user_id: str, access_token: str, creation_id: str) -> Dict:
        return cls._post(
            f"/{ig_user_id}/media_publish",
            {"creation_id": creation_id, "access_token": access_token},
        )
    
    # ------------------------------------------------------------------
    # NEW: Account discovery (user token -> pages -> instagram_accounts)
    # ------------------------------------------------------------------
    @classmethod
    def list_user_pages(cls, user_access_token: str) -> List[Dict[str, Any]]:
        """
        Returns pages the user can manage, including each page access_token.
        """
        return cls._get_all_pages(user_access_token)

    @classmethod
    def list_page_instagram_accounts(cls, page_id: str, page_access_token: str) -> List[Dict[str, Any]]:
        """
        Correct way to get IG professional accounts linked to a Facebook Page.
        Uses: /{page-id}/instagram_accounts
        Returns: [{"id": "...", "username": "..."}]
        """
        data = cls._get(
            f"/{page_id}/instagram_accounts",
            params={
                "access_token": page_access_token,
                "fields": "id,username",
                "limit": 50,
            },
        )
        return data.get("data") or []

    @classmethod
    def get_connected_instagram_accounts(cls, user_access_token: str) -> List[Dict[str, Any]]:
        """
        Returns list of Instagram professional accounts connected to Facebook Pages
        that the user can manage.

        Output items example:
        {
          "platform": "instagram",
          "destination_type": "ig_user",
          "destination_id": "<ig_user_id>",
          "username": "...",
          "page_id": "...",
          "page_name": "...",
          "page_access_token": "...",
        }
        """
        log_tag = "[InstagramAdapter][get_connected_instagram_accounts]"

        if not user_access_token:
            return []

        pages = cls.list_user_pages(user_access_token)
        out: List[Dict[str, Any]] = []

        for p in pages:
            page_id = str(p.get("id") or "")
            page_name = p.get("name")
            page_access_token = p.get("access_token")

            if not page_id or not page_access_token:
                continue

            try:
                ig_accounts = cls.list_page_instagram_accounts(page_id, page_access_token)
            except Exception as e:
                Log.info(f"{log_tag} instagram_accounts lookup failed page_id={page_id}: {e}")
                continue

            # If none linked, you can either skip or return placeholders.
            # Most UIs skip and tell the user to link IG to a Page.
            for ig in ig_accounts:
                ig_id = str(ig.get("id") or "")
                if not ig_id:
                    continue

                out.append({
                    "platform": "instagram",
                    "destination_type": "ig_user",
                    "destination_id": ig_id,
                    "username": ig.get("username"),
                    "page_id": page_id,
                    "page_name": page_name,
                    # You will usually publish using a token tied to the page/user with needed perms
                    "page_access_token": page_access_token,
                })

        return out