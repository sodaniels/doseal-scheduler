import requests
from ..publisher_base import SocialPublisherBase

class PinterestPublisher(SocialPublisherBase):
    PLATFORM = "pinterest"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        board_id = (self.account.get("meta") or {}).get("board_id")
        if not board_id:
            raise Exception("Pinterest requires social_accounts.meta.board_id")

        caption = post.get("caption") or ""
        link = post.get("link")
        media = post.get("media") or {"type": "none"}

        if media.get("type") != "image":
            raise Exception("Pinterest requires media.type=image")

        if not media.get("url"):
            raise Exception("Pinterest requires media.url (public image URL)")

        title = (post.get("extra") or {}).get("title") or (caption[:80] if caption else "Scheduled Pin")

        body = {
            "board_id": board_id,
            "title": title,
            "description": caption,
            "link": link,
            "media_source": {"source_type": "image_url", "url": media["url"]},
        }

        r = requests.post(
            "https://api.pinterest.com/v5/pins",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30
        )
        if r.status_code >= 400:
            raise Exception(f"Pinterest pin failed: {r.status_code} {r.text}")

        data = r.json()
        return {"provider_post_id": data.get("id"), "raw": data}