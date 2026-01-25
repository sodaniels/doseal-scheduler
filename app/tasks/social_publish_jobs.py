# app/tasks/social_publish_jobs.py
from bson.objectid import ObjectId
from ..extensions.db import db
from ..utils.logger import Log
from ..models.social_connected_account import SocialConnectedAccount
from ..models.social_scheduled_post import SocialScheduledPost
from ..models.social_publish_attempt import SocialPublishAttempt
from ..services.social.registry import get_publisher

def publish_scheduled_post(scheduled_post_id: str):
    log_tag = f"[publish_scheduled_post][{scheduled_post_id}]"

    post = db.get_collection(SocialScheduledPost.collection_name).find_one({"_id": ObjectId(scheduled_post_id)})
    if not post:
        Log.error(f"{log_tag} post not found")
        return

    # mark processing
    db.get_collection(SocialScheduledPost.collection_name).update_one(
        {"_id": ObjectId(scheduled_post_id)},
        {"$set": {"status": SocialScheduledPost.STATUS_PROCESSING}}
    )

    success_count = 0
    fail_count = 0

    for target in post.get("platforms", []):
        platform = target.get("platform")
        destination_id = target.get("destination_id")
        destination_type = target.get("destination_type")

        try:
            publisher = get_publisher(platform)

            # fetch connected account for this user/platform
            connected = db.get_collection(SocialConnectedAccount.collection_name).find_one({
                "business_id": post["business_id"],
                "user__id": post["user__id"],
                "platform": platform,
                "status": SocialConnectedAccount.STATUS_ACTIVE
            })

            if not connected:
                raise Exception("No connected account found for platform")

            connected = SocialConnectedAccount.decrypt_token(connected)
            connected = publisher.refresh_token_if_needed(connected)

            access_token = connected.get("access_token")

            destination = {"id": destination_id, "type": destination_type}

            publish_payload = {
                "text": post.get("text"),
                "link": post.get("link"),
                "media": post.get("media", []),
                "metadata": post.get("metadata", {}),
            }

            resp = publisher.publish(access_token, destination, publish_payload)

            attempt = SocialPublishAttempt(
                business_id=str(post["business_id"]),
                user__id=str(post["user__id"]),
                scheduled_post_id=scheduled_post_id,
                platform=platform,
                destination_id=destination_id,
                status=SocialPublishAttempt.STATUS_SUCCESS,
                provider_post_id=resp.get("provider_post_id"),
                request_payload=publish_payload,
                response_payload=resp.get("raw", {}),
            )
            attempt.save(processing_callback=True)
            success_count += 1

        except Exception as e:
            fail_count += 1
            attempt = SocialPublishAttempt(
                business_id=str(post["business_id"]),
                user__id=str(post["user__id"]),
                scheduled_post_id=scheduled_post_id,
                platform=platform,
                destination_id=destination_id,
                status=SocialPublishAttempt.STATUS_FAILED,
                error_message=str(e),
            )
            attempt.save(processing_callback=True)
            Log.error(f"{log_tag} platform={platform} destination={destination_id} error={str(e)}")

    # final status
    if success_count > 0 and fail_count == 0:
        final_status = SocialScheduledPost.STATUS_PUBLISHED
    elif success_count > 0 and fail_count > 0:
        final_status = SocialScheduledPost.STATUS_PARTIAL
    else:
        final_status = SocialScheduledPost.STATUS_FAILED

    db.get_collection(SocialScheduledPost.collection_name).update_one(
        {"_id": ObjectId(scheduled_post_id)},
        {"$set": {"status": final_status}}
    )

    Log.info(f"{log_tag} done success={success_count} failed={fail_count} status={final_status}")