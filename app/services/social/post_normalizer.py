from copy import deepcopy

def normalize_content_for_platform(platform: str, content: dict) -> dict:
    """
    Mutate content to satisfy platform quirks
    WITHOUT losing user intent.
    """
    content = deepcopy(content)

    # --------------------------------------------------
    # Instagram: no clickable link field
    # --------------------------------------------------
    if platform == "instagram":
        if content.get("link"):
            text = content.get("text") or ""
            link = content["link"]

            if link not in text:
                content["text"] = f"{text}\n\n{link}".strip()

            content.pop("link", None)

    return content