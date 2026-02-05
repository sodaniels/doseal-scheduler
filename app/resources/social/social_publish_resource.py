# app/resources/social/publish_resource.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from marshmallow import Schema, fields, pre_load, validates_schema, ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ...utils.helpers import make_log_tag
from ..doseal.admin.admin_business_resource import token_required

from ...services.social.post_normalizer import normalize_content_for_platform
from ...models.social.social_account import SocialAccount
from ...models.social.scheduled_post import ScheduledPost

# you already import these from your project
from ...utils.social.publish_helpers import (
    _parse_iso8601_with_tz,
    _is_url,
    _as_list,
    _default_placement,
    _count_media_types,
)

from ...schemas.social.scheduled_posts_schema import PLATFORM_RULES

blp_unified_publish = Blueprint("unified_publish", __name__, description="Unified publishing")


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------
class MediaAssetSchema(Schema):
    asset_id = fields.Str(required=False, allow_none=True)
    asset_provider = fields.Str(required=False, allow_none=True)
    asset_type = fields.Str(required=True)  # image|video|document
    url = fields.Str(required=True)
    bytes = fields.Int(required=False, allow_none=True)
    duration = fields.Float(required=False, allow_none=True)
    format = fields.Str(required=False, allow_none=True)
    height = fields.Int(required=False, allow_none=True)
    width = fields.Int(required=False, allow_none=True)
    public_id = fields.Str(required=False, allow_none=True)
    filename = fields.Str(required=False, allow_none=True)


class ScheduledPostContentSchema(Schema):
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)  # allow dict or list; we normalize


class DestinationSchema(Schema):
    platform = fields.Str(required=True)
    destination_type = fields.Str(required=False, allow_none=True)
    destination_id = fields.Str(required=True)
    placement = fields.Str(required=False, allow_none=True)

    # Optional per-destination overrides
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)

    # Optional extra destination metadata (e.g. whatsapp "to")
    meta = fields.Dict(required=False, allow_none=True)


