from ...models.social.social_account import SocialAccount
from .registry import get_publisher

class SocialPublishService:
    @staticmethod
    def publish_one(business_id: str, user__id: str, platform: str, post_payload: dict) -> dict:
        acc = SocialAccount.get_account(business_id, user__id, platform)
        if not acc:
            raise Exception(f"{platform} account not connected")

        publisher_cls = get_publisher(platform)
        publisher = publisher_cls(acc)

        payload = dict(post_payload)
        payload["auth"] = {
            "access_token": acc.get("access_token_plain"),
            "refresh_token": acc.get("refresh_token_plain"),
        }
        return publisher.publish(payload)