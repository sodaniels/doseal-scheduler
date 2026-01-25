import requests
from ..publisher_base import SocialPublisherBase

class XPublisher(SocialPublisherBase):
    PLATFORM = "x"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        if not token:
            raise Exception("X requires user OAuth access token (Bearer)")

        text = (post.get("caption") or "").strip()
        link = post.get("link")
        if link:
            text = (text + "\n" + link).strip()

        url = "https://api.x.com/2/tweets"
        r = requests.post(
            url,
            json={"text": text},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30
        )
        if r.status_code >= 400:
            raise Exception(f"X tweet failed: {r.status_code} {r.text}")

        data = r.json()
        provider_id = (data.get("data") or {}).get("id")
        return {"provider_post_id": provider_id, "raw": data}