class UnifiedPublishSchema(Schema):
    """
    Single endpoint that supports:
      - publish_to_all: expand connected accounts automatically
      - destinations: explicit selected accounts (subset)
      - content: {text, link, media} OR top-level (text/link/media)
      - scheduled_at: optional (if missing => now)

    Adds internal fields:
      _scheduled_at_utc (datetime)
      _normalized_content (dict)
      _normalized_media (list|None)
    """

    publish_to_all = fields.Bool(required=False, load_default=False)
    scheduled_at = fields.Str(required=False, allow_none=True)

    destinations = fields.List(fields.Nested(DestinationSchema), required=False, allow_none=True)

    # accept either style
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)

    content = fields.Nested(ScheduledPostContentSchema, required=False)

    include_platforms = fields.List(fields.Str(), required=False, allow_none=True)
    exclude_platforms = fields.List(fields.Str(), required=False, allow_none=True)

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

        # normalize media dict -> list
        media_val = content.get("media")
        if isinstance(media_val, dict):
            content["media"] = [media_val]

        in_data["content"] = content
        return in_data

    @validates_schema
    def validate_all(self, data, **kwargs):
        publish_to_all = bool(data.get("publish_to_all", False))
        destinations = data.get("destinations") or []

        if not publish_to_all and not destinations:
            raise ValidationError({"destinations": ["Provide destinations or set publish_to_all=true"]})

        # scheduled_at: if missing => now
        scheduled_at_raw = data.get("scheduled_at")
        if scheduled_at_raw:
            scheduled_at_utc = _parse_iso8601_with_tz(scheduled_at_raw)
        else:
            scheduled_at_utc = datetime.now(timezone.utc)

        content = data.get("content") or {}
        text = (content.get("text") or "").strip()
        link = (content.get("link") or "").strip() or None

        media_list = content.get("media")
        media_list = _as_list(media_list)  # allow None/dict/list

        # parse/validate media items
        parsed_media: List[Dict[str, Any]] = []
        media_errors: Dict[str, Any] = {}
        for idx, m in enumerate(media_list):
            try:
                parsed_media.append(MediaAssetSchema().load(m))
            except ValidationError as ve:
                media_errors[str(idx)] = ve.messages
        if media_errors:
            raise ValidationError({"content": {"media": media_errors}})

        # must contain text or media
        if not text and not parsed_media:
            raise ValidationError({"content": ["Provide at least one of text or media"]})

        if link and not _is_url(link):
            raise ValidationError({"content": {"link": ["Invalid URL"]}})

        # destination validations
        dest_errors: List[Dict[str, Any]] = []

        LINKEDIN_TYPE_ALIASES = {
            "profile": "author",
            "person": "author",
            "member": "author",
            "user": "author",
            "author": "author",
            "page": "organization",
            "company": "organization",
            "org": "organization",
            "organisation": "organization",
            "organization": "organization",
        }

        WHATSAPP_TYPE_ALIASES = {
            "phone": "phone_number",
            "number": "phone_number",
            "phone_number": "phone_number",
        }

        for idx, dest in enumerate(destinations):
            platform = (dest.get("platform") or "").lower().strip()
            placement = _default_placement(dest)

            dest["platform"] = platform
            dest["placement"] = placement

            if platform == "linkedin":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = LINKEDIN_TYPE_ALIASES.get(raw_type, raw_type)

            if platform == "whatsapp":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = WHATSAPP_TYPE_ALIASES.get(raw_type, raw_type)
                else:
                    dest["destination_type"] = "phone_number"

                # normalize placement to "direct" if missing
                if not placement:
                    dest["placement"] = "direct"

            rule = PLATFORM_RULES.get(platform)
            if not rule:
                dest_errors.append({str(idx): {"platform": ["Unsupported platform"]}})
                continue

            allowed_types = rule.get("requires_destination_type") or set()
            if allowed_types and dest.get("destination_type") not in allowed_types:
                dest_errors.append({
                    str(idx): {
                        "destination_type": [
                            f"{platform} requires destination_type in {sorted(allowed_types)}"
                        ]
                    }
                })

            allowed_placements = set(rule.get("placements") or [])
            if allowed_placements and placement not in allowed_placements:
                dest_errors.append({
                    str(idx): {
                        "placement": [
                            f"{platform} placement must be one of {sorted(allowed_placements)}"
                        ]
                    }
                })

            max_text = rule.get("max_text")
            if max_text and text and len(text) > max_text:
                dest_errors.append({
                    str(idx): {"content.text": [f"Too long for {platform}. Max {max_text} chars."]}
                })

            # NOTE: we still validate link here, but the RESOURCE will normalize per-platform,
            # so instagram can still succeed by moving link into text.
            if link and not rule.get("supports_link", True):
                dest_errors.append({
                    str(idx): {"content.link": [f"{platform} does not support clickable links. Put it in text."]}
                })

            requires_media = bool(rule.get("requires_media", False))
            if requires_media and not parsed_media:
                dest_errors.append({
                    str(idx): {"content.media": [f"{platform} requires at least 1 media item."]}
                })

            media_rule = rule.get("media") or {}
            max_items = int(media_rule.get("max_items") or 0)
            allowed_media_types = set(media_rule.get("types") or [])
            video_max_items = int(media_rule.get("video_max_items") or 0)

            if parsed_media:
                if max_items and len(parsed_media) > max_items:
                    dest_errors.append({
                        str(idx): {"content.media": [f"{platform} supports max {max_items} media items."]}
                    })

                counts = _count_media_types(parsed_media)
                if video_max_items and counts.get("video", 0) > video_max_items:
                    dest_errors.append({
                        str(idx): {"content.media": [f"{platform} supports max {video_max_items} video per post."]}
                    })

                for m in parsed_media:
                    at = (m.get("asset_type") or "").lower().strip()
                    if allowed_media_types and at not in allowed_media_types:
                        dest_errors.append({
                            str(idx): {"content.media": [f"{platform} does not allow '{at}' for this post."]}
                        })

            if platform == "whatsapp":
                meta = dest.get("meta") or {}
                to_phone = (meta.get("to") or "").strip()
                if not to_phone:
                    dest_errors.append({
                        str(idx): {"meta.to": ["WhatsApp requires meta.to (recipient phone E.164)"]}
                    })

        if dest_errors:
            raise ValidationError({"destinations": dest_errors})

        data["_scheduled_at_utc"] = scheduled_at_utc
        data["_normalized_content"] = {
            "text": text or None,
            "link": link,
            "media": parsed_media or None,
        }
        data["_normalized_media"] = parsed_media or None


