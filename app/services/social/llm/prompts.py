# app/services/social/llm/prompts.py

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return "{}"


def build_schwriter_system_prompt(*, platform: str) -> str:
    """
    System prompt: sets strict role + output rules for the "SchWriter" feature.
    """
    platform = (platform or "multi").lower().strip()
    return f"""
        You are SchWriter, a social-media copy assistant.

        Goal:
        - Provide platform-aware recommendations and optional rewrites.
        - Be practical, specific, and enforce platform constraints.

        Output:
        - Return ONLY valid JSON (no markdown, no explanation).
        - Match the response schema EXACTLY as requested by the user prompt.

        Platform:
        - Current platform context: "{platform}"
    """.strip()


def build_schwriter_user_prompt(
    *,
    action: str,
    platform: str,
    content: Dict[str, Any],
    platform_rules: Optional[Dict[str, Any]] = None,
    brand: Optional[Dict[str, Any]] = None,
    preferences: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Builds a single user prompt that forces structured JSON.

    action:
      - fix_grammar
      - optimize_length
      - adjust_tone
      - inspire_engagement
      - full (returns all)
    """
    platform = (platform or "multi").lower().strip()
    action = (action or "full").lower().strip()

    req_schema = {
        "platform": "string",
        "action": "string",
        "suggestions": [
            {
                "type": "string",
                "title": "string",
                "details": ["string"],
            }
        ],
        "platform_notes": ["string"],
        "warnings": ["string"],
        "rewrites": {
            "recommended_text": "string|null",
            "alternatives": ["string"],
        },
        "metrics": {
            "original_length": "int",
            "recommended_length": "int|null",
            "hashtag_count": "int",
            "emoji_count": "int",
            "link_present": "bool",
        },
    }

    return f"""
            ACTION: {action}

            You will produce SchWriter recommendations for ONE platform.

            Input:
            platform="{platform}"
            content={_safe_json(content)}
            brand={_safe_json(brand or {})}
            preferences={_safe_json(preferences or {})}
            platform_rules={_safe_json(platform_rules or {})}

            Rules:
            - If the platform does not support clickable links, recommend placing the link inside the text (append it).
            - Respect max_text if provided.
            - If media is provided, suggest improvements relevant to media type (image/video/document).
            - Provide at least 2 suggestions if action is "full"; otherwise focus only on the selected action.

            Return ONLY JSON matching this schema:
            {_safe_json(req_schema)}
        """.strip()