# app/services/social/jobs.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time, os
import requests
import math

from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...services.social.adapters.instagram_adapter import InstagramAdapter
from ...services.social.adapters.x_adapter import XAdapter
from ...services.social.adapters.tiktok_adapter import TikTokAdapter
from ...services.social.adapters.linkedin_adapter import LinkedInAdapter
from ...services.social.adapters.threads_adapter import ThreadsAdapter
from ...services.social.adapters.youtube_adapter import YouTubeAdapter
from ...utils.logger import Log

from .appctx import run_in_app_context


# -----------------------------
# Small helpers
# -----------------------------
def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    return []


def _build_caption(text: str, link: Optional[str]) -> str:
    caption = (text or "").strip()
    if link:
        caption = f"{caption}\n\n{link}".strip() if caption else link.strip()
    return caption.strip()


def _is_ig_not_ready_error(err: Exception | str) -> bool:
    s = str(err)
    return (
        "Media ID is not available" in s
        or "media is not ready for publishing" in s
        or "The media is not ready for publishing" in s
        or "code': 9007" in s
        or "error_subcode': 2207027" in s
    )


def _download_media_bytes(url: str) -> tuple[bytes, str]:
    """
    Download media from Cloudinary (or any HTTPS URL).
    Returns: (bytes, content_type)
    """
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    content_type = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    return r.content, content_type


# -----------------------------
# Token fetchers
# -----------------------------
def _get_facebook_page_token(post: dict, destination_id: str) -> str:
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "facebook",
        destination_id,
    )
    if not acct or not acct.get("access_token_plain"):
        raise Exception(f"Missing facebook destination token for destination_id={destination_id}")
    return acct["access_token_plain"]


def _get_instagram_token(post: dict, ig_user_id: str) -> str:
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "instagram",
        ig_user_id,
    )
    if not acct or not acct.get("access_token_plain"):
        raise Exception(f"Missing instagram destination token for destination_id={ig_user_id}")
    return acct["access_token_plain"]


def _get_x_oauth_tokens(post: dict, destination_id: str) -> Dict[str, str]:
    """
    For X we stored:
      access_token_plain  -> oauth_token
      refresh_token_plain -> oauth_token_secret
    """
    acct = SocialAccount.get_destination(post["business_id"], post["user__id"], "x", destination_id)
    if not acct:
        raise Exception(f"Missing X destination for destination_id={destination_id}")

    oauth_token = acct.get("access_token_plain")
    oauth_token_secret = acct.get("refresh_token_plain")
    if not oauth_token or not oauth_token_secret:
        raise Exception("Missing X oauth_token/oauth_token_secret (reconnect X account).")

    return {"oauth_token": oauth_token, "oauth_token_secret": oauth_token_secret}


def _get_tiktok_tokens(post: dict, destination_id: str) -> Dict[str, Any]:
    """
    Reads stored SocialAccount for platform=tiktok, destination_id=open_id.

    Stored fields:
      access_token_plain  -> access_token
      refresh_token_plain -> refresh_token

    Returns:
      {
        "access_token": str,
        "refresh_token": Optional[str],
        "_acct": dict (full SocialAccount record)
      }
    """
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "tiktok",
        destination_id,
    )
    if not acct:
        raise Exception(f"Missing tiktok destination for destination_id={destination_id}")

    access_token = acct.get("access_token_plain")
    if not access_token:
        raise Exception(f"Missing TikTok access_token_plain (reconnect TikTok) destination_id={destination_id}")

    return {
        "access_token": access_token,
        "refresh_token": acct.get("refresh_token_plain"),
        "_acct": acct,
    }


def _get_linkedin_access_token(post: dict, destination_id: str) -> str:
    """
    For LinkedIn we store:
      access_token_plain  -> access_token
      refresh_token_plain -> refresh_token (optional, depending on your app)
    """
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "linkedin",
        destination_id,
    )
    if not acct:
        raise Exception(f"Missing LinkedIn destination for destination_id={destination_id}")

    access_token = acct.get("access_token_plain")
    if not access_token:
        raise Exception("Missing LinkedIn access_token (reconnect LinkedIn account).")

    return access_token


