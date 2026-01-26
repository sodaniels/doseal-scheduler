from app import create_social_app as create_app
from ...models.social.scheduled_post import ScheduledPost
from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...utils.logger import Log

def publish_scheduled_post(post_id: str):
    app = create_app()
    with app.app_context():

        post = ScheduledPost.get_by_id(post_id)
        if not post:
            return

        log_tag = f"[jobs.py][publish_scheduled_post][{post_id}]"

        try:
            ScheduledPost.update_status(post_id, post["business_id"], ScheduledPost.STATUS_PUBLISHING)

            results = []

            for dest in post["destinations"]:
                if dest["platform"] != "facebook":
                    continue

                acct = SocialAccount.get_destination(
                    post["business_id"],
                    post["user__id"],
                    "facebook",
                    dest["destination_id"],
                )

                resp = FacebookAdapter.publish_page_feed(
                    dest["destination_id"],
                    acct["access_token_plain"],
                    post["content"]["text"],
                    post["content"].get("link"),
                )

                results.append({
                    "platform": "facebook",
                    "destination_id": dest["destination_id"],
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