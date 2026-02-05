# app/services/social/llm/schwriter_service.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .llm_router import llm_generate_json
from .prompts import build_schwriter_system_prompt, build_schwriter_user_prompt


@dataclass
class SchWriterRequest:
    platform: str
    action: str  # fix_grammar|optimize_length|adjust_tone|inspire_engagement|full
    content: Dict[str, Any]  # {text, link, media}
    brand: Optional[Dict[str, Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    platform_rules: Optional[Dict[str, Any]] = None


class SchWriterService:
    """
    Thin service that:
      - builds prompts
      - calls LLM router
      - returns JSON for UI
    """

    @staticmethod
    def enhance(req: SchWriterRequest) -> Dict[str, Any]:
        system = build_schwriter_system_prompt(platform=req.platform)
        prompt = build_schwriter_user_prompt(
            action=req.action,
            platform=req.platform,
            content=req.content,
            platform_rules=req.platform_rules,
            brand=req.brand,
            preferences=req.preferences,
        )

        result = llm_generate_json(
            system=system,
            prompt=prompt,
            max_tokens=900,
            temperature=0.2,
        )

        # minimal normalization
        result.setdefault("platform", (req.platform or "").lower().strip() or "multi")
        result.setdefault("action", (req.action or "full").lower().strip())
        result.setdefault("suggestions", [])
        result.setdefault("platform_notes", [])
        result.setdefault("warnings", [])
        result.setdefault("rewrites", {"recommended_text": None, "alternatives": []})
        result.setdefault("metrics", {
            "original_length": 0,
            "recommended_length": None,
            "hashtag_count": 0,
            "emoji_count": 0,
            "link_present": False,
        })

        return result