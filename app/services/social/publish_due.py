from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

def publish_due_posts(batch_limit=20):
    log_tag = "[publish_due_posts]"

    due = ScheduledPost.get_due_posts(limit=batch_limit)
    Log.info(f"{log_tag} due_count={len(due)}")

    for post in due:
        post_id = str(post["_id"])
        business_id = str(post["business_id"])
        user__id = str(post["user__id"])

        try:
            # mark publishing
            ScheduledPost.update_status(post_id, business_id, ScheduledPost.STATUS_PUBLISHING)

            content = post.get("content") or {}
            text = content.get("text") or ""
            link = content.get("link")

            results = []
            for dest in post.get("destinations", []):
                if dest.get("platform") != "facebook":
                    continue

                page_id = dest.get("destination_id")
                acct = SocialAccount.get_destination(
                    business_id=business_id,
                    user__id=user__id,
                    platform="facebook",
                    destination_id=str(page_id),
                )
                if not acct:
                    raise Exception(f"No connected Facebook destination for page_id={page_id}")

                page_token = acct.get("access_token_plain")
                if not page_token:
                    raise Exception("Facebook page access token missing")

                resp = FacebookAdapter.publish_page_feed(
                    page_id=str(page_id),
                    page_access_token=page_token,
                    message=text,
                    link=link,
                )

                results.append({
                    "platform": "facebook",
                    "destination_id": str(page_id),
                    "provider_post_id": resp.get("id"),
                    "raw": resp,
                })

            ScheduledPost.update_status(
                post_id,
                business_id,
                ScheduledPost.STATUS_PUBLISHED,
                provider_results=results,
                error=None
            )

        except Exception as e:
            Log.info(f"{log_tag} publish failed post_id={post_id} err={e}")
            ScheduledPost.update_status(
                post_id,
                business_id,
                ScheduledPost.STATUS_FAILED,
                error=str(e)
            )