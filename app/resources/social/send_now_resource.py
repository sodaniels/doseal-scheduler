from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import jsonify, request, g
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate, ValidationError, pre_load, validates_schema, INCLUDE

from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...utils.logger import Log
from ...utils.helpers import make_log_tag

from ...models.social.scheduled_post import ScheduledPost

# ------------------------------------------------------------------
# Publishers
# ------------------------------------------------------------------
from ...services.social.jobs import (
    _as_list,
    _build_caption,
    _publish_to_facebook,
    _publish_to_instagram,
    _publish_to_x,
    _publish_to_tiktok,
    _publish_to_linkedin,
    _publish_to_youtube,
    _publish_to_whatsapp,
    _publish_to_threads,
)

# ------------------------------------------------------------------
# Blueprint
# ------------------------------------------------------------------
blp_send_now = Blueprint("social_send_now", __name__)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _default_placement(dest: dict) -> str:
    return (dest.get("placement") or "feed").lower()


def _count_media_types(media: List[dict]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for m in media:
        t = (m.get("asset_type") or "").lower()
        counts[t] = counts.get(t, 0) + 1
    return counts


# ------------------------------------------------------------------
# PLATFORM RULES
# ------------------------------------------------------------------
PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    "facebook": {
        "placements": {"feed", "reel", "story"},
        "media": {"max_items": 1, "types": {"image", "video"}},
        "requires_destination_type": {"page"},
    },
    "instagram": {
        "placements": {"feed", "reel", "story"},
        "media": {"max_items": 10, "types": {"image", "video"}},
        "requires_destination_type": {"ig_user"},
        "requires_media": True,
    },
    "threads": {
        "placements": {"feed"},
        "media": {"max_items": 1, "types": {"image", "video"}},
        "requires_destination_type": {"user"},
    },
    "x": {
        "placements": {"feed"},
        "media": {"max_items": 4, "types": {"image", "video"}},
        "requires_destination_type": {"user"},
    },
    "tiktok": {
        "placements": {"feed"},
        "media": {"max_items": 1, "types": {"video"}},
        "requires_destination_type": {"user"},
        "requires_media": True,
    },
    "linkedin": {
        "placements": {"feed"},
        "media": {"max_items": 1, "types": {"image", "video"}},
        "requires_destination_type": {"author", "organization"},
    },
    "youtube": {
        "placements": {"feed"},
        "media": {"max_items": 1, "types": {"video"}},
        "requires_destination_type": {"channel"},
        "requires_media": True,
    },
    "whatsapp": {
        "placements": {"direct"},
        "media": {"max_items": 1, "types": {"image", "video", "document"}},
        "requires_destination_type": {"phone_number"},
    },
}


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------
class MediaAssetSchema(Schema):
    class Meta:
        unknown = INCLUDE
        
    asset_type = fields.Str(required=True)
    url = fields.Str(required=True)
    filename = fields.Str(required=False)
    public_id = fields.Str(required=False)

    @validates_schema
    def validate_url(self, data, **kwargs):
        if not _is_url(data["url"]):
            raise ValidationError({"url": ["Invalid URL"]})


class DestinationSchema(Schema):
    platform = fields.Str(required=True)
    destination_type = fields.Str(required=False)
    destination_id = fields.Str(required=True)
    placement = fields.Str(required=False)

    # overrides
    text = fields.Str(required=False)
    link = fields.Str(required=False)
    media = fields.Raw(required=False)

    # WhatsApp
    to = fields.Str(required=False)
    meta = fields.Dict(required=False)

    @pre_load
    def normalize(self, data, **kwargs):
        data["platform"] = (data.get("platform") or "").lower()

        if isinstance(data.get("media"), dict):
            data["media"] = [data["media"]]

        if "placement" not in data:
            data["placement"] = "feed"

        return data


class SendNowContentSchema(Schema):
    class Meta:
        unknown = INCLUDE
    text = fields.Str()
    link = fields.Str()
    media = fields.Raw()

    @pre_load
    def normalize(self, data, **kwargs):
        if isinstance(data.get("media"), dict):
            data["media"] = [data["media"]]
        return data


