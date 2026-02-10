from marshmallow import (
    Schema, fields, validate, ValidationError, validates_schema, validates, pre_load,
    INCLUDE
)
from decimal import Decimal, InvalidOperation

FACEBOOK_MIN_DAILY_BUDGET = 100        # $1.00
FACEBOOK_MIN_LIFETIME_BUDGET = 700     # ~$7.00 (safe minimum)

def _format_major(amount_minor: int, currency: str = "USD") -> str:
    return f"{amount_minor / 100:.2f} {currency}"

class MediaSchema(Schema):
    type = fields.Str(required=True, validate=validate.OneOf(["none", "image", "video"]))
    url = fields.Str(required=False, allow_none=True)       # public URL for IG/Threads/Pinterest
    file_path = fields.Str(required=False, allow_none=True) # local file for YouTube

class SchedulePostSchema(Schema):
    caption = fields.Str(required=True, validate=validate.Length(min=1, max=2200))
    platforms = fields.List(fields.Str(), required=True)
    scheduled_for = fields.DateTime(required=True)  # ISO datetime
    link = fields.Str(required=False, allow_none=True)
    media = fields.Nested(MediaSchema, required=False)
    extra = fields.Dict(required=False)

    @validates_schema
    def validate_platforms(self, data, **kwargs):
        allowed = {"facebook", "instagram", "threads", "x", "linkedin", "pinterest", "youtube", "tiktok"}
        plats = set(data.get("platforms") or [])
        bad = plats - allowed
        if bad:
            raise ValidationError({"platforms": [f"Unsupported platforms: {', '.join(sorted(bad))}"]})

class PaginationSchema(Schema):
    page = fields.Int(required=False, allow_none=True)
    per_page = fields.Int(required=False, allow_none=True)
    
class AccountConnectionSchema(Schema):
    destination_id = fields.Str(
        required=True,
        error_messages={"required": "Destination ID is required", "invalid": "Invalid Destination"}
    )
    
class AddsAccountConnectionSchema(Schema):
    destination_id = fields.Str(
        required=True,
        error_messages={"required": "Destination ID is required", "invalid": "Invalid Destination"}
    )
    ad_account_id = fields.Str(
        required=True,
        error_messages={"required": "Ad account is required", "invalid": "Invalid Ad account"}
    )
    page_id = fields.Str(
        required=False,
        allow_none=True
    )

class FacebookBoostPostSchema(Schema):
    class Meta:
        unknown = INCLUDE  # allow future extensions

    ad_account_id = fields.Str(required=True)
    page_id = fields.Str(required=False, allow_none=True)
    post_id = fields.Str(required=True)

    # Always stored in MINOR units (cents)
    budget_amount = fields.Int(required=True, strict=True)

    currency = fields.Str(
        required=False,
        load_default="USD",
        validate=validate.OneOf(["USD", "GBP", "EUR", "GHS", "NGN", "KES"]),
    )

    duration_days = fields.Int(
        required=True,
        strict=True,
        validate=validate.Range(min=1, max=365),
    )

    budget_type = fields.Str(
        required=False,
        load_default="lifetime",
        validate=validate.OneOf(["daily", "lifetime"]),
    )

    targeting = fields.Dict(required=False, allow_none=True)

    # ---------------------------------
    # Normalize budget to minor units
    # ---------------------------------
    @pre_load
    def normalize_budget(self, in_data, **kwargs):
        if not isinstance(in_data, dict):
            return in_data

        val = in_data.get("budget_amount")
        if val is None:
            return in_data

        try:
            d = Decimal(str(val))
        except (InvalidOperation, ValueError):
            raise ValidationError({"budget_amount": ["Invalid number format"]})

        if d <= 0:
            raise ValidationError({"budget_amount": ["Budget must be greater than 0"]})

        # Decimal → major units → convert to cents
        if d != d.to_integral_value():
            in_data["budget_amount"] = int((d * 100).to_integral_value())
        else:
            in_data["budget_amount"] = int(d)

        return in_data

    # ---------------------------------
    # Facebook-aware validation
    # ---------------------------------
    @validates_schema
    def validate_budget_rules(self, data, **kwargs):
        budget = int(data["budget_amount"])
        budget_type = data.get("budget_type", "lifetime")
        duration = data.get("duration_days", 1)
        currency = data.get("currency", "USD")

        def display(amount_minor: int) -> str:
            return f"{amount_minor / 100:.2f} {currency}"

        # DAILY budget rules
        if budget_type == "daily":
            if budget < FACEBOOK_MIN_DAILY_BUDGET:
                raise ValidationError({
                    "budget_amount": [
                        f"Facebook requires a minimum daily budget of {display(FACEBOOK_MIN_DAILY_BUDGET)}."
                    ]
                })

        # LIFETIME budget rules
        elif budget_type == "lifetime":
            if budget < FACEBOOK_MIN_LIFETIME_BUDGET:
                raise ValidationError({
                    "budget_amount": [
                        f"Facebook requires a minimum lifetime budget of {display(FACEBOOK_MIN_LIFETIME_BUDGET)}."
                    ]
                })

            avg_daily = budget / max(duration, 1)
            if avg_daily < FACEBOOK_MIN_DAILY_BUDGET:
                raise ValidationError({
                    "budget_amount": [
                        "Lifetime budget is too low for the selected duration. "
                        "Increase budget or reduce duration."
                    ]
                })

        # Targeting sanity check
        targeting = data.get("targeting")
        if targeting is not None and not isinstance(targeting, dict):
            raise ValidationError({"targeting": ["targeting must be an object"]})

class InstagramBoostPostSchema(Schema):
    ad_account_id = fields.String(required=True)
    page_id = fields.String(required=True)
    instagram_account_id = fields.String(required=False)
    media_id = fields.String(required=True)
    budget_amount = fields.Integer(required=True, validate=validate.Range(min=100))
    duration_days = fields.Integer(required=True, validate=validate.Range(min=1, max=90))
    targeting = fields.Dict(required=False)
    scheduled_post_id = fields.String(required=False)
    is_adset_budget_sharing_enabled = fields.Boolean(required=False, load_default=False)
    advantage_audience = fields.Boolean(required=False, load_default=False)

class InstagramMediaListSchema(Schema):
    page_id = fields.String(required=False)
    instagram_account_id = fields.String(required=False)
    limit = fields.Integer(required=False, load_default=25)

class PinterestAccountConnectionSchema(Schema):
    destination_id = fields.Str(
        required=True,
        error_messages={"required": "Destination ID is required", "invalid": "Invalid Destination"}
    )
    ad_account_id = fields.Str(
        required=True,
        error_messages={"required": "Ad Account ID is required", "invalid": "Invalid DesAd Account ID"}
    )
   











