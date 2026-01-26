# app/services/social/adapters/facebook_adapter.py
import os
import requests
from ....constants.service_code import HTTP_STATUS_CODES


class FacebookAdapter:
    GRAPH_BASE = os.getenv("FACEBOOK_GRAPH_API_URL", "https://graph.facebook.com/v20.0")

    @classmethod
    def list_pages(cls, user_access_token: str):
        url = f"{cls.GRAPH_BASE}/me/accounts"
        params = {
            "fields": "id,name,access_token,category,tasks",
            "access_token": user_access_token
        }
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if r.status_code != 200:
            raise Exception(f"Meta error: {data}")
        return data.get("data", [])

    @staticmethod
    def publish_page_feed(page_id: str, page_access_token: str, message: str, link: str = None) -> dict:
        url = f"{FacebookAdapter.GRAPH_BASE}/{page_id}/feed"
        payload = {"message": message, "access_token": page_access_token}
        if link:
            payload["link"] = link

        resp = requests.post(url, data=payload, timeout=30)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook publish failed: {data}")
        return data

    @staticmethod
    def publish_page_photo(page_id: str, page_access_token: str, image_url: str, caption: str = "") -> dict:
        """
        POST /{page_id}/photos with a public URL (Cloudinary URL works)
        """
        url = f"{FacebookAdapter.GRAPH_BASE}/{page_id}/photos"
        payload = {
            "url": image_url,
            "caption": caption or "",
            "access_token": page_access_token,
            "published": "true",
        }
        resp = requests.post(url, data=payload, timeout=60)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook photo publish failed: {data}")
        return data