# -------------------------------------------------------------------
# Resource
# -------------------------------------------------------------------
@blp_unified_publish.route("/social/unified/scheduled-posts", methods=["POST"])
class UnifiedPublishResource(MethodView):
    @token_required
    @blp_unified_publish.arguments(UnifiedPublishSchema)
    def post(self, payload):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        log_tag = make_log_tag(
            "publish_resource.py",
            "UnifiedPublishResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            auth_business_id,
        )

        publish_to_all = bool(payload.get("publish_to_all", False))

        # ------------------------------------------------------------
        # 1) Expand destinations if publish_to_all=true
        # ------------------------------------------------------------
        destinations = payload.get("destinations") or []
        if publish_to_all:
            include_platforms = [p.lower().strip() for p in (payload.get("include_platforms") or []) if p]
            exclude_platforms = [p.lower().strip() for p in (payload.get("exclude_platforms") or []) if p]

            connected = SocialAccount.get_all_by_business_id(business_id=auth_business_id) or []

            expanded: List[Dict[str, Any]] = []
            for acct in connected:
                platform = (acct.get("platform") or "").lower().strip()
                if not platform:
                    continue
                if include_platforms and platform not in include_platforms:
                    continue
                if exclude_platforms and platform in exclude_platforms:
                    continue

                expanded.append({
                    "platform": platform,
                    "destination_id": str(acct.get("destination_id") or ""),
                    "destination_type": acct.get("destination_type"),
                    "placement": (acct.get("placement") or "feed"),
                    "meta": (acct.get("meta") or {}),
                })

            if not expanded:
                return jsonify({
                    "success": False,
                    "message": "No connected social accounts found to publish to."
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            destinations = expanded

        # ------------------------------------------------------------
        # 2) Base content from schema normalized output
        # ------------------------------------------------------------
        scheduled_at_utc = payload.get("_scheduled_at_utc") or datetime.now(timezone.utc)
        normalized = payload.get("_normalized_content") or {}

        base_content = {
            "text": normalized.get("text"),
            "link": normalized.get("link"),
            "media": normalized.get("media") or None,
        }

        # ------------------------------------------------------------
        # 3) Build per-destination content + platform normalization
        #    - Instagram: move link into text
        # ------------------------------------------------------------
        final_destinations: List[Dict[str, Any]] = []
        for dest in destinations:
            platform = (dest.get("platform") or "").lower().strip()

            # per-destination overrides (optional)
            dest_content = {
                "text": dest.get("text", base_content.get("text")),
                "link": dest.get("link", base_content.get("link")),
                "media": dest.get("media", base_content.get("media")),
            }

            # normalize quirks PER PLATFORM
            dest_content = normalize_content_for_platform(platform, dest_content)

            cleaned_dest = dict(dest)
            cleaned_dest["platform"] = platform
            cleaned_dest.setdefault("placement", "feed")

            # ✅ store final per-destination content (publisher should prefer this)
            cleaned_dest["content"] = dest_content

            # remove override keys (avoid confusion)
            cleaned_dest.pop("text", None)
            cleaned_dest.pop("link", None)
            cleaned_dest.pop("media", None)

            final_destinations.append(cleaned_dest)

        # ------------------------------------------------------------
        # 4) ALWAYS SAVE IN DB FIRST
        # ------------------------------------------------------------
        doc = {
            "business_id": auth_business_id,
            "user__id": auth_user__id,

            "status": ScheduledPost.STATUS_PENDING,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),

            # required by your model
            "scheduled_at": scheduled_at_utc.isoformat(),
            "scheduled_at_utc": scheduled_at_utc.isoformat(),

            # global content for UI
            "content": base_content,

            # ✅ per destination contains final normalized content
            "destinations": final_destinations,

            "mode": "publish_now" if not payload.get("scheduled_at") else "schedule",
        }

        try:
            created = ScheduledPost.create(doc)
        except Exception as e:
            Log.info(f"{log_tag} Failed to save post: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to save post before publishing",
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # ------------------------------------------------------------
        # 5) Publish now (keep saved even if publish fails)
        # ------------------------------------------------------------
        try:
            from ...services.social.jobs import _publish_scheduled_post
            _publish_scheduled_post(str(created["_id"]), auth_business_id)

            final = ScheduledPost.get_by_id(str(created["_id"]), auth_business_id)
            return jsonify({
                "success": True,
                "message": "Published",
                "data": final,
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} publish failed: {e}")
            try:
                ScheduledPost.update_status(
                    str(created["_id"]),
                    auth_business_id,
                    ScheduledPost.STATUS_FAILED,
                    error=str(e),
                )
            except Exception:
                pass

            return jsonify({
                "success": False,
                "message": "Saved, but publishing failed",
                "data": {"post_id": str(created["_id"])},
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]