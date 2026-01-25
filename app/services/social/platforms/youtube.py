import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ..publisher_base import SocialPublisherBase

class YouTubePublisher(SocialPublisherBase):
    PLATFORM = "youtube"

    def publish(self, post: dict) -> dict:
        access_token = post["auth"]["access_token"]
        refresh_token = post["auth"]["refresh_token"]

        if not refresh_token:
            raise Exception("YouTube requires refresh_token (offline access).")

        media = post.get("media") or {"type": "none"}
        if media.get("type") != "video":
            raise Exception("YouTube requires media.type=video")

        file_path = media.get("file_path")
        if not file_path:
            raise Exception("YouTube requires media.file_path (local path on server)")

        extra = post.get("extra") or {}
        title = extra.get("title") or "Scheduled Upload"
        privacy = extra.get("privacyStatus") or "public"
        description = post.get("caption") or ""

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {"title": title, "description": description, "categoryId": "22"},
            "status": {"privacyStatus": privacy},
        }

        media_upload = MediaFileUpload(file_path, chunksize=-1, resumable=True)
        req = youtube.videos().insert(part="snippet,status", body=body, media_body=media_upload)
        resp = req.execute()

        return {"provider_post_id": resp.get("id"), "raw": resp}