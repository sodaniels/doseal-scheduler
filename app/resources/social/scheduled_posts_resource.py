from datetime import datetime, timezone
import uuid
import os

from dateutil import parser as dateparser
from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint

from ...schemas.social.scheduled_post_schema import CreateScheduledPostSchema
from marshmallow import ValidationError
from ...extensions.queue import scheduler
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log
from ...utils.media.cloudinary_client import upload_image_file, upload_video_file  # ✅ include video


blp_scheduled_posts = Blueprint("scheduled_posts", __name__)

# -------------------------------------------
# Config
# -------------------------------------------
FACEBOOK_STORY_MODE = os.getenv("FACEBOOK_STORY_MODE", "reject").lower().strip()
# allowed: "reject" | "manual"


# -------------------------------------------
# Helpers
# -------------------------------------------
def _normalize_media(media):
    """
    Accept:
      - None
      - dict
      - list[dict]
    Return normalized list[dict] or None
    """
    if not media:
        return None
    if isinstance(media, dict):
        return [media]
    if isinstance(media, list):
        return media
    return None


def _normalize_media_item(m: dict) -> dict:
    """
    Normalize a single media item from Cloudinary-style response.
    Supports BOTH image and video.
    Allows video-only fields like duration.
    """
    if not isinstance(m, dict):
        return {}

    asset_id = m.get("asset_id") or m.get("public_id")
    url = m.get("url")

    if not asset_id or not url:
        return {}

    asset_type = (m.get("asset_type") or "").lower().strip()
    if asset_type not in ("image", "video"):
        return {}

    out = {
        "asset_id": asset_id,
        "public_id": m.get("public_id") or asset_id,
        "asset_provider": m.get("asset_provider") or "cloudinary",
        "asset_type": asset_type,
        "url": url,

        # common metadata
        "width": m.get("width"),
        "height": m.get("height"),
        "format": m.get("format"),
        "bytes": m.get("bytes"),

        # video-only metadata (allowed)
        "duration": m.get("duration"),

        "created_at": m.get("created_at") or datetime.now(timezone.utc).isoformat(),
    }
    return out


def _clean_and_normalize_media(media_in):
    """
    Returns list[dict] or None
    """
    items = _normalize_media(media_in)
    if not items:
        return None

    cleaned = []
    for m in items:
        nm = _normalize_media_item(m)
        if nm:
            cleaned.append(nm)

    return cleaned if cleaned else None


def _parse_scheduled_at(scheduled_at_raw: str) -> datetime:
    scheduled_at = dateparser.isoparse(scheduled_at_raw)
    if scheduled_at.tzinfo is None:
        raise ValueError("scheduled_at must include timezone (e.g. 2026-01-26T12:50:00+00:00)")
    return scheduled_at.astimezone(timezone.utc)


def _default_placement(dest: dict) -> str:
    p = (dest.get("placement") or "").strip().lower()
    return p or "feed"


def _validate_facebook_destination(dest: dict, content: dict, errors: list):
    """
    Facebook validation rules (scheduler behaviour):
      - feed: supports text/link OR 1 image OR 1 video
      - reel: requires exactly 1 video
      - story: reject OR allow as manual_required depending on FACEBOOK_STORY_MODE
    """
    placement = _default_placement(dest)
    media = content.get("media") or []
    text = (content.get("text") or "").strip()

    # enforce single media for facebook in this implementation
    if len(media) > 1:
        errors.append({
            "platform": "facebook",
            "destination_id": dest.get("destination_id"),
            "placement": placement,
            "message": "Facebook supports only 1 media item per scheduled post in this implementation."
        })
        return

    if placement == "reel":
        if len(media) != 1:
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "reel",
                "message": "Facebook reels require exactly 1 media item (video)."
            })
            return
        if (media[0].get("asset_type") or "").lower() != "video":
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "reel",
                "message": "Facebook reels require media.asset_type=video."
            })
            return
        if not media[0].get("url"):
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "reel",
                "message": "Facebook reels require media.url."
            })
            return

    if placement == "story":
        if FACEBOOK_STORY_MODE == "reject":
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "story",
                "message": "Facebook Page Stories scheduling not supported. Use placement=feed or placement=reel."
            })
            return

        # manual mode: still requires exactly one media
        if len(media) != 1:
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "story",
                "message": "Facebook story requires exactly 1 media item."
            })
            return
        if not media[0].get("url"):
            errors.append({
                "platform": "facebook",
                "destination_id": dest.get("destination_id"),
                "placement": "story",
                "message": "Facebook story requires media.url."
            })
            return

    # conservative text limit
    if text and len(text) > 5000:
        errors.append({
            "platform": "facebook",
            "destination_id": dest.get("destination_id"),
            "placement": placement,
            "message": "Facebook post text too long (max 5000 chars)."
        })


def _validate_destinations(destinations: list, content: dict):
    errors = []
    for dest in destinations:
        platform = (dest.get("platform") or "").lower().strip()
        dest["placement"] = _default_placement(dest)  # ensure stored

        if platform == "facebook":
            _validate_facebook_destination(dest, content, errors)

        # add more platforms later (instagram carousel, youtube video-only, etc.)

    return errors


