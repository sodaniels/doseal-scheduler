# app/services/publisher.py

from ...models.social_account import SocialAccount
from .platforms.facebook import FacebookAdapter
from .platforms.instagram import InstagramAdapter
from ...services.platforms.threads import ThreadsAdapter
from ...services.platforms.x import XAdapter
from ...services.platforms.linkedin import LinkedInAdapter
from ...services.platforms.pinterest import PinterestAdapter
from ...services.platforms.tiktok import TikTokAdapter
from ...services.platforms.youtube import YouTubeAdapter

PLATFORM_ADAPTERS = {
    "facebook": FacebookAdapter,
    "instagram": InstagramAdapter,
    "threads": ThreadsAdapter,
    "x": XAdapter,
    "linkedin": LinkedInAdapter,
    "pinterest": PinterestAdapter,
    "tiktok": TikTokAdapter,
    "youtube": YouTubeAdapter,
}

class PublisherService:
    @staticmethod
    def publish_to_platform(business_id, user__id, platform, post_payload):
        acc = SocialAccount.get_account(business_id, user__id, platform)
        if not acc:
            raise Exception(f"{platform} account not connected")

        adapter_cls = PLATFORM_ADAPTERS.get(platform)
        if not adapter_cls:
            raise Exception(f"Unsupported platform: {platform}")

        adapter = adapter_cls(acc)
        return adapter.publish(post_payload)