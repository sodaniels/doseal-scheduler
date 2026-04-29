from marshmallow import Schema, fields, validate

from ...constants.provider_setting import (
    PAYMENT_PROVIDER_KEYS,
    SMS_PROVIDER_KEYS,
    EMAIL_PROVIDER_KEYS,
    WHATSAPP_PROVIDER_KEYS
)


class ProviderSettingUpsertSchema(Schema):
    branch_id = fields.String(required=False, allow_none=True)

    default_payment_provider = fields.String(
        required=False,
        allow_none=True,
        validate=validate.OneOf(PAYMENT_PROVIDER_KEYS),
    )
    default_sms_provider = fields.String(
        required=False,
        allow_none=True,
        validate=validate.OneOf(SMS_PROVIDER_KEYS),
    )
    default_email_provider = fields.String(
        required=False,
        allow_none=True,
        validate=validate.OneOf(EMAIL_PROVIDER_KEYS),
    )
    default_whatsapp_provider = fields.String(
        required=False,
        allow_none=True,
        validate=validate.OneOf(WHATSAPP_PROVIDER_KEYS),
    )

class ProviderSettingGetSchema(Schema):
    branch_id = fields.String(required=False, allow_none=True)


class ProviderSettingClearSchema(Schema):
    branch_id = fields.String(required=False, allow_none=True)
    keys = fields.List(
        fields.String(
            validate=validate.OneOf([
                "default_payment_provider",
                "default_sms_provider",
                "default_email_provider",
                "default_whatsapp_provider",
            ])
        ),
        required=True,
    )
    
    

class ProviderSettingQuerySchema(Schema):
    branch_id = fields.String(required=False, allow_none=True)


class ProviderSettingResponseSchema(Schema):
    _id = fields.String(dump_only=True)
    business_id = fields.String(dump_only=True)
    branch_id = fields.String(dump_only=True, allow_none=True)

    default_payment_provider = fields.String(dump_only=True, allow_none=True)
    default_sms_provider = fields.String(dump_only=True, allow_none=True)
    default_email_provider = fields.String(dump_only=True, allow_none=True)
    default_whatsapp_provider = fields.String(dump_only=True, allow_none=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class EligibleProviderListQuerySchema(Schema):
    branch_id = fields.String(required=False, allow_none=True)