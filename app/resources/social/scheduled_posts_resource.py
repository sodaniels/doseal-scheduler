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
from ...utils.media.cloudinary_client import upload_image_file



blp_scheduled_posts = Blueprint("scheduled_posts", __name__)

def _parse_iso_to_utc(iso_str: str) -> datetime:
    # expects "2026-01-26T20:30:00Z" or "2026-01-26T20:30:00+00:00"
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc)

def _normalize_image_media(media):
    """
    Accepts:
      - None
      - dict (single image)
      - list[dict] (multiple images)

    Returns:
      - None
      - dict (single)
      - list[dict] (multiple)
    """
    if not media:
        return None

    def pick_fields(m: dict) -> dict:
        if not isinstance(m, dict):
            return {}

        # Accept either asset_id or public_id; treat them as the same stable identifier
        asset_id = m.get("asset_id") or m.get("public_id")
        url = m.get("url")
        if not asset_id or not url:
            # Not valid enough to store
            return {}

        return {
            "asset_id": asset_id,
            "public_id": m.get("public_id") or asset_id,
            "asset_provider": m.get("asset_provider") or "cloudinary",
            "asset_type": m.get("asset_type") or "image",
            "url": url,

            # metadata (optional but very useful)
            "width": m.get("width"),
            "height": m.get("height"),
            "format": m.get("format"),
            "bytes": m.get("bytes"),

            # timestamps
            "created_at": datetime.utcnow().isoformat(),
        }

    # list case
    if isinstance(media, list):
        cleaned = [pick_fields(x) for x in media]
        cleaned = [x for x in cleaned if x]  # remove invalid
        return cleaned if cleaned else None

    # dict case
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

        # Optional: basic content-type check
        if not (image.mimetype or "").startswith("image/"):
            return jsonify({"success": False, "message": "file must be an image"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id"))
        user_id = str(user.get("_id"))

        # Cloudinary folder structure
        folder = f"social/{business_id}/{user_id}"

        # Keep deterministic-ish public id
        public_id = f"{uuid.uuid4().hex}"

        try:
            uploaded = upload_image_file(image, folder=folder, public_id=public_id)
            
            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded["public_id"],
                    "asset_provider": "cloudinary",
                    "asset_type": "image",

                    "url": uploaded["url"],
                    "public_id": uploaded["public_id"],

                    "width": uploaded["raw"].get("width"),
                    "height": uploaded["raw"].get("height"),
                    "format": uploaded["raw"].get("format"),
                    "bytes": uploaded["raw"].get("bytes"),
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

        # --- owner context from token_required ---
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # --- required fields ---
        text = body.get("text") or (body.get("content") or {}).get("text")
        link = body.get("link") or (body.get("content") or {}).get("link")

        destinations = body.get("destinations") or []
        # You may also support legacy single page_id:
        page_id = body.get("page_id")
        if page_id and not destinations:
            # Legacy: convert to destinations
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

        # Parse scheduled_at
        try:
            scheduled_at = dateparser.isoparse(scheduled_at_raw)
        except Exception:
            return jsonify({"success": False, "message": "scheduled_at must be ISO8601 (e.g. 2026-01-26T12:50:00+00:00)"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # --- media (image objects) ---
        # Support either:
        #   body.media  OR body.content.media
        media_in = body.get("media")
        if media_in is None:
            media_in = (body.get("content") or {}).get("media")

        normalized_media = _normalize_image_media(media_in)

        # --- build post doc ---
        post_doc = {
            "business_id": business_id,
            "user__id": user__id,

            "platform": "multi",
            "status": ScheduledPost.STATUS_SCHEDULED,

            "scheduled_at_utc": scheduled_at,

            "destinations": destinations,

            "content": {
                "text": text,
                "link": link,
                "media": normalized_media,
            },

            "provider_results": [],
            "error": None,
        }

        try:
            created = ScheduledPost.create(post_doc)  # you implement in your model
            # created should return inserted id or full doc
        except Exception as e:
            Log.info(f"{log_tag} Failed to create scheduled post: {e}")
            return jsonify({"success": False, "message": "Failed to schedule post"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        return jsonify({
            "success": True,
            "message": "scheduled",
            "data": created
        }), HTTP_STATUS_CODES["CREATED"]