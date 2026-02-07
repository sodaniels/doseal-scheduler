# app/services/notifications/notification_config.py

from __future__ import annotations

from typing import Any, Dict


# Stable keys for your UI and your backend logic
NOTIFICATION_CONFIG: Dict[str, Any] = {
    "version": 1,
    "channels": [
        {"key": "email", "label": "Email Notifications"},
        {"key": "in_app", "label": "In-App Notifications"},
        # add later if you want:
        # {"key": "push", "label": "Push Notifications"},
    ],
    "sections": [
        {
            "key": "scheduled_messages",
            "label": "Scheduled Messages",
            "groups": [
                {
                    "key": "email_notifications",
                    "label": "Email Notifications",
                    "items": [
                        {
                            "key": "scheduled_send_failed",
                            "label": "When a scheduled message I wrote fails to send",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "scheduled_send_succeeded",
                            "label": "When a scheduled message I wrote is sent successfully",
                            "default": {"email": False, "in_app": True},
                        },
                    ],
                }
            ],
        },
        {
            "key": "organization_and_teams",
            "label": "Organization and Teams",
            "groups": [
                {
                    "key": "workflow",
                    "label": "Workflow",
                    "items": [
                        {
                            "key": "message_requires_approval",
                            "label": "When a message is created that requires approval",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "message_rejected_in_pre_review",
                            "label": "When a message is rejected in pre-review",
                            "default": {"email": True, "in_app": True},
                        },
                    ],
                }
            ],
        },
        {
            "key": "product_notifications",
            "label": "Product Notifications",
            "groups": [
                {
                    "key": "message_approvals",
                    "label": "Message Approvals",
                    "items": [
                        {
                            "key": "message_requires_my_approval",
                            "label": "Message requires my approval",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "message_rejected_in_pre_screening",
                            "label": "Message was rejected in pre-screening",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "message_rejected",
                            "label": "Message is rejected",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "message_approved",
                            "label": "Message is approved",
                            "default": {"email": False, "in_app": True},
                        },
                        {
                            "key": "message_expired",
                            "label": "Message has expired",
                            "default": {"email": True, "in_app": True},
                        },
                    ],
                }
            ],
        },
        {
            "key": "internal_comments",
            "label": "Internal Comments",
            "groups": [
                {
                    "key": "collaboration",
                    "label": "Internal comments",
                    "items": [
                        {
                            "key": "mentions_and_replies",
                            "label": "Mentions and replies",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "comments_on_my_posts_or_drafts",
                            "label": "Comments on all posts or drafts I’ve created",
                            "default": {"email": True, "in_app": True},
                        },
                        {
                            "key": "conversations_im_part_of",
                            "label": "Conversations I’m a part of",
                            "default": {"email": True, "in_app": True},
                        },
                    ],
                }
            ],
        },
    ],
}


def build_default_settings() -> Dict[str, Any]:
    """
    Returns:
      {
        "email": { "<item_key>": bool, ... },
        "in_app": { "<item_key>": bool, ... }
      }
    """
    defaults = {"email": {}, "in_app": {}}

    for section in NOTIFICATION_CONFIG.get("sections", []):
        for group in section.get("groups", []):
            for item in group.get("items", []):
                key = item["key"]
                d = item.get("default") or {}
                defaults["email"][key] = bool(d.get("email", False))
                defaults["in_app"][key] = bool(d.get("in_app", False))

    return defaults