class SendNowSchema(Schema):
    class Meta:
        unknown = INCLUDE
        
    destinations = fields.List(fields.Nested(DestinationSchema), required=True)

    text = fields.Str()
    link = fields.Str()
    media = fields.Raw()

    content = fields.Nested(SendNowContentSchema)

    @pre_load
    def merge_content(self, data, **kwargs):
        content = data.get("content") or {}

        for k in ("text", "link", "media"):
            if k not in content and data.get(k) is not None:
                content[k] = data[k]

        if isinstance(content.get("media"), dict):
            content["media"] = [content["media"]]

        data["content"] = content
        return data

    @validates_schema
    def validate_all(self, data, **kwargs):
        content = data.get("content") or {}
        text = (content.get("text") or "").strip()
        link = content.get("link")

        media = content.get("media") or []
        if not isinstance(media, list):
            raise ValidationError({"content": {"media": ["must be list"]}})

        parsed_media = []
        for idx, m in enumerate(media):
            parsed_media.append(MediaAssetSchema().load(m))

        if not text and not parsed_media:
            raise ValidationError({"content": ["text or media required"]})

        dest_errors = []

        for idx, dest in enumerate(data["destinations"]):
            platform = dest["platform"]
            placement = _default_placement(dest)

            rule = PLATFORM_RULES.get(platform)
            if not rule:
                dest_errors.append({idx: {"platform": ["unsupported"]}})
                continue

            if placement not in rule["placements"]:
                dest_errors.append({
                    idx: {"placement": [f"Must be one of {sorted(rule['placements'])}"]}
                })

            if rule.get("requires_media") and not parsed_media:
                dest_errors.append({idx: {"media": ["required"]}})

            if platform == "whatsapp":
                to_phone = dest.get("to") or (dest.get("meta") or {}).get("to")
                if not to_phone:
                    dest_errors.append({idx: {"to": ["recipient required"]}})

        if dest_errors:
            raise ValidationError({"destinations": dest_errors})

        data["_normalized_content"] = {
            "text": text,
            "link": link,
            "media": parsed_media,
        }


# ------------------------------------------------------------------
# SEND NOW ENDPOINT
# ------------------------------------------------------------------
@blp_send_now.route("/social/send-now", methods=["POST"])
class SendNowResource(MethodView):

    @token_required
    @blp_send_now.arguments(SendNowSchema)
    def post(self, payload):

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id"))
        user_id = str(user.get("_id"))

        log_tag = make_log_tag(
            "send_now_resource.py",
            "SendNowResource",
            "post",
            request.remote_addr,
            user_id,
            user.get("account_type"),
            business_id,
            business_id,
        )

        content = payload["_normalized_content"]
        text = content.get("text")
        link = content.get("link")
        media = _as_list(content.get("media"))
        destinations = payload["destinations"]

        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()

        # ------------------------------------------------------------------
        # SAVE FIRST
        # ------------------------------------------------------------------
        doc = {
            "business_id": business_id,
            "user__id": user_id,
            "status": ScheduledPost.STATUS_PUBLISHING,
            # ✅ REQUIRED by your ScheduledPost model:
            "scheduled_at_utc": now_iso,   # or use now_dt if your model accepts datetime objects

            # optional (only if your model also stores scheduled_at separately)
            "scheduled_at": now_iso,
            "content": content,
            "destinations": destinations,
            "provider_results": [],
            "error": None,
            "meta": {"send_now": True},
        }

        created = ScheduledPost.create(doc)
        post_id = str(created["_id"])

        post = {
            "_id": post_id,
            "business_id": business_id,
            "user__id": user_id,
            "content": content,
            "destinations": destinations,
        }

        # ------------------------------------------------------------------
        # PUBLISH
        # ------------------------------------------------------------------
        results = []
        any_success = False
        any_failed = False

        for dest in destinations:
            platform = dest["platform"]

            dest_text = dest.get("text") or text
            dest_link = dest.get("link") or link
            dest_media = _as_list(dest.get("media")) or media

            try:
                if platform == "facebook":
                    r = _publish_to_facebook(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "instagram":
                    r = _publish_to_instagram(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "threads":
                    r = _publish_to_threads(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "x":
                    r = _publish_to_x(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "tiktok":
                    r = _publish_to_tiktok(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "linkedin":
                    r = _publish_to_linkedin(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "youtube":
                    r = _publish_to_youtube(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                elif platform == "whatsapp":
                    r = _publish_to_whatsapp(post=post, dest=dest, text=dest_text, link=dest_link, media=dest_media)

                else:
                    raise Exception("Unsupported platform")

            except Exception as e:
                Log.info(f"{log_tag} Error: {str(e)}")
                r = {
                    "platform": platform,
                    "destination_id": dest.get("destination_id"),
                    "status": "failed",
                    "error": str(e),
                    "raw": None,
                }

            results.append(r)

            if r["status"] == "success":
                any_success = True
            else:
                any_failed = True

        final_status = (
            ScheduledPost.STATUS_PUBLISHED
            if any_success and not any_failed
            else ScheduledPost.STATUS_FAILED
        )

        ScheduledPost.update_status(
            post_id,
            business_id,
            final_status,
            provider_results=results,
            error=None if any_success else "All destinations failed",
        )

        return jsonify({
            "success": any_success,
            "post_id": post_id,
            "status": final_status,
            "results": results,
        }), HTTP_STATUS_CODES["OK"]