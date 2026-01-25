# app/services/social/registry.py
from .platforms.facebook import FacebookPublisher
from .platforms.instagram import InstagramPublisher
from .platforms.threads import ThreadsPublisher
from .platforms.x import XPublisher
from .platforms.linkedin import LinkedInPublisher
from .platforms.pinterest import PinterestPublisher
from .platforms.youtube import YouTubePublisher
from .platforms.tiktok import TikTokPublisher

PUBLISHERS = {
    "facebook": FacebookPublisher,
    "instagram": InstagramPublisher,
    "threads": ThreadsPublisher,
    "x": XPublisher,
    "linkedin": LinkedInPublisher,
    "pinterest": PinterestPublisher,
    "youtube": YouTubePublisher,
    "tiktok": TikTokPublisher,
}

def get_publisher(platform: str):
    cls = PUBLISHERS.get(platform)
    if not cls:
        raise Exception(f"Unsupported platform: {platform}")
    return cls