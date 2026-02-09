# app/schemas/social/scheduled_posts_schema.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from dateutil import parser as dateparser

from marshmallow import (
    Schema,
    fields,
    validates_schema,
    ValidationError,
    validate,
    pre_load,
    post_load,
    INCLUDE,
)

# ---------------------------------------------------------------------
# Platform rules (easy to extend / tweak later)
# ---------------------------------------------------------------------
PLATFORM_RULES: Dict[str, Dict[str, Any]] = {
    "facebook": {
        "max_text": 63206,
        "recommended_text": 500,
        "supports_link": True,
        "link_behavior": "attachment",  # Link becomes a preview card
        "media": {
            "max_items": 1,
            "types": {"image", "video"},
            "video_max_items": 1,
        },
        "requires_destination_type": {"page"},
        "requires_media": False,
        "placements": {"feed", "reel"},
    },

    "instagram": {
        "max_text": 2200,
        "recommended_text": 500,
        "max_hashtags": 30,
        "supports_link": False,
        "link_behavior": "ignore",  # Links are ignored (not clickable)
        "link_hint": "Add link to bio or use link stickers in stories",
        "media": {"max_items": 10, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"ig_user"},
        "requires_media": True,
        "placements": {"feed", "reel", "story"},
    },

    "x": {
        "max_text": 280,
        "max_text_with_media": 280,
        "max_text_with_link": 257,
        "supports_link": True,
        "link_behavior": "inline",  # Link is part of text, takes ~23 chars
        "media": {"max_items": 4, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"user"},
        "requires_media": False,
        "placements": {"feed"},
    },

    "linkedin": {
        "max_text": 3000,
        "recommended_text": 700,
        "supports_link": True,
        "link_behavior": "attachment",
        "media": {"max_items": 1, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"author", "organization"},
        "requires_media": False,
        "placements": {"feed"},
    },

    "youtube": {
        "max_text": 5000,
        "max_title": 100,
        "supports_link": True,
        "link_behavior": "in_description",  # Put links in video description
        "media": {
            "max_items": 1,
            "types": {"video"},
            "video_max_items": 1,
        },
        "requires_destination_type": {"channel"},
        "requires_media": True,
        "placements": {"video"},
    },

    "tiktok": {
        "max_text": 2200,
        "recommended_text": 300,
        "supports_link": False,
        "link_behavior": "ignore",
        "link_hint": "Add link to bio",
        "media": {"max_items": 1, "types": {"video"}, "video_max_items": 1},
        "requires_destination_type": {"user"},
        "requires_media": True,
        "placements": {"feed"},
    },

    "pinterest": {
        "max_text": 500,
        "max_title": 100,
        "supports_link": True,
        "link_behavior": "destination",  # Link is the pin destination
        "media": {"max_items": 1, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"board", "user"},
        "requires_media": True,
        "placements": {"pin"},
    },

    "threads": {
        "max_text": 500,
        "supports_link": True,
        "link_behavior": "inline",
        "media": {"max_items": 10, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"user"},
        "requires_media": False,
        "placements": {"feed"},
    },

    "whatsapp": {
        "max_text": 4096,
        "supports_link": True,
        "link_behavior": "inline",
        "media": {"max_items": 1, "types": {"image", "video"}, "video_max_items": 1},
        "requires_destination_type": {"phone_number"},
        "requires_media": False,
        "placements": {"direct"},
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


def _get_text_for_destination(
    dest: Dict[str, Any],
    platform_text: Optional[Dict[str, str]],
    global_text: Optional[str],
) -> str:
    """
    Get the appropriate text for a destination.
    
    Priority:
    1. destination.text (specific to this destination)
    2. platform_text[platform] (specific to this platform)
    3. global text (default for all platforms)
    """
    if dest.get("text"):
        return dest["text"].strip()
    
    platform = (dest.get("platform") or "").lower()
    if platform_text and platform in platform_text:
        return (platform_text[platform] or "").strip()
    
    return (global_text or "").strip()


def _get_link_for_destination(
    dest: Dict[str, Any],
    platform_link: Optional[Dict[str, str]],
    global_link: Optional[str],
) -> Optional[str]:
    """
    Get the appropriate link for a destination.
    
    Priority:
    1. destination.link (specific to this destination)
    2. platform_link[platform] (specific to this platform)
    3. global link (default for all platforms)
    
    Returns None if platform doesn't support links.
    """
    platform = (dest.get("platform") or "").lower()
    rule = PLATFORM_RULES.get(platform, {})
    
    # If platform doesn't support links, return None (don't error)
    if not rule.get("supports_link", True):
        return None
    
    # Check destination-specific link
    if dest.get("link"):
        return dest["link"].strip()
    
    # Check platform-specific link
    if platform_link and platform in platform_link:
        link = platform_link.get(platform)
        return link.strip() if link else None
    
    # Fall back to global link
    return global_link.strip() if global_link else None


def _validate_text_length(text: str, platform: str, has_link: bool = False, has_media: bool = False) -> Dict[str, Any]:
    """Validate text length for a platform."""
    rule = PLATFORM_RULES.get(platform, {})
    
    if platform == "x":
        if has_link:
            limit = rule.get("max_text_with_link", 257)
        elif has_media:
            limit = rule.get("max_text_with_media", 280)
        else:
            limit = rule.get("max_text", 280)
    else:
        limit = rule.get("max_text", 5000)
    
    length = len(text)
    recommended = rule.get("recommended_text")
    
    return {
        "valid": length <= limit,
        "length": length,
        "limit": limit,
        "remaining": limit - length,
        "recommended": recommended,
        "exceeds_recommended": recommended and length > recommended,
    }


def _count_hashtags(text: str) -> int:
    """Count hashtags in text."""
    import re
    return len(re.findall(r'#\w+', text))


# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------
class MediaAssetSchema(Schema):
    """Cloudinary output maps to this structure for both images + videos."""

    class Meta:
        unknown = INCLUDE

    asset_id = fields.Str(required=False, allow_none=True)
    public_id = fields.Str(required=False, allow_none=True)

    asset_provider = fields.Str(required=False, load_default="cloudinary")
    asset_type = fields.Str(required=True, validate=validate.OneOf(["image", "video"]))

    url = fields.Str(required=True)

    width = fields.Int(required=False, allow_none=True)
    height = fields.Int(required=False, allow_none=True)
    format = fields.Str(required=False, allow_none=True)
    bytes = fields.Int(required=False, allow_none=True)

    duration = fields.Float(required=False, allow_none=True)

    created_at = fields.Str(required=False, allow_none=True)

    @validates_schema
    def validate_media(self, data, **kwargs):
        if not _is_url(data.get("url", "")):
            raise ValidationError({"url": ["url must start with http:// or https://"]})

        if not (data.get("asset_id") or data.get("public_id")):
            raise ValidationError({"asset_id": ["asset_id or public_id is required"]})


class DestinationSchema(Schema):
    """
    One destination per post fanout.
    
    Supports optional per-destination overrides for text and link.
    """

    platform = fields.Str(required=True, validate=validate.OneOf(sorted(list(PLATFORM_RULES.keys()))))
    destination_type = fields.Str(required=True)
    destination_id = fields.Str(required=True)
    destination_name = fields.Str(required=False, allow_none=True)
    channel_id = fields.Str(required=False, allow_none=True)
    to = fields.Str(required=False, allow_none=True)
    meta = fields.Dict(required=False, allow_none=True)

    placement = fields.Str(required=False, allow_none=True)

    # Per-destination overrides
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)

    @pre_load
    def normalize(self, in_data, **kwargs):
        if isinstance(in_data, dict):
            if in_data.get("platform"):
                in_data["platform"] = str(in_data["platform"]).strip().lower()
            if in_data.get("placement"):
                in_data["placement"] = str(in_data["placement"]).strip().lower()
            if in_data.get("text"):
                in_data["text"] = str(in_data["text"]).strip()
            if in_data.get("link"):
                in_data["link"] = str(in_data["link"]).strip()
        return in_data


class ScheduledPostContentSchema(Schema):
    """Normalized content object stored under scheduled_posts.content"""

    class Meta:
        unknown = INCLUDE

    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)

    # Platform-specific overrides
    platform_text = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )
    
    platform_link = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )

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

    Text/Link Resolution Priority (per destination):
      1. destination.text / destination.link (highest priority)
      2. platform_text[platform] / platform_link[platform]
      3. text / link (global default)

    Link Handling:
      - Platforms that support links: link is used
      - Platforms that don't support links (Instagram, TikTok): link is ignored (no error)
      - A warning is added to _link_warnings for platforms where link was ignored

    Output helpers:
      data["_scheduled_at_utc"]
      data["_normalized_content"]
      data["_normalized_media"]
      data["_resolved_texts"]
      data["_resolved_links"]
      data["_link_warnings"]  # Platforms where link was provided but ignored
    """

    scheduled_at = fields.Str(required=True)

    destinations = fields.List(
        fields.Nested(DestinationSchema),
        required=True,
        validate=validate.Length(min=1),
    )

    # Global defaults
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)

    # Platform-specific overrides
    platform_text = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )
    
    platform_link = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )

    media = fields.Raw(required=False, allow_none=True)

    content = fields.Nested(ScheduledPostContentSchema, required=False)

    @pre_load
    def merge_content(self, in_data, **kwargs):
        if not isinstance(in_data, dict):
            return in_data

        content = in_data.get("content") or {}
        if not isinstance(content, dict):
            content = {}

        # Merge top-level fields into content
        if "text" not in content and in_data.get("text") is not None:
            content["text"] = in_data.get("text")

        if "link" not in content and in_data.get("link") is not None:
            content["link"] = in_data.get("link")

        if "media" not in content and in_data.get("media") is not None:
            content["media"] = in_data.get("media")

        if "platform_text" not in content and in_data.get("platform_text") is not None:
            content["platform_text"] = in_data.get("platform_text")

        if "platform_link" not in content and in_data.get("platform_link") is not None:
            content["platform_link"] = in_data.get("platform_link")

        # Normalize media to list
        media_val = content.get("media")
        if isinstance(media_val, dict):
            content["media"] = [media_val]

        # Normalize platform_text keys to lowercase
        platform_text = content.get("platform_text")
        if platform_text and isinstance(platform_text, dict):
            content["platform_text"] = {
                k.lower().strip(): v for k, v in platform_text.items()
            }

        # Normalize platform_link keys to lowercase
        platform_link = content.get("platform_link")
        if platform_link and isinstance(platform_link, dict):
            content["platform_link"] = {
                k.lower().strip(): v for k, v in platform_link.items()
            }

        in_data["content"] = content
        return in_data

    @validates_schema
    def validate_all(self, data, **kwargs):
        # Parse scheduled_at
        scheduled_at_raw = data.get("scheduled_at")
        scheduled_at_utc = _parse_iso8601_with_tz(scheduled_at_raw)

        content = data.get("content") or {}

        # Global defaults
        global_text = (content.get("text") or "").strip()
        global_link = (content.get("link") or "").strip() or None
        
        # Platform-specific overrides
        platform_text = content.get("platform_text") or {}
        platform_link = content.get("platform_link") or {}
        
        # Normalize keys
        if platform_text:
            platform_text = {k.lower().strip(): v for k, v in platform_text.items()}
        if platform_link:
            platform_link = {k.lower().strip(): v for k, v in platform_link.items()}

        # Validate global link format (if provided)
        if global_link and not _is_url(global_link):
            raise ValidationError({"content": {"link": ["Invalid URL"]}})

        # Validate platform_link URLs
        for platform, link in platform_link.items():
            if link and not _is_url(link):
                raise ValidationError({
                    "content": {"platform_link": {platform: ["Invalid URL"]}}
                })

        # Parse media
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

        destinations = data.get("destinations") or []
        dest_errors: List[Dict[str, Any]] = []
        
        # Track resolved texts and links
        resolved_texts: List[Dict[str, Any]] = []
        resolved_links: List[Dict[str, Any]] = []
        link_warnings: List[Dict[str, Any]] = []

        # Destination type aliases
        LINKEDIN_TYPE_ALIASES = {
            "profile": "author", "person": "author", "member": "author",
            "user": "author", "author": "author", "page": "organization",
            "company": "organization", "org": "organization",
            "organisation": "organization", "organization": "organization",
        }

        THREADS_TYPE_ALIASES = {
            "user": "user", "profile": "user", "person": "user",
            "member": "user", "author": "user", "threads_user": "user",
        }

        YOUTUBE_TYPE_ALIASES = {
            "channel": "channel", "youtube_channel": "channel",
            "yt_channel": "channel", "creator": "channel",
        }

        WHATSAPP_TYPE_ALIASES = {
            "phone": "phone_number", "number": "phone_number",
            "phone_number": "phone_number", "sender": "phone_number",
            "waba": "phone_number",
        }

        PINTEREST_TYPE_ALIASES = {
            "board": "board", "user": "user", "profile": "user",
        }

        for idx, dest in enumerate(destinations):
            platform = (dest.get("platform") or "").lower().strip()
            placement = _default_placement(dest)

            dest["platform"] = platform
            dest["placement"] = placement

            # ==============================
            # Platform-specific normalization
            # ==============================
            if platform == "linkedin":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                if raw_type:
                    dest["destination_type"] = LINKEDIN_TYPE_ALIASES.get(raw_type, raw_type)

            elif platform == "threads":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                dest["destination_type"] = THREADS_TYPE_ALIASES.get(raw_type, raw_type) if raw_type else "user"
                if not dest.get("placement"):
                    dest["placement"] = "feed"

            elif platform == "whatsapp":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                dest["destination_type"] = WHATSAPP_TYPE_ALIASES.get(raw_type, raw_type) if raw_type else "phone_number"
                if not dest.get("placement"):
                    dest["placement"] = "direct"

            elif platform == "youtube":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                dest["destination_type"] = YOUTUBE_TYPE_ALIASES.get(raw_type, raw_type) if raw_type else "channel"
                if not dest.get("destination_id") and dest.get("channel_id"):
                    dest["destination_id"] = dest.get("channel_id")
                if not dest.get("placement"):
                    dest["placement"] = "video"

            elif platform == "pinterest":
                raw_type = (dest.get("destination_type") or "").lower().strip()
                dest["destination_type"] = PINTEREST_TYPE_ALIASES.get(raw_type, raw_type) if raw_type else "board"
                if not dest.get("placement"):
                    dest["placement"] = "pin"

            # Get platform rules
            rule = PLATFORM_RULES.get(platform)
            if not rule:
                dest_errors.append({str(idx): {"platform": ["Unsupported platform"]}})
                continue

            # ==============================
            # RESOLVE TEXT FOR THIS DESTINATION
            # ==============================
            resolved_text = _get_text_for_destination(dest, platform_text, global_text)
            
            resolved_texts.append({
                "index": idx,
                "platform": platform,
                "destination_id": dest.get("destination_id"),
                "text": resolved_text,
                "text_source": (
                    "destination" if dest.get("text") else
                    "platform_text" if platform_text.get(platform) else
                    "global"
                ),
                "length": len(resolved_text),
                "limit": rule.get("max_text", 5000),
            })

            # ==============================
            # RESOLVE LINK FOR THIS DESTINATION
            # ==============================
            # Check if a link was intended for this destination
            intended_link = (
                dest.get("link") or
                platform_link.get(platform) or
                global_link
            )
            
            # Get the actual link to use (None if platform doesn't support links)
            resolved_link = _get_link_for_destination(dest, platform_link, global_link)
            
            resolved_links.append({
                "index": idx,
                "platform": platform,
                "destination_id": dest.get("destination_id"),
                "link": resolved_link,
                "link_source": (
                    "destination" if dest.get("link") and resolved_link else
                    "platform_link" if platform_link.get(platform) and resolved_link else
                    "global" if global_link and resolved_link else
                    None
                ),
                "supports_link": rule.get("supports_link", True),
            })
            
            # ==============================
            # ADD WARNING IF LINK WAS IGNORED
            # ==============================
            if intended_link and not resolved_link:
                link_hint = rule.get("link_hint", "Links are not supported on this platform")
                link_warnings.append({
                    "index": idx,
                    "platform": platform,
                    "destination_id": dest.get("destination_id"),
                    "ignored_link": intended_link,
                    "reason": f"{platform} does not support clickable links",
                    "hint": link_hint,
                })

            # ==============================
            # Validate destination type
            # ==============================
            allowed_types = rule.get("requires_destination_type") or set()
            if allowed_types and dest.get("destination_type") not in allowed_types:
                dest_errors.append({
                    str(idx): {
                        "destination_type": [f"{platform} requires destination_type in {sorted(allowed_types)}"]
                    }
                })

            # ==============================
            # Validate placement
            # ==============================
            allowed_placements = set(rule.get("placements") or [])
            placement = dest.get("placement") or "feed"
            if allowed_placements and placement not in allowed_placements:
                dest_errors.append({
                    str(idx): {"placement": [f"{platform} placement must be one of {sorted(allowed_placements)}"]}
                })

            # ==============================
            # VALIDATE TEXT LENGTH
            # ==============================
            max_text = rule.get("max_text")
            if max_text and resolved_text and len(resolved_text) > max_text:
                text_source = (
                    "destination.text" if dest.get("text") else
                    f"platform_text.{platform}" if platform_text.get(platform) else
                    "text"
                )
                dest_errors.append({
                    str(idx): {
                        text_source: [
                            f"Too long for {platform}. {len(resolved_text)} chars exceeds max {max_text}."
                        ]
                    }
                })

            # ==============================
            # Validate X/Twitter specific limits
            # ==============================
            if platform == "x" and resolved_text:
                has_link = bool(resolved_link)
                has_media = bool(parsed_media)
                
                validation = _validate_text_length(resolved_text, platform, has_link, has_media)
                
                if not validation["valid"]:
                    text_source = (
                        "destination.text" if dest.get("text") else
                        f"platform_text.{platform}" if platform_text.get(platform) else
                        "text"
                    )
                    context = ""
                    if has_link:
                        context = " (with link)"
                    elif has_media:
                        context = " (with media)"
                    
                    dest_errors.append({
                        str(idx): {
                            text_source: [
                                f"Too long for X{context}. {validation['length']} chars exceeds max {validation['limit']}."
                            ]
                        }
                    })

            # ==============================
            # Validate Instagram hashtag limit
            # ==============================
            if platform == "instagram" and resolved_text:
                max_hashtags = rule.get("max_hashtags", 30)
                hashtag_count = _count_hashtags(resolved_text)
                
                if hashtag_count > max_hashtags:
                    text_source = (
                        "destination.text" if dest.get("text") else
                        f"platform_text.{platform}" if platform_text.get(platform) else
                        "text"
                    )
                    dest_errors.append({
                        str(idx): {
                            text_source: [
                                f"Too many hashtags for Instagram. {hashtag_count} exceeds max {max_hashtags}."
                            ]
                        }
                    })

            # ==============================
            # Validate destination link URL (if provided)
            # ==============================
            dest_link = dest.get("link")
            if dest_link and not _is_url(dest_link):
                dest_errors.append({
                    str(idx): {"link": ["Invalid URL"]}
                })

            # ==============================
            # Validate media requirements
            # ==============================
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

            # ==============================
            # Platform-specific media validation
            # ==============================
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

            elif platform == "youtube":
                if not dest.get("destination_id"):
                    dest_errors.append({str(idx): {"destination_id": ["YouTube requires destination_id (channel_id)."]}})

            # ==============================
            # Check text + media requirement
            # ==============================
            if not resolved_text and not parsed_media:
                dest_errors.append({
                    str(idx): {
                        "content": [
                            f"Destination requires text or media. "
                            f"Provide destination.text, platform_text.{platform}, or global text."
                        ]
                    }
                })

        if dest_errors:
            raise ValidationError({"destinations": dest_errors})

        # ==============================
        # Store resolved data
        # ==============================
        data["_scheduled_at_utc"] = scheduled_at_utc
        data["_normalized_content"] = {
            "text": global_text or None,
            "platform_text": platform_text if platform_text else None,
            "link": global_link,
            "platform_link": platform_link if platform_link else None,
            "media": parsed_media or None,
        }
        data["_normalized_media"] = parsed_media or None
        data["_resolved_texts"] = resolved_texts
        data["_resolved_links"] = resolved_links
        data["_link_warnings"] = link_warnings  # Warnings for ignored links


class UpdateScheduledPostSchema(Schema):
    """Schema for updating a scheduled post."""
    
    scheduled_at = fields.Str(required=False)
    
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    
    platform_text = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )
    
    platform_link = fields.Dict(
        keys=fields.Str(),
        values=fields.Str(allow_none=True),
        required=False,
        allow_none=True,
    )
    
    media = fields.Raw(required=False, allow_none=True)
    
    destinations = fields.List(
        fields.Nested(DestinationSchema),
        required=False,
    )
    
    @pre_load
    def normalize(self, in_data, **kwargs):
        if not isinstance(in_data, dict):
            return in_data
        
        platform_text = in_data.get("platform_text")
        if platform_text and isinstance(platform_text, dict):
            in_data["platform_text"] = {
                k.lower().strip(): v for k, v in platform_text.items()
            }
        
        platform_link = in_data.get("platform_link")
        if platform_link and isinstance(platform_link, dict):
            in_data["platform_link"] = {
                k.lower().strip(): v for k, v in platform_link.items()
            }
        
        media = in_data.get("media")
        if isinstance(media, dict):
            in_data["media"] = [media]
        
        return in_data
    
    @validates_schema
    def validate_update(self, data, **kwargs):
        if data.get("scheduled_at"):
            data["_scheduled_at_utc"] = _parse_iso8601_with_tz(data["scheduled_at"])
        
        link = data.get("link")
        if link and not _is_url(link):
            raise ValidationError({"link": ["Invalid URL"]})
        
        platform_link = data.get("platform_link") or {}
        for platform, pl in platform_link.items():
            if pl and not _is_url(pl):
                raise ValidationError({"platform_link": {platform: ["Invalid URL"]}})
        
        media_list = data.get("media")
        if media_list:
            if not isinstance(media_list, list):
                media_list = [media_list]
            
            parsed_media = []
            media_errors = {}
            
            for idx, m in enumerate(media_list):
                try:
                    parsed_media.append(MediaAssetSchema().load(m))
                except ValidationError as ve:
                    media_errors[str(idx)] = ve.messages
            
            if media_errors:
                raise ValidationError({"media": media_errors})
            
            data["_normalized_media"] = parsed_media


class ScheduledPostStoredSchema(Schema):
    """Response schema for what is stored in MongoDB."""

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
    platform = fields.List(fields.Str(), required=False)

    date_from = fields.Str(required=False)
    date_to = fields.Str(required=False)


# ---------------------------------------------------------------------
# Helper Functions for Use in Publishers
# ---------------------------------------------------------------------
def get_text_for_destination(
    content: Dict[str, Any],
    destination: Dict[str, Any],
) -> str:
    """
    Get the resolved text for a destination from stored content.
    """
    return _get_text_for_destination(
        dest=destination,
        platform_text=content.get("platform_text"),
        global_text=content.get("text"),
    )


def get_link_for_destination(
    content: Dict[str, Any],
    destination: Dict[str, Any],
) -> Optional[str]:
    """
    Get the resolved link for a destination from stored content.
    Returns None if platform doesn't support links.
    """
    return _get_link_for_destination(
        dest=destination,
        platform_link=content.get("platform_link"),
        global_link=content.get("link"),
    )


def validate_text_for_platform(
    text: str,
    platform: str,
    has_link: bool = False,
    has_media: bool = False,
) -> Dict[str, Any]:
    """Validate text length for a platform."""
    return _validate_text_length(text, platform, has_link, has_media)


def get_platform_limits() -> Dict[str, Dict[str, Any]]:
    """Get all platform rules/limits."""
    return PLATFORM_RULES.copy()


def platform_supports_link(platform: str) -> bool:
    """Check if a platform supports clickable links."""
    rule = PLATFORM_RULES.get(platform.lower(), {})
    return rule.get("supports_link", True)


def get_link_hint(platform: str) -> Optional[str]:
    """Get hint for platforms that don't support links."""
    rule = PLATFORM_RULES.get(platform.lower(), {})
    return rule.get("link_hint")