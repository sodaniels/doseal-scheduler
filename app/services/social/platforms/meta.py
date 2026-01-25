# app/services/social/platforms/meta.py
import os, requests
from ..publisher_base import SocialPublisherBase

class MetaPublisher(SocialPublisherBase):
    PLATFORM = "meta"

    def authorize_url(self, state: str) -> str:
        app_id = os.getenv("META_APP_ID")
        redirect_uri = os.getenv("META_REDIRECT_URI")  # e.g. https://api.yourapp.com/social/oauth/meta/callback
        scopes = [
            # you'll request what you need based on your features
            "pages_manage_posts",
            "pages_read_engagement",
            "instagram_basic",
            "instagram_content_publish",
            "threads_basic",
            "threads_content_publish",
        ]
        return (
            "https://www.facebook.com/v19.0/dialog/oauth"
            f"?client_id={app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&state={state}"
            f"&scope={','.join(scopes)}"
        )

    def exchange_code(self, code: str) -> dict:
        app_id = os.getenv("META_APP_ID")
        secret = os.getenv("META_APP_SECRET")
        redirect_uri = os.getenv("META_REDIRECT_URI")

        r = requests.get("https://graph.facebook.com/v19.0/oauth/access_token", params={
            "client_id": app_id,
            "client_secret": secret,
            "redirect_uri": redirect_uri,
            "code": code
        }, timeout=30)
        data = r.json()
        return {
            "access_token": data.get("access_token"),
            "refresh_token": None,
            "expires_at": None,
            "scopes": [],
        }

    def list_destinations(self, access_token: str) -> list:
        # return FB pages, IG accounts, Threads profiles (depending on your integration)
        # Example: GET /me/accounts for pages
        return []

    def publish(self, access_token: str, destination: dict, post: dict) -> dict:
        # You will branch based on destination type:
        # page -> /{page-id}/feed
        # instagram -> container + publish flow
        # threads -> threads publish endpoint
        return {"provider_post_id": "TODO", "raw": {}}