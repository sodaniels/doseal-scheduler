import requests
from ..publisher_base import SocialPublisherBase

class ThreadsPublisher(SocialPublisherBase):
    PLATFORM = "threads"

    def publish(self, post: dict) -> dict:
        token = post["auth"]["access_token"]
        caption = post.get("caption") or ""
        media = post.get("media") or {"type": "none"}

        create_url = "https://graph.threads.net/me/threads"
        params = {"text": caption}

        if media.get("type") == "image":
            if not media.get("url"):
                raise Exception("Threads image requires media.url")
            params.update({"media_type": "IMAGE", "image_url": media["url"]})
        elif media.get("type") == "video":
            if not media.get("url"):
                raise Exception("Threads video requires media.url")
            params.update({"media_type": "VIDEO", "video_url": media["url"]})
        else:
            params.update({"media_type": "TEXT", "auto_publish_text": "true"})

        r1 = requests.post(
            create_url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60
        )
        if r1.status_code >= 400:
            raise Exception(f"Threads create failed: {r1.status_code} {r1.text}")

        creation_id = r1.json().get("id") or r1.json().get("creation_id")
        if not creation_id:
            raise Exception(f"Threads missing creation id: {r1.text}")

        pub_url = "https://graph.threads.net/me/threads_publish"
        r2 = requests.post(
            pub_url,
            params={"creation_id": creation_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30
        )
        if r2.status_code >= 400:
            raise Exception(f"Threads publish failed: {r2.status_code} {r2.text}")

        provider_id = r2.json().get("id") or r2.json().get("post_id")
        return {"provider_post_id": provider_id, "raw": r2.json()}