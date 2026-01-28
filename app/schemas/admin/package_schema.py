# schemas/admin/package_schema.py

from marshmallow import Schema, fields, validate, EXCLUDE
from ...utils.validation import validate_objectid
from ...constants.payment_methods import get_all_payment_methods


# -----------------------------
# Enums aligned with new Package model
# -----------------------------
TIERS = ["Standard", "Advanced", "Enterprise"]
BILLING_PERIODS = ["monthly", "quarterly", "yearly", "lifetime", "custom"]
PRICE_MODELS = ["per_user", "flat", "custom"]
STATUSES = ["Active", "Inactive", "Deprecated"]


class PackageSchema(Schema):
    """Schema for Package validation (Social Media Management SaaS)."""
    class Meta:
        unknown = EXCLUDE  # optional: ignore extra fields instead of failing

    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"required": "Package name is required"},
    )

    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=500),
    )

    tier = fields.Str(
        required=True,
        validate=validate.OneOf(TIERS),
        error_messages={"required": "Package tier is required"},
    )

    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(BILLING_PERIODS),
        error_messages={"required": "Billing period is required"},
    )

    # NEW: per-user vs flat vs custom
    price_model = fields.Str(
        load_default="per_user",
        validate=validate.OneOf(PRICE_MODELS),
    )

    # Allow Enterprise/custom pricing => price can be null
    price = fields.Float(
        required=False,
        allow_none=True,
        validate=lambda x: (x is None) or (x >= 0),
        error_messages={"invalid": "Price must be a number >= 0 (or null for custom)."},
    )

    currency = fields.Str(
        load_default="GBP",
        validate=validate.Length(equal=3),
    )

    setup_fee = fields.Float(
        load_default=0.0,
        validate=lambda x: x >= 0,
    )

    trial_days = fields.Int(
        load_default=0,
        validate=lambda x: x >= 0,
    )

    # -----------------------------
    # UPDATED limits for social app
    # -----------------------------
    max_users = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    max_social_accounts = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x else True,
    )

    bulk_schedule_limit = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x else True,
    )

    competitor_tracking = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x else True,
    )

    history_search_days = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x else True,
    )

    # Feature flags (kept as dict for flexibility)
    features = fields.Dict(required=False, load_default={})

    is_popular = fields.Bool(load_default=False)
    display_order = fields.Int(load_default=0)

    status = fields.Str(
        load_default="Active",
        validate=validate.OneOf(STATUSES),
    )


class PackageUpdateSchema(Schema):
    """Schema for updating a Package (partial updates allowed)."""
    class Meta:
        unknown = EXCLUDE  # optional: ignore extra fields instead of failing

    package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Package ID is required", "invalid": "Invalid Package ID"},
    )

    name = fields.Str(required=False, allow_none=True, validate=validate.Length(min=2, max=100))

    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=500))

    tier = fields.Str(required=False, allow_none=True, validate=validate.OneOf(TIERS))

    billing_period = fields.Str(required=False, allow_none=True, validate=validate.OneOf(BILLING_PERIODS))

    price_model = fields.Str(required=False, allow_none=True, validate=validate.OneOf(PRICE_MODELS))

    price = fields.Float(
        required=False,
        allow_none=True,
        validate=lambda x: (x is None) or (x >= 0),
    )

    currency = fields.Str(required=False, allow_none=True, validate=validate.Length(equal=3))

    setup_fee = fields.Float(required=False, allow_none=True, validate=lambda x: x >= 0)

    trial_days = fields.Int(required=False, allow_none=True, validate=lambda x: x >= 0)

    max_users = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    max_social_accounts = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    bulk_schedule_limit = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    competitor_tracking = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    history_search_days = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)

    features = fields.Dict(required=False, load_default={})

    is_popular = fields.Bool(required=False, allow_none=True)
    display_order = fields.Int(required=False, allow_none=True)

    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))


class PackageQuerySchema(Schema):
    """Schema for querying a single Package by ID."""

    package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Package ID is required", "invalid": "Invalid Package ID"},
    )


class SubscriptionSchema(Schema):
    """Schema for creating a subscription."""

    package_id = fields.Str(required=True, error_messages={"required": "Package ID is required"})

    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(BILLING_PERIODS),
        error_messages={"required": "Billing period is required"},
    )

    # Optional: how many seats the customer is paying for (important for per-user pricing)
    seats = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x is not None else True,
        load_default=1,
    )

    payment_method = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(get_all_payment_methods()),
    )

    payment_reference = fields.Str(required=False, allow_none=True)
    auto_renew = fields.Bool(load_default=True)


class CancelSubscriptionSchema(Schema):
    """Schema for subscription cancellation."""

    reason = fields.Str(required=False, allow_none=True, validate=validate.Length(max=500))