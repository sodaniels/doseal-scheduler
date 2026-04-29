# schemas/church/integration_schema.py

from marshmallow import Schema, fields, validate, EXCLUDE
from ...utils.validation import validate_objectid

CATEGORIES = ["Payment Gateway", "Email Marketing", "SMS Provider", "WhatsApp", "Calendar Sync", "Accounting Export", "Automation", "Custom"]
STATUSES = ["Active", "Inactive", "Error", "Pending"]
WIDGET_TYPES = ["calendar", "giving", "forms", "events", "sermons", "custom"]

WEBHOOK_EVENTS = [
    "member.created", "member.updated", "member.deleted",
    "donation.created", "donation.refunded",
    "event.created", "event.registration",
    "attendance.recorded", "form.submitted",
    "pledge.created", "pledge.payment",
    "volunteer.signup", "volunteer.rsvp",
    "sacrament.created",
    "workflow.submitted", "workflow.approved", "workflow.rejected",
]

# ════════════════════════ INTEGRATION ════════════════════════

class IntegrationCreateSchema(Schema):
    class Meta: unknown = EXCLUDE
    provider = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    display_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=200))
    credentials = fields.Dict(required=False, load_default={})
    settings = fields.Dict(required=False, load_default={})
    status = fields.Str(load_default="Inactive", validate=validate.OneOf(STATUSES))
    is_live = fields.Bool(load_default=False)

class IntegrationUpdateSchema(Schema):
    class Meta: unknown = EXCLUDE
    integration_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)
    display_name = fields.Str(required=False, allow_none=True)
    credentials = fields.Dict(required=False, allow_none=True)
    settings = fields.Dict(required=False, allow_none=True)
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))
    is_live = fields.Bool(required=False, allow_none=True)

class IntegrationIdQuerySchema(Schema):
    integration_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)
    include_credentials = fields.Bool(load_default=False)

class IntegrationListQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    category = fields.Str(required=False, allow_none=True, validate=validate.OneOf(CATEGORIES))
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))
    page = fields.Int(load_default=1); per_page = fields.Int(load_default=50)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

class IntegrationByCategoryQuerySchema(Schema):
    branch_id = fields.Str(required=True, validate=validate_objectid)
    category = fields.Str(required=True, validate=validate.OneOf(CATEGORIES))

class IntegrationByProviderQuerySchema(Schema):
    branch_id = fields.Str(required=True, validate=validate_objectid)
    provider = fields.Str(required=True, validate=validate.Length(min=1, max=50))

class IntegrationTestSchema(Schema):
    integration_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)

class ProvidersQuerySchema(Schema):
    branch_id = fields.Str(required=True, validate=validate_objectid)

# ════════════════════════ WEBHOOK ════════════════════════

class WebhookCreateSchema(Schema):
    class Meta: unknown = EXCLUDE
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    target_url = fields.Url(required=True)
    event_types = fields.List(fields.Str(validate=validate.OneOf(WEBHOOK_EVENTS)), required=True, validate=validate.Length(min=1))
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    headers = fields.Dict(required=False, load_default={})
    retry_count = fields.Int(load_default=3, validate=lambda x: 0 <= x <= 10)

class WebhookUpdateSchema(Schema):
    class Meta: unknown = EXCLUDE
    webhook_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)
    name = fields.Str(required=False, allow_none=True, validate=validate.Length(min=1, max=200))
    target_url = fields.Url(required=False, allow_none=True)
    event_types = fields.List(fields.Str(validate=validate.OneOf(WEBHOOK_EVENTS)), required=False, allow_none=True)
    headers = fields.Dict(required=False, allow_none=True)
    retry_count = fields.Int(required=False, allow_none=True)
    is_active = fields.Bool(required=False, allow_none=True)

class WebhookIdQuerySchema(Schema):
    webhook_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)
    include_secret = fields.Bool(load_default=False)

class WebhookListQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    is_active = fields.Bool(required=False, allow_none=True)
    page = fields.Int(load_default=1); per_page = fields.Int(load_default=50)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

class WebhookEventsQuerySchema(Schema):
    branch_id = fields.Str(required=True, validate=validate_objectid)

# ════════════════════════ EMBED WIDGET ════════════════════════

class WidgetCreateSchema(Schema):
    class Meta: unknown = EXCLUDE
    widget_type = fields.Str(required=True, validate=validate.OneOf(WIDGET_TYPES))
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    settings = fields.Dict(required=False, load_default={})
    allowed_domains = fields.List(fields.Str(validate=validate.Length(max=200)), load_default=[])

class WidgetUpdateSchema(Schema):
    class Meta: unknown = EXCLUDE
    widget_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)
    name = fields.Str(required=False, allow_none=True)
    settings = fields.Dict(required=False, allow_none=True)
    allowed_domains = fields.List(fields.Str(), required=False, allow_none=True)
    is_active = fields.Bool(required=False, allow_none=True)

class WidgetIdQuerySchema(Schema):
    widget_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)

class WidgetListQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    widget_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(WIDGET_TYPES))
    page = fields.Int(load_default=1); per_page = fields.Int(load_default=50)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

class WidgetEmbedKeyQuerySchema(Schema):
    embed_key = fields.Str(required=True, validate=validate.Length(min=1, max=20))
