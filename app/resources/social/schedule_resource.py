from flask_smorest import Blueprint
from flask.views import MethodView
from flask import request, g
from datetime import datetime, timezone

from ...models.social.scheduled_post import ScheduledPost
from ...extensions.queue import scheduler
from ...tasks.social.publish_job import publish_scheduled_post
from ...schemas.social.social_schema import SchedulePostSchema, PaginationSchema

from ...resources.doseal.admin.admin_business_resource import token_required

blp_social = Blueprint("Social Scheduler", "social", url_prefix="/social", description="Social scheduling endpoints")

@blp_social.route("/schedule")
class ScheduleResource(MethodView):

    @token_required
    @blp_social.arguments(SchedulePostSchema)
    def post(self, payload):
        """
        Schedule a post for multiple platforms.
        """
        user = g.current_user
        business_id = str(user["business_id"])
        user__id = str(user["_id"])

        scheduled_for = payload["scheduled_for"]
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        if scheduled_for <= now:
            return {"success": False, "message": "scheduled_for must be in the future (UTC)."}, 400

        sp = ScheduledPost(
            business_id=business_id,
            user__id=user__id,
            caption=payload["caption"],
            platforms=payload["platforms"],
            scheduled_for=scheduled_for,
            link=payload.get("link"),
            media=payload.get("media") or {"type": "none"},
            extra=payload.get("extra") or {},
        )
        post_id = sp.save()

        # Schedule RQ job at the datetime
        scheduler.enqueue_at(
            scheduled_for,
            publish_scheduled_post,
            post_id,
            business_id
        )

        return {"success": True, "post_id": post_id, "scheduled_for": scheduled_for.isoformat()}, 201


@blp_social.route("/posts")
class ListScheduledPostsResource(MethodView):

    @token_required
    @blp_social.arguments(PaginationSchema, location="query")
    def get(self, args):
        user = g.current_user
        business_id = str(user["business_id"])

        page = args.get("page")
        per_page = args.get("per_page")

        res = ScheduledPost.paginate(
            query={"business_id": ScheduledPost(business_id=business_id, user__id=user["_id"], caption="", platforms=[], scheduled_for=datetime.utcnow()).business_id},
            page=page,
            per_page=per_page,
            sort_by="created_at",
            sort_order=-1,
        )
        return {"success": True, "data": res}, 200