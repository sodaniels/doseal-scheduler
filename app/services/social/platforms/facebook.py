import requests
from ..publisher_base import SocialPublisherBase

class FacebookPublisher(SocialPublisherBase):
    PLATFORM = "facebook"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        page_id = (self.account.get("meta") or {}).get("page_id")
        if not page_id:
            raise Exception("Facebook requires social_accounts.meta.page_id")

        caption = post.get("caption") or ""
        link = post.get("link")

        url = f"https://graph.facebook.com/v20.0/{page_id}/feed"
        data = {"access_token": token, "message": caption}
        if link:
            data["link"] = link

        r = requests.post(url, data=data, timeout=30)
        if r.status_code >= 400:
            raise Exception(f"Facebook publish failed: {r.status_code} {r.text}")

        return {"provider_post_id": r.json().get("id"), "raw": r.json()}