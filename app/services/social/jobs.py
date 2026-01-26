# app/services/social/jobs.py

from __future__ import annotations

from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

from .appctx import run_in_app_context


def _as_list(x):
    if not x:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        return [x]
    return []

def _first_media(content: dict) -> dict:
    """
    ScheduledPost.content.media may be:
      - dict
      - list[dict]
      - None
    We use the first item for Facebook.
    """
    media = _as_list((content or {}).get("media"))
    return media[0] if media else {}


def _build_caption(text: str, link: str | None) -> str:
    caption = (text or "").strip()
    if link:
        if caption:
            caption = f"{caption}\n\n{link}"
        else:
            caption = link
    return caption.strip()


def _publish_scheduled_post(post_id: str, business_id: str):
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    # Mark as publishing at the start
    ScheduledPost.update_status(post_id, post["business_id"], ScheduledPost.STATUS_PUBLISHING)

    results = []
    any_success = False
    any_failed = False

    content = post.get("content") or {}
    text = (content.get("text") or "").strip()
    link = content.get("link")

    media = content.get("media") or []
    if isinstance(media, dict):
        media = [media]
    first_media = media[0] if media else {}

    asset_type = (first_media.get("asset_type") or "").lower()
    media_url = first_media.get("url")
    media_bytes = first_media.get("bytes")

    for dest in post.get("destinations") or []:
        # Default per-destination result skeleton
        r = {
            "platform": dest.get("platform"),
            "destination_id": str(dest.get("destination_id") or ""),
            "destination_type": dest.get("destination_type"),
            "placement": (dest.get("placement") or "feed").lower(),
            "status": "failed",
            "provider_post_id": None,
            "error": None,
            "raw": None,
        }

        try:
            if r["platform"] != "facebook":
                r["error"] = "Unsupported platform (not implemented)"
                results.append(r)
                any_failed = True
                continue

            destination_id = r["destination_id"]
            if not destination_id:
                r["error"] = "Missing destination_id"
                results.append(r)
                any_failed = True
                continue

            acct = SocialAccount.get_destination(
                post["business_id"],
                post["user__id"],
                "facebook",
                destination_id,
            )
            if not acct or not acct.get("access_token_plain"):
                raise Exception(f"Missing facebook page token for destination_id={destination_id}")

            page_access_token = acct["access_token_plain"]

            caption = text or ""
            if link:
                caption = (caption + "\n\n" + link).strip()

            placement = r["placement"]

            # -------------------------
            # Placement routing
            # -------------------------
            if placement == "story":
                # If you don't support stories, mark as manual-required style failure
                # (or implement it later)
                raise Exception("Facebook story publishing not supported by this integration (manual required).")

            elif placement == "reel":
                # Reels require a single video, plus file size bytes for resumable upload
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
                    share_to_feed=False,  # IMPORTANT: we handle feed separately if user selected feed too
                )

                r["status"] = "success"
                r["provider_post_id"] = resp.get("id") or resp.get("post_id")
                r["raw"] = resp
                results.append(r)
                any_success = True
                continue

            else:
                # placement == "feed"
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
                    results.append(r)
                    any_success = True
                    continue

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
                    results.append(r)
                    any_success = True
                    continue

                # text/link only
                resp = FacebookAdapter.publish_page_feed(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    message=text,
                    link=link,
                )
                r["status"] = "success"
                r["provider_post_id"] = resp.get("id")
                r["raw"] = resp
                results.append(r)
                any_success = True
                continue

        except Exception as e:
            r["error"] = str(e)
            results.append(r)
            any_failed = True
            Log.info(f"{log_tag} destination failed: {r}")
            # DO NOT raise — keep processing other destinations
            continue

    # -------------------------
    # Decide overall status
    # -------------------------
    # all success
    if any_success and not any_failed:
        overall_status = ScheduledPost.STATUS_PUBLISHED
        overall_error = None

    # some success, some failure
    elif any_success and any_failed:
        # Add this status in ScheduledPost model
        overall_status = getattr(ScheduledPost, "STATUS_PARTIAL", ScheduledPost.STATUS_PUBLISHED)
        # keep an overall error message (optional)
        first_err = next((x.get("error") for x in results if x.get("status") == "failed"), None)
        overall_error = f"Some destinations failed. Example: {first_err}" if first_err else "Some destinations failed."

    # all failed
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
    """
    Entry point used by RQ worker.
    Keep imports light here to avoid circular imports.
    """
    return run_in_app_context(_publish_scheduled_post, post_id, business_id)