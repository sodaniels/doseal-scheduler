# app/resources/social/social_posts_resource.py
import time
from flask import request, g, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from ...utils.logger import Log
from ...utils.json_response import prepared_response
# from ...models.social_scheduled_post import SocialScheduledPost
from ...tasks.queue import social_scheduler
from ...tasks.social_publish_jobs import publish_scheduled_post

from ...resources.doseal.admin.admin_business_resource import token_required

blp_social_posts = Blueprint("Social Posts", __name__, description="Schedule Social Posts")

@blp_social_posts.route("/social/posts", methods=["POST"])
class SocialPostsResource(MethodView):
    @token_required
    def post(self):
        user = g.get("current_user", {})
        business_id = str(user.get("business_id"))
        user__id = str(user.get("_id"))
        client_ip = request.remote_addr

        payload = request.get_json() or {}

        # expected:
        # {
        #  "text": "...",
        #  "link": "...",
        #  "media": [{"type":"image","url":"https://..."}],
        #  "platforms":[{"platform":"meta","destination_id":"...","destination_type":"page"}],
        #  "scheduled_for":"2026-01-23T20:30:00Z"
        # }

        scheduled_for = payload.get("scheduled_for")
        platforms = payload.get("platforms", [])

        if not scheduled_for or not platforms:
            return prepared_response(False, "BAD_REQUEST", "scheduled_for and platforms are required.")

        try:
            start = time.time()

            post = SocialScheduledPost(
                business_id=business_id,
                user__id=user__id,
                text=payload.get("text"),
                link=payload.get("link"),
                media=payload.get("media", []),
                platforms=platforms,
                scheduled_for=scheduled_for,
                timezone=payload.get("timezone", "Europe/London"),
                metadata=payload.get("metadata", {}),
            )
            post_id = post.save()

            # enqueue job at scheduled time
            # rq-scheduler expects python datetime; store utc and parse before scheduling
            from datetime import datetime, timezone
            run_at = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00")).astimezone(timezone.utc)

            social_scheduler.enqueue_at(run_at, publish_scheduled_post, post_id)

            Log.info(f"[social_posts][{client_ip}] scheduled post_id={post_id} run_at={run_at.isoformat()}")

            return jsonify({
                "success": True,
                "message": "Post scheduled successfully",
                "data": {"post_id": post_id}
            }), 200

        except Exception as e:
            Log.error(f"[social_posts][{client_ip}] error={str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to schedule post.")