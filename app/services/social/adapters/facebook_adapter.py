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
    # -------------------------------
    # Reels (Page Reels) - FIXED
    # -------------------------------
    @classmethod
    def publish_page_reel(
        cls,
        page_id: str,
        page_access_token: str,
        video_url: str,
        description: str = "",
        file_size_bytes: int | None = None,
        share_to_feed: bool = False,
    ) -> dict:
        """
        Publishes a Facebook Page REEL using resumable upload (START -> TRANSFER -> FINISH).

        Requirements:
          - video_url must be publicly reachable
          - file_size_bytes is strongly recommended (use Cloudinary 'bytes')

        Returns:
          - FINISH response (contains id in many cases)
        """

        if not video_url:
            raise Exception("video_url is required for reels")

        # If you have Cloudinary bytes in your scheduled post, pass it in.
        if not file_size_bytes:
            # Some apps can work without it, but Meta often requires it.
            raise Exception("file_size_bytes is required for reels (use media.bytes from Cloudinary)")

        # --------------------
        # 1) START
        # --------------------
        start_url = f"{cls.GRAPH_BASE}/{page_id}/video_reels"
        start_payload = {
            "upload_phase": "start",
            "file_size": int(file_size_bytes),
            "access_token": page_access_token,
        }

        r1 = requests.post(start_url, data=start_payload, timeout=60)
        data1 = r1.json()
        if r1.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook reels START failed: {data1}")

        video_id = data1.get("video_id") or data1.get("id")
        upload_url = data1.get("upload_url")

        if not video_id or not upload_url:
            raise Exception(f"Facebook reels START missing video_id/upload_url: {data1}")

        # --------------------
        # 2) TRANSFER
        # --------------------
        # Most implementations use upload_url + file_url.
        # If Meta rejects file_url on your app, you’ll need binary upload (we can add that next).
        transfer_payload = {
            "upload_phase": "transfer",
            "start_offset": 0,
            "access_token": page_access_token,
            "video_id": video_id,
            "file_url": video_url,
        }

        r2 = requests.post(upload_url, data=transfer_payload, timeout=600)
        data2 = r2.json() if r2.headers.get("content-type", "").startswith("application/json") else {"raw": r2.text}

        if r2.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook reels TRANSFER failed: {data2}")

        # --------------------
        # 3) FINISH (publish)
        # --------------------
        finish_payload = {
            "upload_phase": "finish",
            "video_id": video_id,
            "video_state": "PUBLISHED",
            "description": description or "",
            "access_token": page_access_token,
        }

        # This flag is the “like Hootsuite” behavior:
        # - if share_to_feed=True, the reel should also appear in feed
        finish_payload["share_to_feed"] = "true" if share_to_feed else "false"

        r3 = requests.post(start_url, data=finish_payload, timeout=120)
        data3 = r3.json()

        if r3.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook reels FINISH failed: {data3}")

        # Return useful identifiers
        data3["_video_id"] = video_id
        return data3


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