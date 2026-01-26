from datetime import datetime, timezone
from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint

from ...extensions.queue import scheduler
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log

blp_scheduled_posts = Blueprint("scheduled_posts", __name__)

def _parse_iso_to_utc(iso_str: str) -> datetime:
    # expects "2026-01-26T20:30:00Z" or "2026-01-26T20:30:00+00:00"
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)

@blp_scheduled_posts.route("/social/scheduled-posts", methods=["POST"])
class CreateScheduledPostResource(MethodView):
    @token_required
    def post(self):
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id"))
        user__id = str(user.get("_id"))

        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip()
        link = (body.get("link") or "").strip() or None
        scheduled_at = body.get("scheduled_at")  # ISO string
        page_id = body.get("page_id")           # destination_id

        if not text:
            return jsonify({"success": False, "message": "text is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not scheduled_at:
            return jsonify({"success": False, "message": "scheduled_at is required (ISO string)"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not page_id:
            return jsonify({"success": False, "message": "page_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            scheduled_at_utc = _parse_iso_to_utc(scheduled_at)
        except Exception:
            return jsonify({"success": False, "message": "scheduled_at must be ISO format"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        post = ScheduledPost(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            content={"text": text, "link": link},
            scheduled_at_utc=scheduled_at_utc,
            destinations=[{
                "platform": "facebook",
                "destination_type": "page",
                "destination_id": str(page_id),
            }],
            status=ScheduledPost.STATUS_SCHEDULED,
        )

        post_id = post.save()
        
        if post_id:
            Log.info(f"[CreateScheduledPostResource] Scheduled post_id={post_id} for business_id={business_id} at {scheduled_at_utc.isoformat()} UTC")
            job = scheduler.enqueue_at(
                scheduled_at_utc,
                "app.services.social.jobs.publish_scheduled_post",
                post_id,
                business_id
            )
            Log.info(f"[schedule] queued job_id={job.id} at {scheduled_at_utc}")
            
            return jsonify({
                "success": True,
                "message": "Post scheduled",
                "data": {"post_id": post_id}
            }), HTTP_STATUS_CODES["OK"]
        else:
            return jsonify({
                "success": False,
                "message": "Failed to schedule post"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]