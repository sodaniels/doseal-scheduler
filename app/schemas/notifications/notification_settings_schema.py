# app/schemas/notifications/notification_settings_schema.py

from __future__ import annotations

from marshmallow import Schema, fields, validate


class NotificationSettingsPatchSchema(Schema):
    """
    Accept partial updates only.
    """
    channels = fields.Dict(required=True)


class NotificationSettingsSchema(Schema):
    _id = fields.String()
    business_id = fields.String()
    user__id = fields.String()
    channels = fields.Dict()
    created_at = fields.Raw()
    updated_at = fields.Raw()