# -------------------------------------------
# Upload: Image
# -------------------------------------------
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
        folder = f"social/{business_id}/{user_id}"
        public_id = uuid.uuid4().hex

        try:
            uploaded = upload_image_file(image, folder=folder, public_id=public_id)

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded["public_id"],
                    "public_id": uploaded["public_id"],
                    "asset_provider": "cloudinary",
                    "asset_type": "image",
                    "url": uploaded["url"],

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

        # IMPORTANT: field name is "video"
        if "video" not in request.files:
            return jsonify({"success": False, "message": "video file is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        video = request.files["video"]
        if not video or video.filename == "":
            return jsonify({"success": False, "message": "invalid video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Basic content-type check
        if not (video.mimetype or "").startswith("video/"):
            return jsonify({"success": False, "message": "file must be a video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id"))
        user_id = str(user.get("_id"))

        folder = f"social/{business_id}/{user_id}"
        public_id = f"{uuid.uuid4().hex}"

        try:
            # lazy import to avoid circulars if any
            from ...utils.media.cloudinary_client import upload_video_file

            uploaded = upload_video_file(video, folder=folder, public_id=public_id)
            raw = uploaded.get("raw") or {}

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    # keep consistent with image
                    "asset_id": uploaded["public_id"],
                    "public_id": uploaded["public_id"],
                    "asset_provider": "cloudinary",
                    "asset_type": "video",

                    "url": uploaded["url"],

                    # REQUIRED for reels flow
                    "bytes": raw.get("bytes"),

                    # video metadata (Cloudinary usually returns these)
                    "duration": raw.get("duration"),
                    "format": raw.get("format"),
                    "width": raw.get("width"),
                    "height": raw.get("height"),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        
# ---------------------------------------------------------
# Create Scheduled Post API
# ---------------------------------------------------------
@blp_scheduled_posts.route("/social/scheduled-posts", methods=["POST"])
class CreateScheduledPostResource(MethodView):

    @token_required
    def post(self):

        client_ip = request.remote_addr
        log_tag = f"[scheduled_posts.py][CreateScheduledPostResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}

        # ---------------------------------------------------
        # ✅ AUTH CONTEXT
        # ---------------------------------------------------

        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ---------------------------------------------------
        # ✅ 1) SCHEMA VALIDATION
        # ---------------------------------------------------

        try:
            payload = CreateScheduledPostSchema().load(body)
        except ValidationError as err:
            return jsonify({
                "success": False,
                "message": "Validation failed",
                "errors": err.messages,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ---------------------------------------------------
        # ✅ 2) NORMALIZED OUTPUT FROM SCHEMA
        # ---------------------------------------------------

        scheduled_at_utc = payload["_scheduled_at_utc"]

        content = payload["_normalized_content"]

        destinations = payload["destinations"]

        manual_required = payload.get("_manual_required") or []

        # ---------------------------------------------------
        # ✅ 3) BUILD DB DOCUMENT
        # ---------------------------------------------------

        post_doc = {
            "business_id": business_id,
            "user__id": user__id,

            "platform": "multi",

            "status": ScheduledPost.STATUS_SCHEDULED,

            "scheduled_at_utc": scheduled_at_utc,

            "destinations": destinations,

            "content": content,

            "provider_results": [],
            "error": None,

            # used when platform/placement requires human publishing
            "manual_required": manual_required or None,
        }

        # ---------------------------------------------------
        # ✅ 4) INSERT INTO DB
        # ---------------------------------------------------

        try:
            created = ScheduledPost.create(post_doc)

        except Exception as e:
            Log.info(f"{log_tag} Failed to create scheduled post: {e}")

            return jsonify({
                "success": False,
                "message": "Failed to schedule post",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        post_id = created.get("_id")

        if not post_id:
            return jsonify({
                "success": False,
                "message": "Failed to create scheduled post id",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # ---------------------------------------------------
        # ✅ 5) MANUAL REQUIRED → DO NOT ENQUEUE
        # ---------------------------------------------------

        if manual_required:

            return jsonify({
                "success": True,
                "message": "scheduled (manual_required)",
                "data": created,
            }), HTTP_STATUS_CODES["CREATED"]

        # ---------------------------------------------------
        # ✅ 6) ENQUEUE JOB
        # ---------------------------------------------------

        try:

            # lazy import prevents circular refs
            from ...services.social.jobs import publish_scheduled_post

            job_id = f"publish-{business_id}-{post_id}"

            # cancel old job if exists
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
                meta={
                    "business_id": business_id,
                    "post_id": post_id,
                },
            )

            # TTL configuration
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

            return jsonify({
                "success": False,
                "message": "Scheduled post created but enqueue failed",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # ---------------------------------------------------
        # ✅ SUCCESS
        # ---------------------------------------------------

        return jsonify({
            "success": True,
            "message": "scheduled",
            "data": created,
        }), HTTP_STATUS_CODES["CREATED"]