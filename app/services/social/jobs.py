# app/services/social/jobs.py

from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

from .appctx import run_in_app_context


def _publish_scheduled_post(post_id: str, business_id: str):
    """
    Actual implementation that runs inside Flask app context.
    Publishes to all destinations for this scheduled post.

    Facebook behavior:
      - video -> /{page_id}/videos (file_url)
      - image -> /{page_id}/photos (url)
      - otherwise -> /{page_id}/feed
    """
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    try:
        # Mark as publishing
        ScheduledPost.update_status(
            post_id,
            post["business_id"],
            ScheduledPost.STATUS_PUBLISHING
        )

        results = []

        content = post.get("content") or {}
        text = content.get("text") or ""
        link = content.get("link")

        media = content.get("media") or {}

        # If media stored as list, pick first for Facebook
        if isinstance(media, list):
            media = media[0] if media else {}

        asset_type = (media.get("asset_type") or "").lower()
        media_url = media.get("url")

        for dest in (post.get("destinations") or []):
            if dest.get("platform") != "facebook":
                continue

            destination_id = str(dest.get("destination_id") or "")
            if not destination_id:
                continue

            acct = SocialAccount.get_destination(
                post["business_id"],
                post["user__id"],
                "facebook",
                destination_id,
            )
            if not acct or not acct.get("access_token_plain"):
                raise Exception(f"Missing facebook destination token for destination_id={destination_id}")

            page_access_token = acct["access_token_plain"]

            # Build caption/description (include link in caption for image/video)
            caption = (text or "").strip()
            if link:
                caption = (caption + "\n\n" + link).strip()

            # ---------- Choose publish method ----------
            if asset_type == "video" and media_url:
                resp = FacebookAdapter.publish_page_video(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    video_url=media_url,
                    description=caption,
                )

                results.append({
                    "platform": "facebook",
                    "destination_id": destination_id,
                    "provider_post_id": resp.get("id"),
                    "raw": resp,
                })

            elif asset_type == "image" and media_url:
                resp = FacebookAdapter.publish_page_photo(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    image_url=media_url,
                    caption=caption,
                )

                provider_post_id = resp.get("post_id") or resp.get("id")
                results.append({
                    "platform": "facebook",
                    "destination_id": destination_id,
                    "provider_post_id": provider_post_id,
                    "raw": resp,
                })

            else:
                # Text/link feed post
                resp = FacebookAdapter.publish_page_feed(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    message=text,
                    link=link,
                )

                results.append({
                    "platform": "facebook",
                    "destination_id": destination_id,
                    "provider_post_id": resp.get("id"),
                    "raw": resp,
                })

        # Mark published
        ScheduledPost.update_status(
            post_id,
            post["business_id"],
            ScheduledPost.STATUS_PUBLISHED,
            provider_results=results,
        )

        return {"success": True, "results": results}

    except Exception as e:
        Log.info(f"{log_tag} FAILED {e}")
        ScheduledPost.update_status(
            post_id,
            post["business_id"],
            ScheduledPost.STATUS_FAILED,
            error=str(e),
        )
        raise


def publish_scheduled_post(post_id: str, business_id: str):
    """
    Entry point for RQ worker.
    Keep this thin to avoid circular imports.
    """
    return run_in_app_context(_publish_scheduled_post, post_id, business_id)