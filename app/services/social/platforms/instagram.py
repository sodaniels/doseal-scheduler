import requests
import time
from ..publisher_base import SocialPublisherBase

class InstagramPublisher(SocialPublisherBase):
    PLATFORM = "instagram"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        ig_user_id = (self.account.get("meta") or {}).get("ig_user_id")
        if not ig_user_id:
            raise Exception("Instagram requires social_accounts.meta.ig_user_id")

        caption = post.get("caption") or ""
        media = post.get("media") or {"type": "none"}

        if media.get("type") not in ("image", "video"):
            raise Exception("Instagram requires media.type image|video (no text-only posting)")

        # 1) Create container
        create_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media"
        data = {"access_token": token, "caption": caption}

        if media["type"] == "image":
            if not media.get("url"):
                raise Exception("Instagram image requires media.url (public URL)")
            data["image_url"] = media["url"]

        if media["type"] == "video":
            if not media.get("url"):
                raise Exception("Instagram video requires media.url (public URL)")
            data["video_url"] = media["url"]

        r1 = requests.post(create_url, data=data, timeout=60)
        if r1.status_code >= 400:
            raise Exception(f"IG create container failed: {r1.status_code} {r1.text}")

        creation_id = r1.json().get("id")
        if not creation_id:
            raise Exception(f"IG container missing id: {r1.text}")

        # Give Meta a moment for video processing
        if media["type"] == "video":
            time.sleep(3)

        # 2) Publish container
        publish_url = f"https://graph.facebook.com/v20.0/{ig_user_id}/media_publish"
        r2 = requests.post(
            publish_url,
            data={"access_token": token, "creation_id": creation_id},
            timeout=30
        )
        if r2.status_code >= 400:
            raise Exception(f"IG publish failed: {r2.status_code} {r2.text}")

        return {"provider_post_id": r2.json().get("id"), "raw": r2.json()}