#app/resources/social/scheduled_posts_resources.py

from datetime import datetime, timezone
import uuid
import os

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from marshmallow import ValidationError
from bson import ObjectId


from ...schemas.social.scheduled_posts_schema import CreateScheduledPostSchema
from ...extensions.queue import scheduler
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log
from ...extensions import db as db_ext
from ...utils.helpers import env_bool
from ...utils.media.cloudinary_client import (
    upload_image_file, upload_video_file
)


blp_scheduled_posts = Blueprint("scheduled_posts", __name__)

# -------------------------------------------
# Config
# -------------------------------------------
FACEBOOK_STORY_MODE = os.getenv("FACEBOOK_STORY_MODE", "reject").lower().strip()
# allowed: "reject" | "manual"


# -------------------------------------------
# Helpers
# -------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_media(media):
    """
    Accept:
      - None
      - dict
      - list[dict]
    Return list[dict] or None
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
    Keeps video-only fields like duration.
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

        # timestamps
        "created_at": m.get("created_at") or _utc_now().isoformat(),
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


def _ensure_content_shape(body: dict) -> dict:
    """
    Ensure schema always receives:
      body["content"] = {"text": ..., "link": ..., "media": [..] or None}

    Accepts:
      - top-level: text/link/media
      - nested: content.text/content.link/content.media

    Also normalizes media into your canonical list-of-dicts form.
    """
    if not isinstance(body, dict):
        return {}

    content = body.get("content")
    if not isinstance(content, dict):
        content = {}

    # merge top-level into content only if missing
    if content.get("text") is None and body.get("text") is not None:
        content["text"] = body.get("text")

    if content.get("link") is None and body.get("link") is not None:
        content["link"] = body.get("link")

    # media can be on top-level or content.media
    media_in = content.get("media")
    if media_in is None and body.get("media") is not None:
        media_in = body.get("media")

    # normalize to canonical list[dict] or None
    content["media"] = _clean_and_normalize_media(media_in)

    body["content"] = content
    return body

def _get_business_suspension(business_id: str) -> dict:
    """
    Checks business_suspensions for an active suspension.

    Returns:
      {
        is_suspended: bool,
        reason: str,
        suspended_at: datetime,
        suspended_by: str,
        scope: str,
        platforms: list | None,
        destinations: list | None
      }
    """

    if not business_id:
        return {"is_suspended": False}

    col = db_ext.get_collection("business_suspensions")

    doc = col.find_one(
        {
            "business_id": ObjectId(str(business_id)),
            "is_active": True,
        },
        sort=[("suspended_at", -1)],
    )

    if not doc:
        return {"is_suspended": False}

    return {
        "is_suspended": True,
        "reason": doc.get("reason"),
        "suspended_at": doc.get("suspended_at"),
        "suspended_by": str(doc.get("suspended_by")) if doc.get("suspended_by") else None,
        "scope": doc.get("scope") or "all",
        "platforms": doc.get("platforms"),
        "destinations": doc.get("destinations"),
    }
    
  
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

        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = uuid.uuid4().hex

        try:
            uploaded = upload_image_file(image, folder=folder, public_id=public_id)
            raw = uploaded.get("raw") or {}

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded.get("public_id"),
                    "public_id": uploaded.get("public_id"),
                    "asset_provider": "cloudinary",
                    "asset_type": "image",
                    "url": uploaded.get("url"),

                    "width": raw.get("width"),
                    "height": raw.get("height"),
                    "format": raw.get("format"),
                    "bytes": raw.get("bytes"),
                    "created_at": _utc_now().isoformat(),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------
# Upload: Video
# -------------------------------------------
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

        # allow octet-stream too (Postman sometimes sends it)
        mt = (video.mimetype or "").lower()
        if not (mt.startswith("video/") or mt == "application/octet-stream"):
            return jsonify({"success": False, "message": "file must be a video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = uuid.uuid4().hex

        try:
            uploaded = upload_video_file(video, folder=folder, public_id=public_id)
            raw = uploaded.get("raw") or {}

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded.get("public_id"),
                    "public_id": uploaded.get("public_id"),
                    "asset_provider": "cloudinary",
                    "asset_type": "video",
                    "url": uploaded.get("url"),

                    # ✅ important for reels flows and platform rules
                    "bytes": raw.get("bytes"),

                    "duration": raw.get("duration"),
                    "format": raw.get("format"),
                    "width": raw.get("width"),
                    "height": raw.get("height"),
                    "created_at": _utc_now().isoformat(),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ---------------------------------------------------------
# Create Scheduled Post API (FB/IG/etc)
# ---------------------------------------------------------
@blp_scheduled_posts.route("/social/scheduled-posts", methods=["POST"])
class CreateScheduledPostResource(MethodView):

    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[scheduled_posts_resource.py][CreateScheduledPostResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}

        # ---------------------------------------------------
        # ✅ AUTH CONTEXT
        # ---------------------------------------------------
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        # ---------------------------------------------------
        # ✅ BUSINESS SUSPENSION (single source of truth)
        # ---------------------------------------------------
        ALLOW_SCHEDULE_WHEN_SUSPENDED = env_bool(
            "ALLOW_SCHEDULE_WHEN_SUSPENDED",
            default=False,
        )

        susp = {"is_suspended": False}
        try:
            susp = _get_business_suspension(business_id) or {"is_suspended": False}
        except Exception as e:
            Log.info(f"{log_tag} suspension lookup failed (ignored): {e}")
            susp = {"is_suspended": False}

        is_suspended = bool(susp.get("is_suspended"))

        if is_suspended and not ALLOW_SCHEDULE_WHEN_SUSPENDED:
            return jsonify({
                "success": False,
                "code": "BUSINESS_SUSPENDED",
                "status_code": HTTP_STATUS_CODES["FORBIDDEN"],
                "message": "This business is currently suspended from scheduling/publishing.",
                "message_to_show": "Your business is currently suspended from scheduling/publishing.",
                "suspension": {
                    "reason": susp.get("reason"),
                    "suspended_at": susp.get("suspended_at"),
                    "until": susp.get("until"),
                }
            }), HTTP_STATUS_CODES["FORBIDDEN"]

        # ---------------------------------------------------
        # ✅ PRE-NORMALIZE BODY BEFORE SCHEMA LOAD
        # ---------------------------------------------------
        body = _ensure_content_shape(body)

        # ---------------------------------------------------
        # ✅ 1) SCHEMA VALIDATION (platform rules live there)
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
        # ✅ 2) USE SCHEMA NORMALIZED OUTPUTS
        # ---------------------------------------------------
        # ✅ This is already a datetime object from the schema!
        scheduled_at_utc = payload["_scheduled_at_utc"]
        
        # ✅ DEBUG: Check scheduled time vs current time
        now_utc = datetime.now(timezone.utc)
        
        # Ensure scheduled_at_utc is timezone-aware
        if scheduled_at_utc.tzinfo is None:
            scheduled_at_utc = scheduled_at_utc.replace(tzinfo=timezone.utc)
        
        diff_seconds = (scheduled_at_utc - now_utc).total_seconds()
        
        Log.info(f"{log_tag} Current time (UTC): {now_utc.isoformat()}")
        Log.info(f"{log_tag} Scheduled time (UTC): {scheduled_at_utc.isoformat()}")
        Log.info(f"{log_tag} Time difference: {diff_seconds:.0f} seconds ({diff_seconds/60:.1f} minutes)")

        # ✅ VALIDATE: Ensure scheduled time is in the future
        MIN_SCHEDULE_DELAY_SECONDS = 60  # At least 1 minute in the future
        
        if diff_seconds < MIN_SCHEDULE_DELAY_SECONDS:
            error_message = {
                "success": False,
                "message": f"Scheduled time must be at least {MIN_SCHEDULE_DELAY_SECONDS} seconds in the future",
                "errors": {
                    "scheduled_at": [
                        f"Time is {abs(diff_seconds):.0f} seconds {'in the past' if diff_seconds < 0 else 'too soon'}. "
                        f"Please schedule at least {MIN_SCHEDULE_DELAY_SECONDS} seconds from now."
                    ]
                },
                "debug": {
                    "now_utc": now_utc.isoformat(),
                    "scheduled_at_utc": scheduled_at_utc.isoformat(),
                    "diff_seconds": diff_seconds,
                }
            }
            Log.info(f"{log_tag} {error_message}")
            return jsonify(error_message), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ---------------------------------------------------
        # ✅ 2) USE SCHEMA NORMALIZED OUTPUTS
        # ---------------------------------------------------
        scheduled_at_utc = payload["_scheduled_at_utc"]
        normalized_content = payload["_normalized_content"]

        normalized_media = normalized_content.get("media")
        if isinstance(normalized_media, dict):
            normalized_media = [normalized_media]
        elif not isinstance(normalized_media, list):
            normalized_media = None
            

        # USE RESOLVED DESTINATIONS (with per-platform text)
        destinations = payload.get("_resolved_destinations") or payload["destinations"]

        manual_required = payload.get("_manual_required") or []

        # ✅ GET PLATFORM-SPECIFIC TEXT AND LINKS
        platform_text = normalized_content.get("platform_text")
        platform_link = normalized_content.get("platform_link")
        
        # ✅ GET WARNINGS FOR RESPONSE (optional)
        link_warnings = payload.get("_link_warnings") or []

        # ---------------------------------------------------
        # ✅ 3) BUILD DB DOCUMENT (canonical form)
        # ---------------------------------------------------
        post_doc = {
            "business_id": business_id,
            "user__id": user__id,

            "platform": "multi",
            "status": ScheduledPost.STATUS_SCHEDULED,

            "scheduled_at_utc": scheduled_at_utc,
            "destinations": destinations,

            # ✅ FIXED: Include platform_text and platform_link
            "content": {
                "text": normalized_content.get("text"),
                "platform_text": platform_text,
                "link": normalized_content.get("link"),
                "platform_link": platform_link,
                "media": normalized_media,
            },

            "provider_results": [],
            "error": None,

            "manual_required": manual_required or None,

            "suspension": {
                "is_suspended": is_suspended,
                "reason": susp.get("reason"),
                "suspended_at": susp.get("suspended_at"),
                "until": susp.get("until"),
            } if is_suspended else None,
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
                "warnings": {"links_ignored": link_warnings} if link_warnings else None,
            }), HTTP_STATUS_CODES["CREATED"]

        # ---------------------------------------------------
        # ✅ 6) SUSPENDED BUT ALLOWED TO SAVE → DO NOT ENQUEUE
        # ---------------------------------------------------
        if is_suspended and ALLOW_SCHEDULE_WHEN_SUSPENDED:
            ScheduledPost.update_status(
                post_id,
                business_id,
                ScheduledPost.STATUS_HELD,
            )
            return jsonify({
                "success": True,
                "message": "scheduled (publishing suspended)",
                "data": created,
                "warnings": {"links_ignored": link_warnings} if link_warnings else None,
            }), HTTP_STATUS_CODES["CREATED"]

        # ---------------------------------------------------
        # ✅ 7) ENQUEUE JOB
        # ---------------------------------------------------
        try:
            from ...services.social.jobs import publish_scheduled_post

            job_id = f"publish-{business_id}-{post_id}"

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

        # ✅ BUILD RESPONSE WITH OPTIONAL WARNINGS
        response = {
            "success": True,
            "message": "scheduled",
            "data": created,
        }
        
        # ✅ Include link warnings if any platforms had their links ignored
        if link_warnings:
            response["warnings"] = {
                "links_ignored": link_warnings
            }

        return jsonify(response), HTTP_STATUS_CODES["CREATED"]






