# -----------------------------
# Instagram: create -> wait -> publish (with publish retry)
# -----------------------------
def _ig_create_wait_publish(
    *,
    ig_user_id: str,
    access_token: str,
    creation_id: str,
    wait_attempts: int = 40,
    wait_sleep: float = 3.0,
    publish_attempts: int = 6,
    publish_sleep: float = 3.0,
) -> Dict[str, Any]:
    """
    - Waits for container processing to FINISH
    - Then attempts publish, retrying "not ready" errors a few times
    """
    status_payload = InstagramAdapter.wait_until_container_ready(
        creation_id,
        access_token,
        max_attempts=wait_attempts,
        sleep_seconds=wait_sleep,
    )

    status_code = (status_payload.get("status_code") or "").upper()
    if status_code != "FINISHED":
        raise Exception(f"Instagram container not ready: {status_payload}")

    last_publish_err: Optional[Exception] = None
    for _ in range(publish_attempts):
        try:
            pub = InstagramAdapter.publish_container(
                ig_user_id=ig_user_id,
                access_token=access_token,
                creation_id=creation_id,
            )
            return {"status": status_payload, "publish": pub}
        except Exception as e:
            last_publish_err = e
            if _is_ig_not_ready_error(e):
                time.sleep(publish_sleep)
                continue
            raise

    raise Exception(f"Instagram publish failed after retries: {last_publish_err}")


