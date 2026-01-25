from ...models.social.scheduled_post import ScheduledPost
from ...services.social.publish_service import SocialPublishService

def publish_scheduled_post(post_id: str, business_id: str):
    """
    RQ job: publish one scheduled post to all selected platforms.
    """
    post_doc = ScheduledPost.get_by_id(post_id, business_id)
    if not post_doc:
        return {"ok": False, "error": "Scheduled post not found"}

    user__id = post_doc["user__id"]
    platforms = post_doc.get("platforms") or []

    ScheduledPost.set_status(post_id, business_id, ScheduledPost.STATUS_PROCESSING)

    results = {}
    try:
        payload = {
            "caption": post_doc.get("caption"),
            "link": post_doc.get("link"),
            "media": post_doc.get("media"),
            "extra": post_doc.get("extra"),
        }

        for platform in platforms:
            try:
                r = SocialPublishService.publish_one(business_id, user__id, platform, payload)
                results[platform] = {"success": True, **r}
            except Exception as e:
                results[platform] = {"success": False, "error": str(e)}

        all_ok = all(v.get("success") for v in results.values()) if results else False
        final_status = ScheduledPost.STATUS_POSTED if all_ok else ScheduledPost.STATUS_FAILED

        ScheduledPost.set_status(post_id, business_id, final_status, results=results, error=None if all_ok else "One or more platforms failed")
        return {"ok": True, "results": results}

    except Exception as e:
        ScheduledPost.set_status(post_id, business_id, ScheduledPost.STATUS_FAILED, results=results, error=str(e))
        return {"ok": False, "error": str(e), "results": results}