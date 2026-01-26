# app/resources/social/scheduled_posts_resource.py

from datetime import datetime, timezone
import uuid
from dateutil import parser as dateparser
from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint

from ...extensions.queue import scheduler
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log
from ...utils.media.cloudinary_client import (
    upload_image_file, upload_video_file
)

blp_scheduled_posts = Blueprint("scheduled_posts", __name__)


def _normalize_media(media):
    if not media:
        return None

    def pick_fields(m: dict) -> dict:
        if not isinstance(m, dict):
            return {}

        asset_id = m.get("asset_id") or m.get("public_id")
        url = m.get("url")
        asset_type = (m.get("asset_type") or "").lower()

        if not asset_id or not url:
            return {}

        if asset_type not in ("image", "video"):
            # default if missing
            asset_type = "image"

        return {
            "asset_id": asset_id,
            "public_id": m.get("public_id") or asset_id,
            "asset_provider": m.get("asset_provider") or "cloudinary",
            "asset_type": asset_type,
            "url": url,
            "width": m.get("width"),
            "height": m.get("height"),
            "format": m.get("format"),
            "bytes": m.get("bytes"),
            "duration": m.get("duration"),  # video
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    if isinstance(media, list):
        cleaned = [pick_fields(x) for x in media]
        cleaned = [x for x in cleaned if x]
        return cleaned if cleaned else None

    if isinstance(media, dict):
        cleaned = pick_fields(media)
        return cleaned if cleaned else None

    return None

@blp_scheduled_posts.route("/social/media/upload-image", methods=["POST"])
class UploadImageResource(MethodView):
    @token_required
    def post(self):
        log_tag = "[scheduled_posts_resource.py][UploadImageResource][post]"
        user = g.get("current_user", {}) or {}

        if "image" not in request.files:
            return jsonify({"success": False, "message": "image file is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        image = request.files["image"]
        if not image or image.filename == "":
            return jsonify({"success": False, "message": "invalid image"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        if not (image.mimetype or "").startswith("image/"):
            return jsonify({"success": False, "message": "file must be an image"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id"))
        user_id = str(user.get("_id"))
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = f"{uuid.uuid4().hex}"

        try:
            uploaded = upload_image_file(image, folder=folder, public_id=public_id)

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    # stable identifier you can store and use later
                    "asset_id": uploaded["public_id"],
                    "public_id": uploaded["public_id"],

                    "asset_provider": "cloudinary",
                    "asset_type": "image",
                    "url": uploaded["url"],

                    # optional metadata (nice for UI + validations)
                    "width": uploaded["raw"].get("width"),
                    "height": uploaded["raw"].get("height"),
                    "format": uploaded["raw"].get("format"),
                    "bytes": uploaded["raw"].get("bytes"),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

@blp_scheduled_posts.route("/social/media/upload-video", methods=["POST"])
class UploadVideoResource(MethodView):
    @token_required
    def post(self):
        log_tag = "[scheduled_posts_resource.py][UploadVideoResource][post]"
        user = g.get("current_user", {}) or {}

        if "video" not in request.files:
            return jsonify({"success": False, "message": "video file is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        video = request.files["video"]
        if not video or video.filename == "":
            return jsonify({"success": False, "message": "invalid video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # basic content-type check (can be video/mp4, video/quicktime, etc.)
        if not (video.mimetype or "").startswith("video/"):
            return jsonify({"success": False, "message": "file must be a video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id"))
        user_id = str(user.get("_id"))
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = f"{uuid.uuid4().hex}"

        try:
            # IMPORTANT: your cloudinary client must support resource_type="video"
            uploaded = upload_video_file(video, folder=folder, public_id=public_id)

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded["public_id"],
                    "public_id": uploaded["public_id"],
                    "asset_provider": "cloudinary",
                    "asset_type": "video",
                    "url": uploaded["url"],

                    # optional metadata
                    "format": uploaded["raw"].get("format"),
                    "bytes": uploaded["raw"].get("bytes"),
                    "duration": uploaded["raw"].get("duration"),
                    "width": uploaded["raw"].get("width"),
                    "height": uploaded["raw"].get("height"),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        
@blp_scheduled_posts.route("/social/scheduled-posts", methods=["POST"])
class CreateScheduledPostResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[scheduled_posts.py][CreateScheduledPostResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}

        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # required fields
        text = body.get("text") or (body.get("content") or {}).get("text")
        link = body.get("link") or (body.get("content") or {}).get("link")

        destinations = body.get("destinations") or []
        page_id = body.get("page_id")
        if page_id and not destinations:
            destinations = [{
                "platform": "facebook",
                "destination_id": str(page_id),
                "destination_type": "page",
            }]

        scheduled_at_raw = body.get("scheduled_at")

        if not text:
            return jsonify({"success": False, "message": "text is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not destinations:
            return jsonify({"success": False, "message": "destinations is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not scheduled_at_raw:
            return jsonify({"success": False, "message": "scheduled_at is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # parse scheduled_at
        try:
            scheduled_at = dateparser.isoparse(scheduled_at_raw)
            if scheduled_at.tzinfo is None:
                return jsonify(
                    {"success": False, "message": "scheduled_at must include timezone (e.g. +00:00)"},
                ), HTTP_STATUS_CODES["BAD_REQUEST"]
            scheduled_at_utc = scheduled_at.astimezone(timezone.utc)
        except Exception:
            return jsonify(
                {"success": False, "message": "scheduled_at must be ISO8601 (e.g. 2026-01-26T12:50:00+00:00)"},
            ), HTTP_STATUS_CODES["BAD_REQUEST"]

        # media in body.media or body.content.media
        media_in = body.get("media")
        if media_in is None:
            media_in = (body.get("content") or {}).get("media")
        normalized_media = _normalize_media(media_in)

        # build doc
        post_doc = {
            "business_id": business_id,
            "user__id": user__id,
            "platform": "multi",
            "status": ScheduledPost.STATUS_SCHEDULED,
            "scheduled_at_utc": scheduled_at_utc,
            "destinations": destinations,
            "content": {
                "text": text,
                "link": link,
                "media": normalized_media,
            },
            "provider_results": [],
            "error": None,
        }

        # 1) create in DB
        try:
            created = ScheduledPost.create(post_doc)
        except Exception as e:
            Log.info(f"{log_tag} Failed to create scheduled post: {e}")
            return jsonify({"success": False, "message": "Failed to schedule post"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        post_id = created.get("_id")
        if not post_id:
            return jsonify({"success": False, "message": "Failed to create scheduled post id"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # 2) enqueue job at scheduled time
        # IMPORTANT: lazy import to avoid circular import
        try:
            from ...services.social.jobs import publish_scheduled_post

            # ✅ safe job id (NO ":" or spaces)
            job_id = f"publish-{business_id}-{post_id}"

            # best-effort: remove any existing job with same id
            try:
                existing = scheduler.get_job(job_id)
                if existing:
                    existing.cancel()
            except Exception:
                pass

            job = scheduler.enqueue_at(
                scheduled_at_utc,
                publish_scheduled_post,
                post_id,
                business_id,
                job_id=job_id,
                meta={"business_id": business_id, "post_id": post_id},
            )

            # ✅ IMPORTANT: do NOT pass result_ttl/failure_ttl to enqueue_at
            # Set them on the job object instead (prevents kwargs reaching your function).
            try:
                job.result_ttl = 500
                job.failure_ttl = 86400
                job.save()
            except Exception:
                pass

        except Exception as e:
            Log.info(f"{log_tag} Failed to enqueue job: {e}")
            ScheduledPost.update_status(
                post_id,
                business_id,
                ScheduledPost.STATUS_FAILED,
                error=f"enqueue failed: {e}",
            )
            return jsonify({"success": False, "message": "Scheduled post created but enqueue failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        return jsonify({
            "success": True,
            "message": "scheduled",
            "data": created
        }), HTTP_STATUS_CODES["CREATED"]