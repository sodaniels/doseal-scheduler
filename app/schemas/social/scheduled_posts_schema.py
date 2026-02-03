from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from dateutil import parser as dateparser

from marshmallow import (
    Schema,
    fields,
    validates_schema,
    ValidationError,
    validate,
    pre_load,
    INCLUDE,
)

# ---------------------------------------------------------------------
# Platform rules (easy to extend / tweak later)
# ---------------------------------------------------------------------
PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    # Facebook Pages: simple publishing flow (feed OR photo OR video) => 1 primary media max.
    "facebook": {
        "max_text": 5000,
        "supports_link": True,
        "media": {
            "max_items": 1,
            "types": {"image", "video"},
            "video_max_items": 1,
        },
        "requires_destination_type": {"page"},
        "requires_media": False,
        "placements": {"feed", "reel"},  # you can add "story" later if you support it
    },

    # Instagram: carousel up to 10
    # NOTE: In practice:
    # - feed: image(s) or video(s) (carousel up to 10)
    # - reel: single video
    # - story: single image or video (if you support it)
    "instagram": {
        "max_text": 2200,
        "supports_link": False,  # no clickable links in caption
        "media": {"max_items": 10, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"ig_user"},
        "requires_media": True,
        "placements": {"feed", "reel", "story"},
    },

    # X/Twitter: conservative limits
    "x": {
        "max_text": 280,
        "supports_link": True,
        "media": {"max_items": 4, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"user"},
        "requires_media": False,
        "placements": {"feed"},
    },

    # LinkedIn: common organic post limits
    "linkedin": {
        "max_text": 3000,
        "supports_link": True,
        "media": {"max_items": 1, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"author", "organization"},
        "requires_media": False,
        "placements": {"feed"},
    },

    # YouTube: video-first (upload/publish video)
    "youtube": {
        "max_text": 5000,  # treat as description
        "supports_link": True,
        "media": {"max_items": 1, "types": {"video"}, "video_max_items": 1},
        "requires_destination_type": {"channel"},
        "requires_media": True,
        "placements": {"feed"},
    },

    # TikTok: video-first
    "tiktok": {
        "max_text": 2200,
        "supports_link": False,
        "media": {"max_items": 1, "types": {"video"}, "video_max_items": 1},
        "requires_destination_type": {"user"},
        "requires_media": True,
        "placements": {"feed"},
    },
}

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _parse_iso8601_with_tz(value: str) -> datetime:
    try:
        dt = dateparser.isoparse(value)
    except Exception:
        raise ValidationError("Invalid datetime. Use ISO8601 (e.g. 2026-01-26T12:50:00+00:00).")

    if dt.tzinfo is None:
        raise ValidationError("scheduled_at must include timezone (e.g. +00:00).")

    return dt.astimezone(timezone.utc)


def _is_url(s: str) -> bool:
    return isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))


def _count_media_types(media: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for m in media:
        t = (m.get("asset_type") or "").lower()
        if not t:
            continue
        counts[t] = counts.get(t, 0) + 1
    return counts


def _default_placement(dest: dict) -> str:
    p = (dest.get("placement") or "").strip().lower()
    return p or "feed"


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------
class MediaAssetSchema(Schema):
    """
    Cloudinary output maps to this structure for both images + videos.

    NOTE:
    - Allows extra provider fields (Cloudinary includes many)
    - Includes duration (fixes your "Unknown field duration" issue)
    """

    class Meta:
        unknown = INCLUDE  # ✅ keep Cloudinary extras like duration, resource_type, etc.

    asset_id = fields.Str(required=False, allow_none=True)
    public_id = fields.Str(required=False, allow_none=True)

    asset_provider = fields.Str(required=False, load_default="cloudinary")
    asset_type = fields.Str(required=True, validate=validate.OneOf(["image", "video"]))

    url = fields.Str(required=True)

    width = fields.Int(required=False, allow_none=True)
    height = fields.Int(required=False, allow_none=True)
    format = fields.Str(required=False, allow_none=True)
    bytes = fields.Int(required=False, allow_none=True)

    # ✅ video-only metadata
    duration = fields.Float(required=False, allow_none=True)

    created_at = fields.Str(required=False, allow_none=True)

    @validates_schema
    def validate_media(self, data, **kwargs):
        if not _is_url(data.get("url", "")):
            raise ValidationError({"url": ["url must start with http:// or https://"]})

        # At least one stable identifier should exist
        if not (data.get("asset_id") or data.get("public_id")):
            raise ValidationError({"asset_id": ["asset_id or public_id is required"]})


class DestinationSchema(Schema):
    """
    One destination per post fanout.
    """

    platform = fields.Str(required=True, validate=validate.OneOf(sorted(list(PLATFORM_RULES.keys()))))
    destination_type = fields.Str(required=True)
    destination_id = fields.Str(required=True)
    destination_name = fields.Str(required=False, allow_none=True)
    channel_id = fields.Str(required=False, allow_none=True)

    placement = fields.Str(
        required=False,
        load_default="feed",
        validate=validate.OneOf(["feed", "reel", "story"]),
    )

    @pre_load
    def normalize(self, in_data, **kwargs):
        if isinstance(in_data, dict):
            if in_data.get("platform"):
                in_data["platform"] = str(in_data["platform"]).strip().lower()
            if in_data.get("placement"):
                in_data["placement"] = str(in_data["placement"]).strip().lower()
        return in_data


class ScheduledPostContentSchema(Schema):
    """
    Normalized content object stored under scheduled_posts.content
    """

    class Meta:
        unknown = INCLUDE

    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)

    # We normalize to list[dict]
    media = fields.Raw(required=False, allow_none=True)

    @pre_load
    def normalize_media(self, in_data, **kwargs):
        if not isinstance(in_data, dict):
            return in_data

        media = in_data.get("media")
        if media is None:
            return in_data

        if isinstance(media, dict):
            in_data["media"] = [media]
        elif isinstance(media, list):
            in_data["media"] = media
        else:
            in_data["media"] = None

        return in_data


