import os
import requests
from ..publisher_base import SocialPublisherBase

class LinkedInPublisher(SocialPublisherBase):
    PLATFORM = "linkedin"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        author_urn = (self.account.get("meta") or {}).get("author_urn")
        if not author_urn:
            raise Exception("LinkedIn requires social_accounts.meta.author_urn (urn:li:person:... or urn:li:organization:...)")

        caption = post.get("caption") or ""
        link = post.get("link")
        commentary = (caption + ("\n" + link if link else "")).strip()

        body = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": []
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False
        }

        li_version = os.getenv("LINKEDIN_VERSION", "202601")

        r = requests.post(
            "https://api.linkedin.com/rest/posts",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "LinkedIn-Version": li_version,
                "Content-Type": "application/json",
            },
            timeout=30
        )
        if r.status_code >= 400:
            raise Exception(f"LinkedIn post failed: {r.status_code} {r.text}")

        post_id = r.headers.get("x-restli-id")
        return {"provider_post_id": post_id, "raw": {"headers": dict(r.headers)}}