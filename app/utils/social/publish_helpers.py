# app/utils/social/publish_helpers.py

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Dict, List


# ---------------------------------------------------------
# Parse ISO date string into UTC-aware datetime
# ---------------------------------------------------------
def _parse_iso8601_with_tz(value: str) -> datetime:
    """
    Parse an ISO 8601 datetime string and ensure it's UTC-aware.

    Accepts:
      - 2026-02-03T10:00:00Z
      - 2026-02-03T10:00:00+00:00
      - 2026-02-03T10:00:00

    Returns:
      datetime with tzinfo=UTC
    """
    if not value:
        raise ValueError("Missing datetime")

    try:
        # Normalize trailing Z
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")

        dt = datetime.fromisoformat(value)

        # If naive, force UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        raise ValueError(f"Invalid ISO datetime: {value}")


# ---------------------------------------------------------
# URL validation
# ---------------------------------------------------------
def _is_url(value: str) -> bool:
    if not value:
        return False

    try:
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


# ---------------------------------------------------------
# Ensure list
# ---------------------------------------------------------
def _as_list(val):
    """
    Normalize value into a list.

    None -> []
    dict -> [dict]
    scalar -> [scalar]
    list -> list
    """
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


# ---------------------------------------------------------
# Determine default placement per destination
# ---------------------------------------------------------
def _default_placement(dest: Dict[str, Any]) -> str:
    """
    Determine placement if missing.

    Uses:
      - dest["placement"]
      - defaults to "feed"
      - WhatsApp defaults to "direct"
    """
    placement = (dest.get("placement") or "").strip()
    if placement:
        return placement

    platform = (dest.get("platform") or "").lower()

    if platform == "whatsapp":
        return "direct"

    return "feed"


# ---------------------------------------------------------
# Count media types
# ---------------------------------------------------------
def _count_media_types(media: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Returns:
      { "image": 2, "video": 1 }
    """
    counts = {}

    for m in media or []:
        atype = (m.get("asset_type") or "").lower()
        if not atype:
            continue

        counts[atype] = counts.get(atype, 0) + 1

    return counts