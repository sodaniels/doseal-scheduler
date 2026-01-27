# app/services/social/jobs.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
import time, os

from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...services.social.adapters.instagram_adapter import InstagramAdapter
from ...services.social.adapters.x_adapter import XAdapter
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
    """
    X rules:
      - Only one placement (ignore dest.placement)
      - Text <= 280
      - Media: up to 4 images OR 1 video (your schema enforces this)
    """
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

    consumer_key = os.getenv("X_CLIENT_ID")
    consumer_secret = os.getenv("X_CLIENT_SECRET")
    if not consumer_key or not consumer_secret:
        raise Exception("Missing X_CLIENT_ID / X_CLIENT_SECRET in env")

    tokens = _get_x_oauth_tokens(post, destination_id)
    oauth_token = tokens["oauth_token"]
    oauth_token_secret = tokens["oauth_token_secret"]

    tweet_text = _build_caption(text, link)
    if len(tweet_text) > 280:
        tweet_text = tweet_text[:277] + "..."

    media_ids: List[str] = []
    if media:
        # Upload each media item
        for m in media:
            mtype = (m.get("asset_type") or "").lower()
            url = m.get("url")
            if not url:
                continue

            # choose category
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
            media_ids.append(mid)

    resp = XAdapter.create_tweet(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        oauth_token=oauth_token,
        oauth_token_secret=oauth_token_secret,
        text=tweet_text,
        media_ids=media_ids or None,
    )

    # v2 returns { "data": {"id":"...", "text":"..."} }
    tweet_id = ((resp.get("data") or {}).get("id")) if isinstance(resp, dict) else None

    r["status"] = "success"
    r["provider_post_id"] = tweet_id
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
    media = _as_list(content.get("media"))

    for dest in post.get("destinations") or []:
        platform = (dest.get("platform") or "").strip().lower()

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

            # Ensure shape
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
        first_err = next((x.get("error") for x in results if x.get("status") == "failed" and x.get("error")), None)
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