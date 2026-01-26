import requests, os
from ....constants.service_code import (
    HTTP_STATUS_CODES,
)

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
        """
        Publish a post to a Facebook Page feed.
        POST /{page_id}/feed
        """
        url = f"{FacebookAdapter.GRAPH_BASE}/{page_id}/feed"
        payload = {
            "message": message,
            "access_token": page_access_token,
        }
        if link:
            payload["link"] = link

        resp = requests.post(url, data=payload, timeout=30)
        data = resp.json()

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            raise Exception(f"Facebook publish failed: {data}")

        # returns {"id": "<page_post_id>"}
        return data


































