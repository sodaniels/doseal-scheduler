from typing import Any, Dict, List


def _ensure_content_shape(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize incoming payload into canonical shape:

    {
        content: {
            text: str|None,
            link: str|None,
            media: list[dict]|None
        },
        destinations: [...]
    }

    Accepts:
      - top-level text/link/media
      - content.text/link/media
      - media as dict or list
    """

    if not isinstance(body, dict):
        return body

    body = dict(body)  # shallow copy

    content = body.get("content") or {}
    if not isinstance(content, dict):
        content = {}

    # -------------------------------------------------
    # Move top-level → content
    # -------------------------------------------------
    for key in ("text", "link", "media"):
        if key not in content and key in body:
            content[key] = body.get(key)

    # -------------------------------------------------
    # Normalize media → list
    # -------------------------------------------------
    media_val = content.get("media")

    if media_val is None:
        content["media"] = None

    elif isinstance(media_val, dict):
        content["media"] = [media_val]

    elif isinstance(media_val, list):
        content["media"] = media_val

    else:
        # Unknown type → drop, schema will error
        content["media"] = media_val

    body["content"] = content

    return body