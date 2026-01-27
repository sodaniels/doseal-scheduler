# app/services/social/jobs.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time, os
import requests
import json


from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...services.social.adapters.instagram_adapter import InstagramAdapter
from ...services.social.adapters.x_adapter import XAdapter
from ...services.social.adapters.tiktok_adapter import TikTokAdapter
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
        # still in progress after timeout
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

    # -----------------
    # REEL
    # -----------------
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

    # -----------------
    # STORY
    # -----------------
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

    # -----------------
    # FEED
    # -----------------
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

            # ✅ IMPORTANT: feed video uses REELS with share_to_feed=True
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


#------------------------------
# X publisher
#------------------------------
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

    # -----------------------------------------
    # Upload media (download bytes first)
    # -----------------------------------------
    media_ids: List[str] = []

    if media:
        # detect if video exists (X: 1 video max)
        has_video = any(((m.get("asset_type") or "").lower() == "video") for m in media)
        if has_video:
            media = [next(m for m in media if (m.get("asset_type") or "").lower() == "video")]

        for m in media:
            mtype = (m.get("asset_type") or "").lower()
            url = m.get("url")
            if not url:
                continue

            raw_bytes, content_type = _download_media_bytes(url)

            # category
            category = "tweet_image" if mtype == "image" else "tweet_video"

            # IMPORTANT:
            # - images: upload + get media_id
            # - video: chunk upload + finalize + wait processing => then media_id
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

    # -----------------------------------------
    # Create tweet (only after video ready)
    # -----------------------------------------
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
# TikTok token fetcher
# -----------------------------
def _get_tiktok_tokens(post: dict, destination_id: str) -> Dict[str, str]:
    """
    Fetch stored TikTok tokens from social_accounts.

    Convention:
      - access_token_plain  => TikTok access_token
      - refresh_token_plain => TikTok refresh_token (optional but recommended)
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
    refresh_token = acct.get("refresh_token_plain")

    if not access_token:
        raise Exception(f"Missing TikTok access_token for destination_id={destination_id}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "_acct": acct,  # optional: keep for future updates
    }


def _publish_to_tiktok(
    *,
    post: dict,
    dest: dict,
    text: str,
    link: Optional[str],
    media: List[dict],
) -> Dict[str, Any]:
    """
    TikTok rules (for Direct Post via Content Posting API):
      - Video only (most common). Photos require different endpoints/flow depending on your approval.
      - Usually 1 video per post in this flow.
      - Caption length limits are enforced by TikTok; keep your caption short-ish.

    Returns standard result shape.
    """
    r = {
        "platform": "tiktok",
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

    # Build caption (TikTok doesn't do clickable links like IG; link in caption if you want)
    caption = _build_caption(text, link)
    caption = (caption or "").strip()

    # Enforce media rules: TikTok direct post video
    if not media:
        raise Exception("TikTok requires a video media item.")
    if len(media) > 1:
        # keep it strict to avoid unexpected API behavior
        raise Exception("TikTok publishing currently supports exactly 1 video media item.")

    m = media[0] or {}
    mtype = (m.get("asset_type") or "").lower()
    url = m.get("url")
    size_bytes = m.get("bytes")

    if mtype != "video":
        raise Exception("TikTok publishing currently supports video only.")
    if not url:
        raise Exception("TikTok requires media.url for video.")
    if not size_bytes:
        # TikTok init wants size; if missing, we can still compute from downloaded bytes
        size_bytes = None

    # Pull stored tokens
    tokens = _get_tiktok_tokens(post, destination_id)
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")

    # Download video bytes (reuse your helper)
    video_bytes, content_type = _download_media_bytes(url)  # you already use this in X flow
    if not video_bytes:
        raise Exception("Downloaded TikTok video is empty.")

    video_size = int(size_bytes) if size_bytes else len(video_bytes)

    # Try init/upload/publish
    try:
        init_resp = TikTokAdapter.init_direct_post_video(
            access_token=access_token,
            post_text=caption,
            video_size_bytes=video_size,
            privacy_level="PUBLIC_TO_EVERYONE",
        )

    except Exception as e:
        # If token invalid, try refresh once (if we have refresh_token + client creds)
        msg = str(e)
        if ("access_token_invalid" in msg or "invalid or not found" in msg) and refresh_token:
            client_key = os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("TIKTOK_CLIENT_ID")
            client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
            if not client_key or not client_secret:
                raise Exception(
                    "TikTok access_token invalid and cannot refresh because "
                    "TIKTOK_CLIENT_KEY/TIKTOK_CLIENT_SECRET env is missing"
                )

            refreshed = TikTokAdapter.refresh_access_token(
                client_key=client_key,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )

            new_access = refreshed.get("access_token")
            new_refresh = refreshed.get("refresh_token") or refresh_token
            if not new_access:
                raise Exception(f"TikTok refresh failed: {refreshed}")

            # OPTIONAL: persist updated tokens (recommended)
            try:
                SocialAccount.upsert_destination(
                    business_id=post["business_id"],
                    user__id=post["user__id"],
                    platform="tiktok",
                    destination_id=destination_id,
                    destination_type=dest.get("destination_type") or "user",
                    destination_name=dest.get("destination_name") or destination_id,
                    access_token_plain=new_access,
                    refresh_token_plain=new_refresh,
                    token_expires_at=None,
                    scopes=[],  # keep your stored scopes if you have them
                    platform_user_id=destination_id,
                    platform_username=dest.get("username"),
                    meta=(tokens.get("_acct") or {}).get("meta") or {},
                )
            except Exception:
                pass

            access_token = new_access

            # retry init
            init_resp = TikTokAdapter.init_direct_post_video(
                access_token=access_token,
                post_text=caption,
                video_size_bytes=video_size,
                privacy_level="PUBLIC_TO_EVERYONE",
            )
        else:
            raise

    data = init_resp.get("data") or {}
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id")

    if not upload_url or not publish_id:
        raise Exception(f"TikTok init missing upload_url/publish_id: {init_resp}")

    upload_resp = TikTokAdapter.upload_video_put_single(
        upload_url=upload_url,
        video_bytes=video_bytes,
    )

    status_resp = TikTokAdapter.wait_for_publish(
        access_token=access_token,
        publish_id=publish_id,
        max_wait_seconds=180,
        poll_interval=2.0,
    )

    # provider_post_id: use publish_id (and if status returns an actual video_id, prefer that)
    status_data = (status_resp.get("data") or {})
    provider_id = status_data.get("video_id") or publish_id

    # Determine success/failure from status
    status_val = (status_data.get("status") or "").lower()
    if status_val in ("failed", "error"):
        raise Exception(f"TikTok publish failed: {status_resp}")

    # If TikTok keeps it "processing" but no failure, you can still mark success,
    # but better to treat as success only on published/succeeded.
    if status_val and status_val not in ("published", "success", "succeeded", "processing"):
        # unknown status - still return raw so you can inspect
        pass

    r["status"] = "success"
    r["provider_post_id"] = str(provider_id)
    r["raw"] = {
        "init": init_resp,
        "upload": upload_resp,
        "status": status_resp,
    }
    return r


# -----------------------------
# Main job
# -----------------------------
def _publish_scheduled_post(post_id: str, business_id: str):
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    # Mark as publishing
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

    # Always normalize media to a list
    base_media = _as_list(content.get("media"))

    for dest in (post.get("destinations") or []):
        platform = (dest.get("platform") or "").strip().lower()
        placement = (dest.get("placement") or "feed").lower()

        # ✅ IMPORTANT: work on a fresh copy of media for each destination
        # (prevents one publisher from mutating media for the next)
        media = list(base_media) if base_media else []

        try:
            if platform == "facebook":
                r = _publish_to_facebook(
                    post=post,
                    dest=dest,
                    text=text,
                    link=link,
                    media=media,
                )

            elif platform == "instagram":
                r = _publish_to_instagram(
                    post=post,
                    dest=dest,
                    text=text,
                    link=link,
                    media=media,
                )

            elif platform == "x":
                r = _publish_to_x(
                    post=post,
                    dest=dest,
                    text=text,
                    link=link,
                    media=media,
                )

            elif platform == "tiktok":
                r = _publish_to_tiktok(
                    post=post,
                    dest=dest,
                    text=text,
                    link=link,
                    media=media,
                )

            else:
                r = {
                    "platform": platform,
                    "destination_id": str(dest.get("destination_id") or ""),
                    "destination_type": dest.get("destination_type"),
                    "placement": placement,
                    "status": "failed",
                    "provider_post_id": None,
                    "error": "Unsupported platform (not implemented)",
                    "raw": None,
                }

            # Ensure result is a dict
            if not isinstance(r, dict):
                r = {
                    "platform": platform,
                    "destination_id": str(dest.get("destination_id") or ""),
                    "destination_type": dest.get("destination_type"),
                    "placement": placement,
                    "status": "failed",
                    "provider_post_id": None,
                    "error": f"Publisher returned invalid result type: {type(r)}",
                    "raw": None,
                }

            # Enforce required keys (safe defaults)
            r.setdefault("platform", platform)
            r.setdefault("destination_id", str(dest.get("destination_id") or ""))
            r.setdefault("destination_type", dest.get("destination_type"))
            r.setdefault("placement", placement)
            r.setdefault("status", "failed")
            r.setdefault("provider_post_id", None)
            r.setdefault("error", None)
            r.setdefault("raw", None)

            results.append(r)

            if r.get("status") == "success":
                any_success = True
            else:
                any_failed = True

        except Exception as e:
            rr = {
                "platform": platform,
                "destination_id": str(dest.get("destination_id") or ""),
                "destination_type": dest.get("destination_type"),
                "placement": placement,
                "status": "failed",
                "provider_post_id": None,
                "error": str(e),
                "raw": None,
            }
            results.append(rr)
            any_failed = True
            Log.info(f"{log_tag} destination failed: {rr}")

        # ✅ Persist progress after each destination (very useful if worker crashes)
        try:
            ScheduledPost.update_status(
                post_id,
                post["business_id"],
                ScheduledPost.STATUS_PUBLISHING,
                provider_results=results,
                error=None,
            )
        except Exception:
            pass

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