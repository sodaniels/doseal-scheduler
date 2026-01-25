from ..publisher_base import SocialPublisherBase

class TikTokPublisher(SocialPublisherBase):
    PLATFORM = "tiktok"

    def publish(self, post: dict) -> dict:
        # TikTok posting requires approved app + correct scopes.
        # Implement after your TikTok "Content Posting API" is approved.
        raise Exception("TikTok publishing not enabled: requires approved Content Posting API + scopes.")