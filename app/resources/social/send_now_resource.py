# app/routes/social/send_now_resource.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate, ValidationError, pre_load, validates_schema

from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...utils.logger import Log

# Reuse your existing helpers/publishers
from ...services.social.jobs import (
    _as_list,
    _publish_to_facebook,
    _publish_to_instagram,
    _publish_to_x,
    _publish_to_tiktok,
    _publish_to_linkedin,
    _publish_to_youtube,
    _publish_to_whatsapp,
    _publish_to_threads,
)

# ----------------------------------------------------------
# Minimal schemas (compatible with your existing job logic)
# ----------------------------------------------------------

class SendNowDestinationSchema(Schema):
    platform = fields.Str(required=True, validate=validate.Length(min=1))
    destination_type = fields.Str(required=False, allow_none=True)
    destination_id = fields.Str(required=True, validate=validate.Length(min=1))
    placement = fields.Str(required=False, allow_none=True)

    # per-destination overrides
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)

    # WhatsApp recipient (put it in meta to avoid "Unknown field")
    meta = fields.Dict(required=False, allow_none=True)


class SendNowContentSchema(Schema):
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)


class SendNowSchema(Schema):
    """
    POST /social/api/v1/social/send-now
    Mirrors CreateScheduledPostSchema but WITHOUT scheduled_at.
    Accepts either:
      - top-level text/link/media
      - OR content: {text, link, media}
    """
    destinations = fields.List(
        fields.Nested(SendNowDestinationSchema),
        required=True,
        validate=validate.Length(min=1),
    )

    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)

    content = fields.Nested(SendNowContentSchema, required=False)

    @pre_load
    def merge_content(self, in_data, **kwargs):
        if not isinstance(in_data, dict):
            return in_data

        content = in_data.get("content") or {}
        if not isinstance(content, dict):
            content = {}

        if "text" not in content and in_data.get("text") is not None:
            content["text"] = in_data.get("text")

        if "link" not in content and in_data.get("link") is not None:
            content["link"] = in_data.get("link")

        if "media" not in content and in_data.get("media") is not None:
            content["media"] = in_data.get("media")

        # normalize global media dict -> list
        media_val = content.get("media")
        if isinstance(media_val, dict):
            content["media"] = [media_val]

        in_data["content"] = content
        return in_data

    @validates_schema
    def validate_basic(self, data, **kwargs):
        content = data.get("content") or {}
        text = (content.get("text") or "").strip()
        media_list = content.get("media") or []

        if isinstance(media_list, dict):
            media_list = [media_list]

        if media_list and not isinstance(media_list, list):
            raise ValidationError({"content": {"media": ["media must be an object or list"]}})

        if not text and not media_list:
            raise ValidationError({"content": ["Provide at least one of text or media"]})


blp_send_now = Blueprint("social_send_now", __name__, url_prefix="/social/api/v1/social", description="Send Now")


@blp_send_now.route("/social/send-now", methods=["POST"])
class SendNowResource(MethodView):
    @token_required
    @blp_send_now.arguments(SendNowSchema)
    def post(self, payload):
        """
        Publishes immediately to the specified destinations and returns per-destination results.
        """
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        log_tag = f"[send_now_resource.py][SendNowResource][post][{client_ip}][{business_id}][{user__id}]"

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        content = payload.get("content") or {}
        text = (content.get("text") or "").strip()
        link = content.get("link")
        global_media = _as_list(content.get("media"))

        # "post" object shape expected by the token fetchers (SocialAccount.get_destination)
        pseudo_post: Dict[str, Any] = {
            "business_id": business_id,
            "user__id": user__id,
            "_id": "send-now",
            "content": content,
            "destinations": payload.get("destinations") or [],
        }

        results: List[Dict[str, Any]] = []
        any_success = False
        any_failed = False

        for dest in pseudo_post["destinations"]:
            platform = (dest.get("platform") or "").strip().lower()

            dest_text = (dest.get("text") or "").strip() or text
            dest_link = dest.get("link") or link
            dest_media = _as_list(dest.get("media")) or global_media

            try:
                if platform == "facebook":
                    r = _publish_to_facebook(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "instagram":
                    r = _publish_to_instagram(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "threads":
                    # If you paused Threads, keep a safe failure OR call your adapter.
                    # If you have _publish_to_threads implemented, uncomment the call.
                    try:
                        r = _publish_to_threads(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)
                    except NameError:
                        r = {
                            "platform": "threads",
                            "destination_id": str(dest.get("destination_id") or ""),
                            "destination_type": dest.get("destination_type"),
                            "placement": (dest.get("placement") or "feed").lower(),
                            "status": "failed",
                            "provider_post_id": None,
                            "error": "Threads publisher not wired (paused/disabled).",
                            "raw": None,
                        }

                elif platform in ("twitter", "x"):
                    # allow both names from client
                    r = _publish_to_x(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "tiktok":
                    r = _publish_to_tiktok(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "linkedin":
                    r = _publish_to_linkedin(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "youtube":
                    r = _publish_to_youtube(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "whatsapp":
                    # IMPORTANT: recipient must be in dest.meta.to
                    r = _publish_to_whatsapp(post=pseudo_post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                else:
                    r = {
                        "platform": platform,
                        "destination_id": str(dest.get("destination_id") or ""),
                        "destination_type": dest.get("destination_type"),
                        "placement": (dest.get("placement") or "feed").lower(),
                        "status": "failed",
                        "provider_post_id": None,
                        "error": "Unsupported platform (not implemented)",
                        "raw": None,
                    }

                if not isinstance(r, dict):
                    r = {
                        "platform": platform,
                        "destination_id": str(dest.get("destination_id") or ""),
                        "destination_type": dest.get("destination_type"),
                        "placement": (dest.get("placement") or "feed").lower(),
                        "status": "failed",
                        "provider_post_id": None,
                        "error": f"Publisher returned invalid result type: {type(r)}",
                        "raw": None,
                    }

                # Normalize result shape
                r.setdefault("platform", platform)
                r.setdefault("destination_id", str(dest.get("destination_id") or ""))
                r.setdefault("destination_type", dest.get("destination_type"))
                r.setdefault("placement", (dest.get("placement") or "feed").lower())
                r.setdefault("status", "failed")
                r.setdefault("provider_post_id", None)
                r.setdefault("error", None)
                r.setdefault("raw", None)

                results.append(r)

                if r.get("status") == "success":
                    any_success = True
                else:
                    any_failed = True
                    Log.info(f"{log_tag} destination failed: {r}")

            except Exception as e:
                rr = {
                    "platform": platform,
                    "destination_id": str(dest.get("destination_id") or ""),
                    "destination_type": dest.get("destination_type"),
                    "placement": (dest.get("placement") or "feed").lower(),
                    "status": "failed",
                    "provider_post_id": None,
                    "error": str(e),
                    "raw": None,
                }
                results.append(rr)
                any_failed = True
                Log.info(f"{log_tag} destination exception: {rr}")

        # Overall status
        if any_success and not any_failed:
            overall = "success"
        elif any_success and any_failed:
            overall = "partial"
        else:
            overall = "failed"

        return jsonify({"success": overall != "failed", "status": overall, "results": results}), HTTP_STATUS_CODES["OK"]