class CreateScheduledPostSchema(Schema):
    """
    Validates inbound POST /social/scheduled-posts

    Supports:
      - top-level text/link/media
      - OR nested content: {text, link, media}

    Output helpers:
      data["_scheduled_at_utc"]
      data["_normalized_content"]
      data["_normalized_media"]
    """

    scheduled_at = fields.Str(required=True)

    destinations = fields.List(
        fields.Nested(DestinationSchema),
        required=True,
        validate=validate.Length(min=1),
    )

    # accept either style
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)

    content = fields.Nested(ScheduledPostContentSchema, required=False)

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

        media_val = content.get("media")
        if isinstance(media_val, dict):
            content["media"] = [media_val]

        in_data["content"] = content
        return in_data

    @validates_schema
    def validate_all(self, data, **kwargs):
        scheduled_at_raw = data.get("scheduled_at")
        scheduled_at_utc = _parse_iso8601_with_tz(scheduled_at_raw)

        content = data.get("content") or {}

        text = (content.get("text") or "").strip()
        link = (content.get("link") or "").strip() or None

        media_list = content.get("media") or []
        if not isinstance(media_list, list):
            raise ValidationError({"content": {"media": ["media must be an object or list"]}})

        parsed_media: List[Dict[str, Any]] = []
        media_errors: Dict[str, Any] = {}

        for idx, m in enumerate(media_list):
            try:
                parsed_media.append(MediaAssetSchema().load(m))
            except ValidationError as ve:
                media_errors[str(idx)] = ve.messages

        if media_errors:
            raise ValidationError({"content": {"media": media_errors}})

        if not text and not parsed_media:
            raise ValidationError({"content": ["Provide at least one of text or media"]})

        if link and not _is_url(link):
            raise ValidationError({"content": {"link": ["Invalid URL"]}})

        destinations = data.get("destinations") or []
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

        THREADS_TYPE_ALIASES = {
            "user": "user",
            "profile": "user",
            "person": "user",
            "member": "user",
            "author": "user",
            "threads_user": "user",
        }

        # ✅ NEW: YouTube destination type aliases
        YOUTUBE_TYPE_ALIASES = {
            "channel": "channel",
            "youtube_channel": "channel",
            "yt_channel": "channel",
            "creator": "channel",
        }

        for idx, dest in enumerate(destinations):
            platform = (dest.get("platform") or "").lower().strip()
            placement = _default_placement(dest)

            dest["platform"] = platform
            dest["placement"] = placement

            # ------------------------------
            # LINKEDIN NORMALIZATION
            # ------------------------------
            if platform == "linkedin":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = LINKEDIN_TYPE_ALIASES.get(raw_type, raw_type)

            # ------------------------------
            # THREADS NORMALIZATION
            # ------------------------------
            elif platform == "threads":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = THREADS_TYPE_ALIASES.get(raw_type, raw_type)
                else:
                    dest["destination_type"] = "user"
                if not placement:
                    dest["placement"] = "feed"

            # ------------------------------
            # ✅ YOUTUBE NORMALIZATION
            # ------------------------------
            elif platform == "youtube":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = YOUTUBE_TYPE_ALIASES.get(raw_type, raw_type)
                else:
                    dest["destination_type"] = "channel"  # default

                # If frontend sends channel_id (connect endpoint style), map it to destination_id
                # so the rest of your pipeline is consistent.
                if not dest.get("destination_id") and dest.get("channel_id"):
                    dest["destination_id"] = dest.get("channel_id")

                # Default placement (optional): "video" or "short"
                if not dest.get("placement"):
                    dest["placement"] = "video"

            rule = PLATFORM_RULES.get(platform)
            if not rule:
                dest_errors.append({str(idx): {"platform": ["Unsupported platform"]}})
                continue

            allowed_types = rule.get("requires_destination_type") or set()
            if allowed_types and dest.get("destination_type") not in allowed_types:
                dest_errors.append({
                    str(idx): {
                        "destination_type": [f"{platform} requires destination_type in {sorted(allowed_types)}"]
                    }
                })

            allowed_placements = set(rule.get("placements") or [])
            if allowed_placements and placement not in allowed_placements:
                dest_errors.append({
                    str(idx): {"placement": [f"{platform} placement must be one of {sorted(allowed_placements)}"]}
                })

            max_text = rule.get("max_text")
            if max_text and text and len(text) > max_text:
                dest_errors.append({
                    str(idx): {"content.text": [f"Too long for {platform}. Max {max_text} chars."]}
                })

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
            allowed_types_media = set(media_rule.get("types") or [])
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
                    at = (m.get("asset_type") or "").lower()
                    if allowed_types_media and at not in allowed_types_media:
                        dest_errors.append({
                            str(idx): {"content.media": [f"{platform} does not allow '{at}' for this post."]}
                        })

            # Facebook / Instagram / Threads special blocks unchanged...
            if platform == "facebook":
                if placement == "feed" and len(parsed_media) > 1:
                    dest_errors.append({str(idx): {"content.media": ["Facebook feed supports only 1 media item."]}})
                elif placement == "reel":
                    if len(parsed_media) != 1:
                        dest_errors.append({str(idx): {"content.media": ["Facebook reels require exactly 1 media item (video)."]}})
                    elif parsed_media[0]["asset_type"].lower() != "video":
                        dest_errors.append({str(idx): {"content.media": ["Facebook reels require a video."]}})

            elif platform == "instagram":
                if len(parsed_media) < 1:
                    dest_errors.append({str(idx): {"content.media": ["Instagram requires at least 1 media item."]}})
                if placement == "reel":
                    if len(parsed_media) != 1:
                        dest_errors.append({str(idx): {"content.media": ["Instagram reel requires exactly 1 media item."]}})
                    elif parsed_media[0]["asset_type"].lower() != "video":
                        dest_errors.append({str(idx): {"content.media": ["Instagram reel requires a video."]}})
                elif placement == "story" and len(parsed_media) != 1:
                    dest_errors.append({str(idx): {"content.media": ["Instagram story requires exactly 1 media item."]}})

            elif platform == "threads":
                pass

            # ✅ Optional: YouTube extra validation (lightweight)
            elif platform == "youtube":
                # Connect requires channel_id; scheduling/publishing uses destination_id
                if not dest.get("destination_id"):
                    dest_errors.append({str(idx): {"destination_id": ["YouTube requires destination_id (channel_id)."]}})

        if dest_errors:
            raise ValidationError({"destinations": dest_errors})

        data["_scheduled_at_utc"] = scheduled_at_utc
        data["_normalized_content"] = {
            "text": text or None,
            "link": link,
            "media": parsed_media or None,
        }
        data["_normalized_media"] = parsed_media or None    
        
        

class ScheduledPostStoredSchema(Schema):
    """
    Optional response schema for what you store in MongoDB.
    """

    _id = fields.Str()
    business_id = fields.Str()
    user__id = fields.Str()

    platform = fields.Str()
    status = fields.Str()

    scheduled_at_utc = fields.DateTime()

    destinations = fields.List(fields.Nested(DestinationSchema))
    content = fields.Nested(ScheduledPostContentSchema)

    provider_results = fields.List(fields.Dict(), required=False)
    error = fields.Str(required=False, allow_none=True)

    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    

class ListScheduledPostsQuerySchema(Schema):
    page = fields.Int(load_default=1)
    per_page = fields.Int(load_default=20)

    status = fields.Str(required=False)

    # ✅ allow: ?platform=instagram&platform=facebook
    platform = fields.List(fields.Str(), required=False)

    # optional date filters
    date_from = fields.Str(required=False)
    date_to = fields.Str(required=False)

















