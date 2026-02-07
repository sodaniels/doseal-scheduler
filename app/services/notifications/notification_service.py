# app/services/notifications/notification_service.py

from __future__ import annotations

from typing import Any, Dict

from ...models.notifications.notification_settings import NotificationSettings


class NotificationService:
    @staticmethod
    def is_enabled(
        *,
        business_id: str,
        user__id: str,
        channel: str,          # "email" | "in_app"
        item_key: str,         # e.g. "scheduled_send_failed"
        default: bool = False,
    ) -> bool:
        """
        Returns the current toggle.
        Creates defaults if missing.
        """
        doc = NotificationSettings.get_or_create_defaults(business_id=business_id, user__id=user__id)
        channels = doc.get("channels") or {}
        ch = channels.get(channel) or {}
        val = ch.get(item_key)
        if isinstance(val, bool):
            return val
        return default