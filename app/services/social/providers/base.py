# app/services/social/providers/base.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ProviderResult:
    platform: str
    destination_id: str
    destination_name: Optional[str]
    # canonical totals for the date-range
    totals: Dict[str, float]
    # daily timeline points (YYYY-MM-DD)
    timeline: List[Dict[str, Any]]
    # raw debug if needed
    debug: Optional[Dict[str, Any]] = None


class SocialProviderBase:
    platform: str = "unknown"

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> ProviderResult:
        raise NotImplementedError