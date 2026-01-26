from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

from .appctx import run_in_app_context


def _publish_scheduled_post(post_id: str, business_id: str):
    """
    Actual implementation that runs inside Flask app context.
    """
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    try:
        ScheduledPost.update_status(
            post_id,
            post["business_id"],
            ScheduledPost.STATUS_PUBLISHING
        )

        results = []

        content = post.get("content") or {}
        text = content.get("text") or ""
        link = content.get("link")
        media = content.get("media")

        # media might be dict OR list; normalize to "first image" for now
        chosen_media = None
        if isinstance(media, list) and media:
            chosen_media = media[0]
        elif isinstance(media, dict):
            chosen_media = media

        for dest in post.get("destinations") or []:
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

            # -------- Choose publish method (image vs text/link) --------
            if chosen_media and chosen_media.get("asset_type") == "image" and chosen_media.get("url"):
                caption = text or ""
                if link:
                    caption = (caption + "\n\n" + link).strip()

                resp = FacebookAdapter.publish_page_photo(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    image_url=chosen_media["url"],
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

        ScheduledPost.update_status(
            post_id,
            post["business_id"],
            ScheduledPost.STATUS_PUBLISHED,
            provider_results=results,
        )

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
    RQ imports this function; it must not trigger circular imports.
    """
    return run_in_app_context(_publish_scheduled_post, post_id, business_id)