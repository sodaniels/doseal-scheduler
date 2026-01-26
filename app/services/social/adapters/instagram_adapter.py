import os
import time
import requests

from ....constants.service_code import HTTP_STATUS_CODES


class InstagramAdapter:
    GRAPH_BASE = os.getenv("FACEBOOK_GRAPH_API_URL", "https://graph.facebook.com/v20.0")

    @classmethod
    def list_connected_instagram_accounts(cls, user_access_token: str):
        """
        Returns FB Pages + attached IG Business account.
        GET /me/accounts?fields=id,name,access_token,instagram_business_account{id,username}
        """
        url = f"{cls.GRAPH_BASE}/me/accounts"
        params = {
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": user_access_token,
        }
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if r.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Meta error listing accounts: {data}")

        pages = data.get("data", []) or []
        # Normalize into “destinations” the user can select
        out = []
        for p in pages:
            ig = (p.get("instagram_business_account") or {})
            if not ig.get("id"):
                continue
            out.append({
                "page_id": str(p.get("id")),
                "page_name": p.get("name"),
                "page_access_token": p.get("access_token"),  # IMPORTANT (used for IG publishing)
                "ig_user_id": str(ig.get("id")),
                "ig_username": ig.get("username"),
            })
        return out

    # -----------------------------
    # Content Publishing primitives
    # -----------------------------
    @classmethod
    def create_media_container(cls, ig_user_id: str, page_access_token: str, *, caption: str = "", image_url=None, video_url=None, media_type=None, children=None, is_carousel_item=False):
        """
        POST /{ig-user-id}/media
        Returns {"id": "<creation_id>"}
        """
        url = f"{cls.GRAPH_BASE}/{ig_user_id}/media"
        payload = {
            "access_token": page_access_token,
        }

        if caption:
            payload["caption"] = caption

        if is_carousel_item:
            payload["is_carousel_item"] = "true"

        if media_type:
            payload["media_type"] = media_type  # IMAGE, VIDEO, CAROUSEL, REELS (as supported by Meta)

        if image_url:
            payload["image_url"] = image_url
        if video_url:
            payload["video_url"] = video_url

        if children:
            # children = comma-separated container IDs
            payload["children"] = ",".join(children)

        r = requests.post(url, data=payload, timeout=120)
        data = r.json()
        if r.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Instagram create container failed: {data}")
        return data

    @classmethod
    def get_container_status(cls, creation_id: str, page_access_token: str):
        """
        GET /{creation_id}?fields=status_code,status
        status_code often: IN_PROGRESS, FINISHED, ERROR
        """
        url = f"{cls.GRAPH_BASE}/{creation_id}"
        params = {"fields": "status_code,status", "access_token": page_access_token}
        r = requests.get(url, params=params, timeout=60)
        data = r.json()
        if r.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Instagram container status failed: {data}")
        return data

    @classmethod
    def publish_container(cls, ig_user_id: str, page_access_token: str, creation_id: str):
        """
        POST /{ig-user-id}/media_publish
        Returns {"id":"<ig_media_id>"}
        """
        url = f"{cls.GRAPH_BASE}/{ig_user_id}/media_publish"
        payload = {
            "creation_id": creation_id,
            "access_token": page_access_token,
        }
        r = requests.post(url, data=payload, timeout=120)
        data = r.json()
        if r.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Instagram publish failed: {data}")
        return data

    # -----------------------------
    # High-level publish helpers
    # -----------------------------
    @classmethod
    def publish_feed_image(cls, ig_user_id: str, page_access_token: str, image_url: str, caption: str):
        container = cls.create_media_container(
            ig_user_id,
            page_access_token,
            caption=caption,
            image_url=image_url,
            media_type="IMAGE",
        )
        return cls.publish_container(ig_user_id, page_access_token, container["id"])

    @classmethod
    def publish_feed_video(cls, ig_user_id: str, page_access_token: str, video_url: str, caption: str):
        container = cls.create_media_container(
            ig_user_id,
            page_access_token,
            caption=caption,
            video_url=video_url,
            media_type="VIDEO",
        )

        # Poll until FINISHED (video containers usually async)
        creation_id = container["id"]
        for _ in range(40):  # ~40 * 3s = 2 minutes
            st = cls.get_container_status(creation_id, page_access_token)
            if (st.get("status_code") or "").upper() == "FINISHED":
                break
            if (st.get("status_code") or "").upper() == "ERROR":
                raise Exception(f"Instagram video processing ERROR: {st}")
            time.sleep(3)

        return cls.publish_container(ig_user_id, page_access_token, creation_id)

    @classmethod
    def publish_reel(cls, ig_user_id: str, page_access_token: str, video_url: str, caption: str):
        """
        Reels are typically created as a media container with media_type=REELS.
        Some accounts/apps may need extra requirements/approval.
        """
        container = cls.create_media_container(
            ig_user_id,
            page_access_token,
            caption=caption,
            video_url=video_url,
            media_type="REELS",
        )

        creation_id = container["id"]
        for _ in range(50):
            st = cls.get_container_status(creation_id, page_access_token)
            if (st.get("status_code") or "").upper() == "FINISHED":
                break
            if (st.get("status_code") or "").upper() == "ERROR":
                raise Exception(f"Instagram reel processing ERROR: {st}")
            time.sleep(3)

        return cls.publish_container(ig_user_id, page_access_token, creation_id)

    @classmethod
    def publish_carousel(cls, ig_user_id: str, page_access_token: str, media_items: list, caption: str):
        """
        Carousel flow:
          1) Create child containers (is_carousel_item=true)
          2) Create parent container media_type=CAROUSEL children=<ids>
          3) Publish parent container
        """
        child_ids = []

        for item in media_items:
            at = (item.get("asset_type") or "").lower()
            if at == "image":
                c = cls.create_media_container(
                    ig_user_id,
                    page_access_token,
                    image_url=item["url"],
                    is_carousel_item=True,
                    media_type="IMAGE",
                )
            elif at == "video":
                c = cls.create_media_container(
                    ig_user_id,
                    page_access_token,
                    video_url=item["url"],
                    is_carousel_item=True,
                    media_type="VIDEO",
                )
                # wait for each video child
                cid = c["id"]
                for _ in range(40):
                    st = cls.get_container_status(cid, page_access_token)
                    if (st.get("status_code") or "").upper() == "FINISHED":
                        break
                    if (st.get("status_code") or "").upper() == "ERROR":
                        raise Exception(f"Instagram carousel child video ERROR: {st}")
                    time.sleep(3)
            else:
                raise Exception(f"Unsupported carousel asset_type: {at}")

            child_ids.append(c["id"])

        parent = cls.create_media_container(
            ig_user_id,
            page_access_token,
            caption=caption,
            media_type="CAROUSEL",
            children=child_ids,
        )

        # parent may also process async
        pid = parent["id"]
        for _ in range(40):
            st = cls.get_container_status(pid, page_access_token)
            if (st.get("status_code") or "").upper() == "FINISHED":
                break
            if (st.get("status_code") or "").upper() == "ERROR":
                raise Exception(f"Instagram carousel parent ERROR: {st}")
            time.sleep(3)

        return cls.publish_container(ig_user_id, page_access_token, pid)