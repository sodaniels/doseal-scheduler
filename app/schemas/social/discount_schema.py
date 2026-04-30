# schemas/admin/discount_schema.py

from marshmallow import Schema, fields, validate, EXCLUDE
from ...utils.validation import validate_objectid


DISCOUNT_TYPES = ["percentage", "fixed"]
DURATIONS = ["once", "repeating", "forever"]
STATUSES = ["Active", "Inactive", "Expired", "Exhausted"]
TIERS = ["Free", "Starter", "Small", "Medium", "Large", "Unlimited"]
BILLING_PERIODS = ["monthly", "annually"]


class DiscountCreateSchema(Schema):
    """Schema for creating a discount code (SYSTEM_OWNER only)."""
    class Meta:
        unknown = EXCLUDE

    code = fields.Str(
        required=True,
        validate=validate.Length(min=3, max=30),
        error_messages={"required": "Discount code is required"},
    )
    discount_type = fields.Str(
        required=True,
        validate=validate.OneOf(DISCOUNT_TYPES),
        error_messages={"required": "Discount type is required (percentage or fixed)"},
    )
    value = fields.Float(
        required=True,
        validate=lambda x: x > 0,
        error_messages={"required": "Discount value is required"},
    )
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=500))

    # Limits
    max_uses = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    max_uses_per_business = fields.Int(load_default=1, validate=lambda x: x > 0)

    # Validity
    start_date = fields.DateTime(required=False, allow_none=True)
    end_date = fields.DateTime(required=False, allow_none=True)

    # Restrictions
    applicable_tiers = fields.List(fields.Str(validate=validate.OneOf(TIERS)), load_default=[])
    applicable_billing_periods = fields.List(fields.Str(validate=validate.OneOf(BILLING_PERIODS)), load_default=[])
    minimum_amount = fields.Float(load_default=0, validate=lambda x: x >= 0)
    first_time_only = fields.Bool(load_default=False)

    # Duration
    duration = fields.Str(load_default="once", validate=validate.OneOf(DURATIONS))
    duration_months = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)


class DiscountUpdateSchema(Schema):
    """Schema for updating a discount code."""
    class Meta:
        unknown = EXCLUDE

    discount_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])

    code = fields.Str(required=False, allow_none=True, validate=validate.Length(min=3, max=30))
    discount_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(DISCOUNT_TYPES))
    value = fields.Float(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=500))
    max_uses = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    max_uses_per_business = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    start_date = fields.DateTime(required=False, allow_none=True)
    end_date = fields.DateTime(required=False, allow_none=True)
    applicable_tiers = fields.List(fields.Str(validate=validate.OneOf(TIERS)), required=False)
    applicable_billing_periods = fields.List(fields.Str(validate=validate.OneOf(BILLING_PERIODS)), required=False)
    minimum_amount = fields.Float(required=False, allow_none=True, validate=lambda x: x >= 0 if x is not None else True)
    first_time_only = fields.Bool(required=False, allow_none=True)
    duration = fields.Str(required=False, allow_none=True, validate=validate.OneOf(DURATIONS))
    duration_months = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))


class DiscountQuerySchema(Schema):
    discount_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])


class DiscountApplySchema(Schema):
    """Schema for applying/validating a discount code during checkout."""
    class Meta:
        unknown = EXCLUDE

    code = fields.Str(required=True, validate=validate.Length(min=3, max=30), error_messages={"required": "Discount code is required"})
    package_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid], error_messages={"required": "Package ID is required"})
    billing_period = fields.Str(required=True, validate=validate.OneOf(BILLING_PERIODS), error_messages={"required": "Billing period is required"})