# -----------------------------
# Facebook publisher
# -----------------------------
def _publish_to_facebook(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "facebook",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": dest.get("destination_type"),
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    destination_id = r["destination_id"]
    if not destination_id:
        r["error"] = "Missing destination_id"
        return r

    placement = r["placement"]
    page_access_token = _get_facebook_page_token(post, destination_id)
    caption = _build_caption(text, link)

    first_media = media[0] if media else {}
    asset_type = (first_media.get("asset_type") or "").lower()
    media_url = first_media.get("url")
    media_bytes = first_media.get("bytes")

    if placement == "story":
        raise Exception("Facebook story publishing not supported by this integration (manual required).")

    if placement == "reel":
        if asset_type != "video" or not media_url:
            raise Exception("Facebook reels require a single video media.url")
        if not media_bytes:
            raise Exception("Facebook reels require media.bytes (file_size_bytes)")

        resp = FacebookAdapter.publish_page_reel(
            page_id=destination_id,
            page_access_token=page_access_token,
            video_url=media_url,
            description=caption,
            file_size_bytes=int(media_bytes),
            share_to_feed=False,
        )
        r["status"] = "success"
        r["provider_post_id"] = resp.get("id") or resp.get("post_id")
        r["raw"] = resp
        return r

    # feed
    if asset_type == "image" and media_url:
        resp = FacebookAdapter.publish_page_photo(
            page_id=destination_id,
            page_access_token=page_access_token,
            image_url=media_url,
            caption=caption,
        )
        r["status"] = "success"
        r["provider_post_id"] = resp.get("post_id") or resp.get("id")
        r["raw"] = resp
        return r

    if asset_type == "video" and media_url:
        resp = FacebookAdapter.publish_page_video(
            page_id=destination_id,
            page_access_token=page_access_token,
            video_url=media_url,
            description=caption,
        )
        r["status"] = "success"
        r["provider_post_id"] = resp.get("id")
        r["raw"] = resp
        return r

    resp = FacebookAdapter.publish_page_feed(
        page_id=destination_id,
        page_access_token=page_access_token,
        message=text,
        link=link,
    )
    r["status"] = "success"
    r["provider_post_id"] = resp.get("id")
    r["raw"] = resp
    return r


# -----------------------------
# Instagram publisher
# -----------------------------
def _publish_to_instagram(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "instagram",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": dest.get("destination_type"),
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    ig_user_id = r["destination_id"]
    if not ig_user_id:
        r["error"] = "Missing destination_id"
        return r

    placement = r["placement"]
    caption = _build_caption(text, link)
    access_token = _get_instagram_token(post, ig_user_id)

    # REEL
    if placement == "reel":
        if len(media) != 1:
            raise Exception("Instagram reel requires exactly 1 media item (video).")
        if (media[0].get("asset_type") or "").lower() != "video":
            raise Exception("Instagram reel requires media.asset_type=video.")
        url = media[0].get("url")
        if not url:
            raise Exception("Instagram reel requires media.url.")

        create_resp = InstagramAdapter.create_reel_container(
            ig_user_id=ig_user_id,
            access_token=access_token,
            video_url=url,
            caption=caption,
            share_to_feed=False,
        )
        creation_id = create_resp.get("id")
        if not creation_id:
            raise Exception(f"Instagram create container missing id: {create_resp}")

        flow = _ig_create_wait_publish(
            ig_user_id=ig_user_id,
            access_token=access_token,
            creation_id=creation_id,
        )

        r["status"] = "success"
        r["provider_post_id"] = (flow.get("publish") or {}).get("id")
        r["raw"] = {"create": create_resp, **flow}
        return r

    # STORY
    if placement == "story":
        if len(media) != 1:
            raise Exception("Instagram story requires exactly 1 media item.")
        m = media[0]
        mtype = (m.get("asset_type") or "").lower()
        url = m.get("url")
        if not url:
            raise Exception("Instagram story requires media.url.")
        if mtype not in ("image", "video"):
            raise Exception("Instagram story supports image|video only.")

        if mtype == "image":
            create_resp = InstagramAdapter.create_story_container_image(
                ig_user_id=ig_user_id,
                access_token=access_token,
                image_url=url,
                caption=caption,
            )
        else:
            create_resp = InstagramAdapter.create_story_container_video(
                ig_user_id=ig_user_id,
                access_token=access_token,
                video_url=url,
                caption=caption,
            )

        creation_id = create_resp.get("id")
        if not creation_id:
            raise Exception(f"Instagram create container missing id: {create_resp}")

        flow = _ig_create_wait_publish(
            ig_user_id=ig_user_id,
            access_token=access_token,
            creation_id=creation_id,
        )

        r["status"] = "success"
        r["provider_post_id"] = (flow.get("publish") or {}).get("id")
        r["raw"] = {"create": create_resp, **flow}
        return r

    # FEED
    if placement == "feed":
        if len(media) < 1:
            raise Exception("Instagram feed requires at least 1 media item.")

        # Single media
        if len(media) == 1:
            m = media[0]
            mtype = (m.get("asset_type") or "").lower()
            url = m.get("url")
            if not url:
                raise Exception("Instagram feed requires media.url.")

            # feed video uses REELS with share_to_feed=True
            if mtype == "video":
                create_resp = InstagramAdapter.create_reel_container(
                    ig_user_id=ig_user_id,
                    access_token=access_token,
                    video_url=url,
                    caption=caption,
                    share_to_feed=True,
                )
            elif mtype == "image":
                create_resp = InstagramAdapter.create_feed_container_image(
                    ig_user_id=ig_user_id,
                    access_token=access_token,
                    image_url=url,
                    caption=caption,
                )
            else:
                raise Exception("Instagram feed supports image|video only.")

            creation_id = create_resp.get("id")
            if not creation_id:
                raise Exception(f"Instagram create container missing id: {create_resp}")

            flow = _ig_create_wait_publish(
                ig_user_id=ig_user_id,
                access_token=access_token,
                creation_id=creation_id,
            )

            r["status"] = "success"
            r["provider_post_id"] = (flow.get("publish") or {}).get("id")
            r["raw"] = {"create": create_resp, **flow}
            return r

        # Carousel (2..10)
        child_ids: List[str] = []
        child_raw: List[Dict[str, Any]] = []

        for m in media:
            mtype = (m.get("asset_type") or "").lower()
            url = m.get("url")
            if not url:
                raise Exception("Instagram carousel requires media.url for each item.")

            if mtype == "image":
                child = InstagramAdapter.create_carousel_item_image(
                    ig_user_id=ig_user_id,
                    access_token=access_token,
                    image_url=url,
                )
            elif mtype == "video":
                child = InstagramAdapter.create_carousel_item_video(
                    ig_user_id=ig_user_id,
                    access_token=access_token,
                    video_url=url,
                )
            else:
                raise Exception("Instagram carousel supports image|video only.")

            cid = child.get("id")
            if not cid:
                raise Exception(f"Instagram carousel child missing id: {child}")

            child_ids.append(cid)
            child_raw.append(child)

        carousel = InstagramAdapter.create_carousel_container(
            ig_user_id=ig_user_id,
            access_token=access_token,
            children=child_ids,
            caption=caption,
        )
        carousel_id = carousel.get("id")
        if not carousel_id:
            raise Exception(f"Instagram carousel create missing id: {carousel}")

        flow = _ig_create_wait_publish(
            ig_user_id=ig_user_id,
            access_token=access_token,
            creation_id=carousel_id,
        )

        r["status"] = "success"
        r["provider_post_id"] = (flow.get("publish") or {}).get("id")
        r["raw"] = {"children": child_raw, "carousel_create": carousel, **flow}
        return r

    raise Exception("Invalid instagram placement. Use feed|reel|story.")


# -----------------------------
# X publisher
# -----------------------------
def _publish_to_x(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "x",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": dest.get("destination_type"),
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    destination_id = r["destination_id"]
    if not destination_id:
        r["error"] = "Missing destination_id"
        return r

    consumer_key = os.getenv("X_CONSUMER_KEY")
    consumer_secret = os.getenv("X_CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        raise Exception("Missing X_CONSUMER_KEY / X_CONSUMER_SECRET in env")

    tokens = _get_x_oauth_tokens(post, destination_id)
    oauth_token = tokens["oauth_token"]
    oauth_token_secret = tokens["oauth_token_secret"]

    tweet_text = _build_caption(text, link)
    if len(tweet_text) > 280:
        tweet_text = tweet_text[:277] + "..."

    media_ids: List[str] = []

    if media:
        has_video = any(((m.get("asset_type") or "").lower() == "video") for m in media)
        if has_video:
            media = [next(m for m in media if (m.get("asset_type") or "").lower() == "video")]

        for m in media:
            mtype = (m.get("asset_type") or "").lower()
            url = m.get("url")
            if not url:
                continue

            _raw_bytes, _content_type = _download_media_bytes(url)

            category = "tweet_image" if mtype == "image" else "tweet_video"

            mid = XAdapter.upload_media(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                oauth_token=oauth_token,
                oauth_token_secret=oauth_token_secret,
                media_url=url,
                media_type=mtype,
                media_category=category,
            )

            media_ids.append(str(mid))

    resp = XAdapter.create_tweet(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        oauth_token=oauth_token,
        oauth_token_secret=oauth_token_secret,
        text=tweet_text,
        media_ids=media_ids or None,
    )

    tweet_id = ((resp.get("data") or {}).get("id")) if isinstance(resp, dict) else None

    r["status"] = "success"
    r["provider_post_id"] = tweet_id
    r["raw"] = resp
    return r


# -----------------------------
# TikTok helpers/publisher
# -----------------------------
def _is_tiktok_token_invalid(err: Exception | str) -> bool:
    s = str(err).lower()
    return (
        "access_token_invalid" in s
        or "invalid access token" in s
        or "access token is invalid" in s
        or "token is invalid" in s
        or "invalid or not found" in s
        or "authorization failed" in s
        or "unauthorized" in s
        or "401" in s
    )


def _refresh_tiktok_access_token_or_raise(
    *,
    post: dict,
    destination_id: str,
    destination_type: str,
    tokens: Dict[str, Any],
) -> str:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise Exception("TikTok access token invalid/expired and refresh_token is missing (reconnect TikTok).")

    client_key = os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("TIKTOK_CLIENT_ID")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        raise Exception(
            "TikTok token refresh requires TIKTOK_CLIENT_KEY (or TIKTOK_CLIENT_ID) "
            "and TIKTOK_CLIENT_SECRET in env"
        )

    refreshed = TikTokAdapter.refresh_access_token(
        client_key=client_key,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )

    ref_data = refreshed.get("data") or refreshed
    new_access = ref_data.get("access_token")
    new_refresh = ref_data.get("refresh_token") or refresh_token

    if not new_access:
        raise Exception(f"TikTok OAuth refresh failed: {refreshed}")

    acct = tokens.get("_acct") or {}
    try:
        SocialAccount.upsert_destination(
            business_id=post["business_id"],
            user__id=post["user__id"],
            platform="tiktok",
            destination_id=destination_id,
            destination_type=destination_type or "user",
            destination_name=(acct.get("destination_name") or destination_id),
            access_token_plain=new_access,
            refresh_token_plain=new_refresh,
            token_expires_at=None,
            scopes=(acct.get("scopes") or []),
            platform_user_id=destination_id,
            platform_username=acct.get("platform_username"),
            meta=(acct.get("meta") or {}),
        )
    except Exception:
        pass

    return new_access


def _publish_to_tiktok(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "tiktok",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": dest.get("destination_type") or "user",
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    destination_id = r["destination_id"]
    if not destination_id:
        r["error"] = "Missing destination_id"
        return r

    caption = (_build_caption(text, link) or "").strip()

    if not media:
        raise Exception("TikTok requires media (video or images).")

    images = [m for m in media if ((m.get("asset_type") or "").lower() == "image")]
    videos = [m for m in media if ((m.get("asset_type") or "").lower() == "video")]
    has_video = len(videos) > 0

    tokens = _get_tiktok_tokens(post, destination_id)
    access_token = tokens["access_token"]

    # VIDEO
    if has_video:
        if len(videos) != 1:
            raise Exception("TikTok video publishing supports exactly 1 video media item.")

        v = videos[0] or {}
        video_url = v.get("url")
        if not video_url:
            raise Exception("TikTok video requires media.url")

        video_bytes, _ct = _download_media_bytes(video_url)
        if not video_bytes:
            raise Exception("Downloaded TikTok video is empty")

        video_size = len(video_bytes)

        chunk_size = None
        total_chunk_count = None
        if video_size > 64 * 1024 * 1024:
            chunk_size = 16 * 1024 * 1024
            total_chunk_count = int(math.ceil(video_size / float(chunk_size)))

        def _init_video(a_token: str) -> Dict[str, Any]:
            return TikTokAdapter.init_video_post(
                access_token=a_token,
                post_text=caption,
                video_size_bytes=video_size,
                privacy_level="PUBLIC_TO_EVERYONE",
                chunk_size=chunk_size,
                total_chunk_count=total_chunk_count,
            )

        try:
            init_resp = _init_video(access_token)
        except Exception as e:
            if _is_tiktok_token_invalid(e):
                access_token = _refresh_tiktok_access_token_or_raise(
                    post=post,
                    destination_id=destination_id,
                    destination_type=r["destination_type"],
                    tokens=tokens,
                )
                init_resp = _init_video(access_token)
            else:
                raise

        init_data = init_resp.get("data") or {}
        upload_url = init_data.get("upload_url")
        publish_id = init_data.get("publish_id")

        if not upload_url or not publish_id:
            raise Exception(f"TikTok init missing upload_url/publish_id: {init_resp}")

        if chunk_size and total_chunk_count:
            upload_resp = TikTokAdapter.upload_video_put_chunked(
                upload_url=upload_url,
                video_bytes=video_bytes,
                chunk_size=chunk_size,
            )
        else:
            upload_resp = TikTokAdapter.upload_video_put_single(
                upload_url=upload_url,
                video_bytes=video_bytes,
            )

        status_resp = TikTokAdapter.wait_for_publish(
            access_token=access_token,
            publish_id=publish_id,
            max_wait_seconds=240,
            poll_interval=2.0,
        )

        status_data = status_resp.get("data") or {}
        status_val = (status_data.get("status") or "").lower()

        if status_val in ("failed", "error"):
            raise Exception(f"TikTok publish failed: {status_resp}")

        provider_id = status_data.get("video_id") or publish_id

        r["status"] = "success"
        r["provider_post_id"] = str(provider_id)
        r["raw"] = {"init": init_resp, "upload": upload_resp, "status": status_resp}
        return r

    # PHOTO
    if not images:
        raise Exception("TikTok requires either a video or at least 1 image.")

    image_urls = [m.get("url") for m in images if m.get("url")]
    if not image_urls:
        raise Exception("TikTok photo post requires media.url for images.")

    if len(image_urls) > 35:
        image_urls = image_urls[:35]

    def _init_photo(a_token: str) -> Dict[str, Any]:
        return TikTokAdapter.init_photo_post(
            access_token=a_token,
            post_text=caption,
            image_urls=image_urls,
            privacy_level="PUBLIC_TO_EVERYONE",
        )

    try:
        init_resp = _init_photo(access_token)
    except Exception as e:
        if _is_tiktok_token_invalid(e):
            access_token = _refresh_tiktok_access_token_or_raise(
                post=post,
                destination_id=destination_id,
                destination_type=r["destination_type"],
                tokens=tokens,
            )
            init_resp = _init_photo(access_token)
        else:
            raise

    init_data = init_resp.get("data") or {}
    publish_id = init_data.get("publish_id")
    if not publish_id:
        raise Exception(f"TikTok photo init missing publish_id: {init_resp}")

    status_resp = TikTokAdapter.wait_for_publish(
        access_token=access_token,
        publish_id=publish_id,
        max_wait_seconds=240,
        poll_interval=2.0,
    )

    status_data = status_resp.get("data") or {}
    status_val = (status_data.get("status") or "").lower()

    if status_val in ("failed", "error"):
        raise Exception(f"TikTok photo publish failed: {status_resp}")

    provider_id = status_data.get("video_id") or publish_id

    r["status"] = "success"
    r["provider_post_id"] = str(provider_id)
    r["raw"] = {"init": init_resp, "status": status_resp}
    return r


# -----------------------------
# LinkedIn publisher (USES LinkedInAdapter)
# -----------------------------
def _publish_to_linkedin(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "linkedin",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": (dest.get("destination_type") or "").lower().strip(),
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    destination_id = r["destination_id"]
    destination_type = r["destination_type"]

    if not destination_id:
        r["error"] = "Missing destination_id"
        return r

    if destination_type not in ("author", "organization"):
        r["error"] = "linkedin destination_type must be 'author' or 'organization'"
        return r

    # Build caption early (so it's always defined)
    final_text = _build_caption(text, link).strip()

    # Get token early (so it's always defined OR we return)
    try:
        acct = SocialAccount.get_destination(
            post["business_id"],
            post["user__id"],
            "linkedin",
            destination_id,
        )
        if not acct:
            r["error"] = f"Missing LinkedIn destination for destination_id={destination_id}"
            return r

        access_token = acct.get("access_token_plain")
        if not access_token:
            r["error"] = "Missing LinkedIn access_token_plain (reconnect LinkedIn)."
            return r

    except Exception as e:
        r["error"] = f"Failed to load LinkedIn token: {str(e)}"
        return r

    log_tag = f"[jobs.py][_publish_to_linkedin][{post.get('business_id')}][{post.get('_id') or post.get('post_id')}]"

    # Use adapter (adapter will handle media if implemented there)
    adapter_resp = LinkedInAdapter.publish_post(
        access_token=access_token,
        destination_type=destination_type,
        destination_id=destination_id,
        text=final_text,
        link=None,           # link already merged into final_text
        media=media or None, # adapter decides what to do
        log_tag=log_tag,
    )

    if adapter_resp.get("success"):
        r["status"] = "success"
        r["provider_post_id"] = adapter_resp.get("provider_post_id")
        r["raw"] = adapter_resp.get("raw")
        return r

    r["error"] = adapter_resp.get("error") or "LinkedIn publish failed"
    r["raw"] = adapter_resp.get("raw")
    return r


# -----------------------------
# LinkedIn publisher (USES LinkedInAdapter)
# -----------------------------
def _get_threads_access_token(post: dict, destination_id: str) -> str:
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "threads",
        destination_id,
    )
    if not acct or not acct.get("access_token_plain"):
        raise Exception(f"Missing threads destination token for destination_id={destination_id}")
    return acct["access_token_plain"]

def _publish_to_threads(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "threads",
        "destination_id": str(dest.get("destination_id") or ""),
        "destination_type": dest.get("destination_type") or "user",
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    threads_user_id = r["destination_id"]
    if not threads_user_id:
        r["error"] = "Missing destination_id"
        return r

    # Threads: start with text-only. Media needs specific endpoint support.
    if media:
        r["error"] = "Threads media posting not implemented yet (text-only supported)."
        return r

    access_token = _get_threads_access_token(post, threads_user_id)
    caption = (text or "").strip()

    log_tag = f"[jobs.py][_publish_to_threads][{post.get('business_id')}][{post.get('_id') or post.get('post_id')}]"

    resp = ThreadsAdapter.publish_post(
        threads_user_id=threads_user_id,
        access_token=access_token,
        text=caption,
        link=link,
        log_tag=log_tag,
    )

    if resp.get("success"):
        r["status"] = "success"
        r["provider_post_id"] = resp.get("provider_post_id")
        r["raw"] = resp.get("raw")
        return r

    r["error"] = resp.get("error") or "Threads publish failed"
    r["raw"] = resp.get("raw")
    return r


# -----------------------------
# Youtube publisher
# -----------------------------
def _get_youtube_tokens(post: dict, destination_id: str) -> Dict[str, Any]:
    """
    SocialAccount:
      access_token_plain  -> access_token
      refresh_token_plain -> refresh_token (optional but strongly recommended)
    """
    acct = SocialAccount.get_destination(
        post["business_id"],
        post["user__id"],
        "youtube",
        destination_id,
    )
    if not acct:
        raise Exception(f"Missing youtube destination for destination_id={destination_id}")

    access_token = acct.get("access_token_plain")
    refresh_token = acct.get("refresh_token_plain")

    if not access_token:
        raise Exception("Missing YouTube access_token (reconnect YouTube).")

    return {"access_token": access_token, "refresh_token": refresh_token, "_acct": acct}


def _is_youtube_token_invalid(err: Exception | str) -> bool:
    s = str(err).lower()
    return (
        "invalid_grant" in s
        or "invalid_token" in s
        or "unauthorized" in s
        or "401" in s
        or "authError".lower() in s
    )


def _refresh_youtube_access_token_or_raise(*, post: dict, destination_id: str, tokens: Dict[str, Any], log_tag: str) -> str:
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise Exception("YouTube access token expired/invalid and refresh_token missing (reconnect YouTube).")

    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise Exception("Missing YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET for refresh flow")

    data = YouTubeAdapter.refresh_access_token(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        log_tag=log_tag,
    )

    new_access = data.get("access_token")
    if not new_access:
        raise Exception(f"YouTube refresh did not return access_token: {data}")

    # Persist token (do not block publishing if fails)
    acct = tokens.get("_acct") or {}
    try:
        SocialAccount.upsert_destination(
            business_id=post["business_id"],
            user__id=post["user__id"],
            platform="youtube",
            destination_id=destination_id,
            destination_type=(acct.get("destination_type") or "channel"),
            destination_name=(acct.get("destination_name") or destination_id),

            access_token_plain=new_access,
            refresh_token_plain=refresh_token,
            token_expires_at=None,
            scopes=(acct.get("scopes") or []),
            platform_user_id=(acct.get("platform_user_id") or destination_id),
            platform_username=acct.get("platform_username"),
            meta=(acct.get("meta") or {}),
        )
    except Exception:
        pass

    return new_access

def _publish_to_youtube(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    r = {
        "platform": "youtube",
        "destination_id": str(dest.get("destination_id") or ""),      # channel_id
        "destination_type": dest.get("destination_type") or "channel",
        "placement": (dest.get("placement") or "feed").lower(),
        "status": "failed",
        "provider_post_id": None,
        "error": None,
        "raw": None,
    }

    channel_id = r["destination_id"]
    if not channel_id:
        r["error"] = "Missing destination_id (channel_id)"
        return r

    # YouTube requires a VIDEO.
    videos = [m for m in (media or []) if ((m.get("asset_type") or "").lower() == "video")]
    if len(videos) != 1:
        raise Exception("YouTube publishing requires exactly 1 video media item.")

    v = videos[0] or {}
    video_url = v.get("url")
    if not video_url:
        raise Exception("YouTube video requires media.url")

    # Build title/description.
    # - title max ~100 chars recommended; enforce safe trimming.
    # - description can be the caption + link.
    caption = _build_caption(text, link).strip()
    title = (text or "").strip()
    if not title:
        title = "New video"
    title = title[:100]

    description = caption[:5000] if caption else ""

    log_tag = f"[jobs.py][_publish_to_youtube][{post.get('business_id')}][{post.get('_id') or ''}]"

    tokens = _get_youtube_tokens(post, channel_id)
    access_token = tokens["access_token"]

    # Download bytes (Cloudinary)
    video_bytes, content_type = _download_media_bytes(video_url)
    if not video_bytes:
        raise Exception("Downloaded YouTube video is empty")

    def _do_publish(a_token: str) -> Dict[str, Any]:
        return YouTubeAdapter.publish_video(
            access_token=a_token,
            title=title,
            description=description,
            video_bytes=video_bytes,
            content_type=content_type or "video/mp4",
            tags=None,
            privacy_status="public",
            log_tag=log_tag,
        )

    try:
        resp = _do_publish(access_token)
    except Exception as e:
        if _is_youtube_token_invalid(e):
            access_token = _refresh_youtube_access_token_or_raise(
                post=post,
                destination_id=channel_id,
                tokens=tokens,
                log_tag=log_tag,
            )
            resp = _do_publish(access_token)
        else:
            raise

    # On success, YouTube returns a video resource with "id"
    provider_id = None
    if isinstance(resp, dict):
        provider_id = resp.get("id")

    r["status"] = "success"
    r["provider_post_id"] = provider_id
    r["raw"] = resp
    return r

# -----------------------------
# Main job
# -----------------------------
def _publish_scheduled_post(post_id: str, business_id: str):
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    # Mark as publishing (reset provider_results/error every run)
    ScheduledPost.update_status(
        post_id,
        post["business_id"],
        ScheduledPost.STATUS_PUBLISHING,
        provider_results=[],
        error=None,
    )

    results: List[Dict[str, Any]] = []
    any_success = False
    any_failed = False

    content = post.get("content") or {}
    text = (content.get("text") or "").strip()
    link = content.get("link")

    # global media applies to all destinations unless dest overrides
    global_media = _as_list(content.get("media"))

    for dest in post.get("destinations") or []:
        platform = (dest.get("platform") or "").strip().lower()

        # per-destination overrides
        dest_text = ((dest.get("text") or "")).strip() or text
        dest_link = dest.get("link") or link
        dest_media = _as_list(dest.get("media")) or global_media

        try:
            if platform == "facebook":
                r = _publish_to_facebook(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            elif platform == "instagram":
                r = _publish_to_instagram(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            elif platform == "x":
                r = _publish_to_x(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            elif platform == "tiktok":
                r = _publish_to_tiktok(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            elif platform == "linkedin":
                r = _publish_to_linkedin(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            elif platform == "threads":
                r = _publish_to_threads(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)
                
            elif platform == "youtube":
                r = _publish_to_youtube(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

            else:
                r = {
                    "platform": platform,
                    "destination_id": str(dest.get("destination_id") or ""),
                    "destination_type": dest.get("destination_type"),
                    "placement": (dest.get("placement") or "feed").lower(),
                    "status": "failed",
                    "provider_post_id": None,
                    "error": "Unsupported platform (not implemented)",
                    "raw": None,
                }

            # Ensure dict shape
            if not isinstance(r, dict):
                r = {
                    "platform": platform,
                    "destination_id": str(dest.get("destination_id") or ""),
                    "destination_type": dest.get("destination_type"),
                    "placement": (dest.get("placement") or "feed").lower(),
                    "status": "failed",
                    "provider_post_id": None,
                    "error": f"Publisher returned invalid result type: {type(r)}",
                    "raw": None,
                }

            # Enforce required keys (safe defaults)
            r.setdefault("platform", platform)
            r.setdefault("destination_id", str(dest.get("destination_id") or ""))
            r.setdefault("destination_type", dest.get("destination_type"))
            r.setdefault("placement", (dest.get("placement") or "feed").lower())
            r.setdefault("status", "failed")
            r.setdefault("provider_post_id", None)
            r.setdefault("error", None)
            r.setdefault("raw", None)

            results.append(r)

            if r.get("status") == "success":
                any_success = True
            else:
                any_failed = True
                Log.info(f"{log_tag} destination failed: {r}")

        except Exception as e:
            rr = {
                "platform": platform,
                "destination_id": str(dest.get("destination_id") or ""),
                "destination_type": dest.get("destination_type"),
                "placement": (dest.get("placement") or "feed").lower(),
                "status": "failed",
                "provider_post_id": None,
                "error": str(e),
                "raw": None,
            }
            results.append(rr)
            any_failed = True
            Log.info(f"{log_tag} destination failed: {rr}")

    # Decide overall status
    if any_success and not any_failed:
        overall_status = ScheduledPost.STATUS_PUBLISHED
        overall_error = None

    elif any_success and any_failed:
        overall_status = getattr(ScheduledPost, "STATUS_PARTIAL", ScheduledPost.STATUS_PUBLISHED)
        first_err = next(
            (x.get("error") for x in results if x.get("status") == "failed" and x.get("error")),
            None,
        )
        overall_error = f"Some destinations failed. Example: {first_err}" if first_err else "Some destinations failed."

    else:
        overall_status = ScheduledPost.STATUS_FAILED
        first_err = next((x.get("error") for x in results if x.get("error")), "All destinations failed.")
        overall_error = first_err

    ScheduledPost.update_status(
        post_id,
        post["business_id"],
        overall_status,
        provider_results=results,
        error=overall_error,
    )


def publish_scheduled_post(post_id: str, business_id: str):
    return run_in_app_context(_publish_scheduled_post, post_id, business_id)