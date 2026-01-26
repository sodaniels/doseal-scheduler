from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

from .appctx import run_in_app_context


def _publish_scheduled_post(post_id: str, business_id: str):
    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        return

    log_tag = f"[jobs.py][_publish_scheduled_post][{business_id}][{post_id}]"

    try:
        ScheduledPost.update_status(post_id, post["business_id"], ScheduledPost.STATUS_PUBLISHING)

        results = []

        content = post.get("content") or {}
        text = (content.get("text") or "").strip()
        link = content.get("link")

        media = content.get("media") or []
        if isinstance(media, dict):
            media = [media]
        first_media = media[0] if media else {}

        asset_type = (first_media.get("asset_type") or "").lower()
        media_url = first_media.get("url")

        for dest in post.get("destinations") or []:
            if dest.get("platform") != "facebook":
                continue

            destination_id = str(dest.get("destination_id") or "")
            if not destination_id:
                continue

            placement = (dest.get("placement") or "feed").lower()  # feed|reel|story

            acct = SocialAccount.get_destination(
                post["business_id"],
                post["user__id"],
                "facebook",
                destination_id,
            )
            if not acct or not acct.get("access_token_plain"):
                raise Exception(f"Missing facebook destination token for destination_id={destination_id}")

            page_access_token = acct["access_token_plain"]

            caption = text or ""
            if link:
                caption = (caption + "\n\n" + link).strip()

            # --- placement routing ---
            if placement == "story":
                # Likely unsupported → clear error
                resp = FacebookAdapter.publish_page_story()
                results.append({
                    "platform": "facebook",
                    "destination_id": destination_id,
                    "placement": "story",
                    "provider_post_id": resp.get("id"),
                    "raw": resp,
                })

            elif placement == "reel":
                if asset_type != "video" or not media_url:
                    raise Exception("Facebook reels require a single video media.url")
                resp = FacebookAdapter.publish_page_reel(
                    page_id=destination_id,
                    page_access_token=page_access_token,
                    video_url=media_url,
                    description=caption,
                    share_to_feed=True,
                )
                results.append({
                    "platform": "facebook",
                    "destination_id": destination_id,
                    "placement": "reel",
                    "provider_post_id": resp.get("id") or resp.get("post_id"),
                    "raw": resp,
                })

            else:
                # placement == "feed"
                if asset_type == "image" and media_url:
                    resp = FacebookAdapter.publish_page_photo(
                        page_id=destination_id,
                        page_access_token=page_access_token,
                        image_url=media_url,
                        caption=caption,
                    )
                    results.append({
                        "platform": "facebook",
                        "destination_id": destination_id,
                        "placement": "feed",
                        "provider_post_id": resp.get("post_id") or resp.get("id"),
                        "raw": resp,
                    })

                elif asset_type == "video" and media_url:
                    resp = FacebookAdapter.publish_page_video(
                        page_id=destination_id,
                        page_access_token=page_access_token,
                        video_url=media_url,
                        description=caption,
                    )
                    results.append({
                        "platform": "facebook",
                        "destination_id": destination_id,
                        "placement": "feed",
                        "provider_post_id": resp.get("id"),
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
                        "placement": "feed",
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
    return run_in_app_context(_publish_scheduled_post, post_id, business_id)