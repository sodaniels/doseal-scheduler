import os
import requests

from ....constants.service_code import HTTP_STATUS_CODES


class FacebookAdapter:
    GRAPH_BASE = os.getenv("FACEBOOK_GRAPH_API_URL", "https://graph.facebook.com/v20.0")

    # ----------------------------
    # Pages listing
    # ----------------------------
    @classmethod
    def list_pages(cls, user_access_token: str):
        url = f"{cls.GRAPH_BASE}/me/accounts"
        params = {
            "fields": "id,name,access_token,category,tasks",
            "access_token": user_access_token
        }
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if r.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Meta error: {data}")
        return data.get("data", [])

    # ----------------------------
    # Feed post (text + link)
    # POST /{page_id}/feed
    # ----------------------------
    @classmethod
    def publish_page_feed(cls, page_id: str, page_access_token: str, message: str, link: str = None) -> dict:
        url = f"{cls.GRAPH_BASE}/{page_id}/feed"
        payload = {
            "message": message or "",
            "access_token": page_access_token,
        }
        if link:
            payload["link"] = link

        resp = requests.post(url, data=payload, timeout=60)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook feed publish failed: {data}")
        return data  # {"id": "<page_post_id>"}

    # ----------------------------
    # Photo post (single image)
    # POST /{page_id}/photos
    # ----------------------------
    @classmethod
    def publish_page_photo(cls, page_id: str, page_access_token: str, image_url: str, caption: str = "") -> dict:
        url = f"{cls.GRAPH_BASE}/{page_id}/photos"
        payload = {
            "url": image_url,          # remote image URL (Cloudinary)
            "caption": caption or "",
            "access_token": page_access_token,
        }

        resp = requests.post(url, data=payload, timeout=120)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook photo publish failed: {data}")

        # Usually returns {"id": "<photo_id>", "post_id": "<page_post_id>"}
        return data

    # ----------------------------
    # Video post (feed video)
    # POST /{page_id}/videos
    # ----------------------------
    @classmethod
    def publish_page_video(cls, page_id: str, page_access_token: str, video_url: str, description: str = "") -> dict:
        url = f"{cls.GRAPH_BASE}/{page_id}/videos"

        # Graph API commonly uses file_url for hosted videos
        payload = {
            "file_url": video_url,
            "description": description or "",
            "access_token": page_access_token,
        }

        resp = requests.post(url, data=payload, timeout=300)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook video publish failed: {data}")

        # Usually returns {"id": "<video_id>"}
        return data

    # ----------------------------
    # Reels (Page Reels)
    # POST /{page_id}/video_reels
    #
    # NOTE:
    # - This endpoint/params can vary by API version/app permission.
    # - Some apps must use resumable upload instead of URL-based upload.
    # If URL upload fails in your app, you’ll implement resumable upload next.
    # ----------------------------
    @classmethod
    def publish_page_reel(cls, page_id: str, page_access_token: str, video_url: str, description: str = "", share_to_feed: bool = True) -> dict:
        url = f"{cls.GRAPH_BASE}/{page_id}/video_reels"
        payload = {
            # commonly supported patterns are "video_url" or "file_url" depending on rollout
            "video_url": video_url,
            "description": description or "",
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": page_access_token,
        }

        resp = requests.post(url, data=payload, timeout=300)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            # fallback attempt: some setups accept file_url instead of video_url
            payload.pop("video_url", None)
            payload["file_url"] = video_url

            resp2 = requests.post(url, data=payload, timeout=300)
            data2 = resp2.json()
            if resp2.status_code != HTTP_STATUS_CODES["OK"]:
                raise Exception(f"Facebook reels publish failed: {data2}")
            return data2

        return data

    # ----------------------------
    # Stories (Facebook Page stories)
    #
    # Practical reality:
    # - This is not reliably supported for Pages via public Graph API for most apps.
    # - Many schedulers treat this as “manual publish required” unless you have partner access.
    # ----------------------------
    @classmethod
    def publish_page_story(cls, *args, **kwargs) -> dict:
        raise Exception(
            "Facebook Page Stories publishing is not available via public Graph API for most apps. "
            "Mark this placement as 'manual_required' or integrate an approved partner channel."
        )