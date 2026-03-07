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
   
class PublicIdSchema(Schema):
    public_id = fields.Str(
        required=True,
        error_messages={"required": "Public ID is required", "invalid": "Invalid Public ID"}
    )


# =========================================
# CONNECT AD ACCOUNT
# =========================================
class TikTokAdAccountConnectSchema(Schema):
    advertiser_id = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=50),
        metadata={"description": "TikTok advertiser ID"}
    )


# =========================================
# BOOST VIDEO (SPARK AD)
# =========================================
class TikTokBoostVideoSchema(Schema):

    advertiser_id = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=50),
    )

    spark_ad_auth_code = fields.Str(
        required=True,
        validate=validate.Length(min=10),
    )

    # 💰 Use Decimal for money (NOT Float)
    daily_budget_usd = fields.Decimal(
        required=True,
        as_string=True,
        validate=validate.Range(min=1),
        metadata={"description": "Daily budget in USD"}
    )

    duration_days = fields.Int(
        required=True,
        validate=validate.Range(min=1, max=365),
    )

    objective = fields.Str(
        load_default="VIDEO_VIEWS",
        validate=validate.OneOf([
            "VIDEO_VIEWS",
            "CONVERSIONS",
            "TRAFFIC",
            "LEAD_GENERATION",
            "APP_INSTALL",
        ])
    )

    optimization_goal = fields.Str(
        load_default="VIDEO_VIEW",
        validate=validate.OneOf([
            "VIDEO_VIEW",
            "CONVERSION",
            "CLICK",
            "LEAD",
            "APP_INSTALL",
        ])
    )

    placements = fields.List(
        fields.Str(),
        load_default=None
    )

    bid_type = fields.Str(
        load_default="BID_TYPE_NO_BID",
        validate=validate.OneOf([
            "BID_TYPE_NO_BID",
            "BID_TYPE_CUSTOM",
        ])
    )

    bid_usd = fields.Decimal(
        load_default=None,
        as_string=True,
        allow_none=True,
        validate=validate.Range(min=0)
    )

    billing_event = fields.Str(
        load_default="CPM",
        validate=validate.OneOf([
            "CPM",
            "CPC",
            "CPV",
            "OCPM",
        ])
    )

    call_to_action = fields.Str(
        load_default="WATCH_NOW",
        validate=validate.OneOf([
            "WATCH_NOW",
            "SHOP_NOW",
            "LEARN_MORE",
            "SIGN_UP",
            "DOWNLOAD",
            "CONTACT_US",
        ])
    )

    landing_page_url = fields.Url(
        load_default=None,
        allow_none=True
    )

    campaign_name = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=255)
    )

    targeting = fields.Dict(
        load_default=None,
        allow_none=True
    )

    scheduled_post_id = fields.Str(
        load_default=None,
        allow_none=True
    )

    auto_activate = fields.Bool(
        load_default=False
    )

    # =========================================
    # Custom Validation
    # =========================================
    @validates_schema
    def validate_bid_logic(self, data, **kwargs):
        """
        If bid_type is BID_TYPE_CUSTOM,
        bid_usd must be provided.
        """
        if data.get("bid_type") == "BID_TYPE_CUSTOM" and not data.get("bid_usd"):
            raise ValidationError(
                "bid_usd is required when bid_type is BID_TYPE_CUSTOM",
                field_name="bid_usd"
            )

# =========================================
# CONNECT GOOGLE ADS ACCOUNT
# =========================================
class YouTubeAdAccountConnectSchema(Schema):

    customer_id = fields.Str(
        required=True,
        validate=validate.Regexp(
            r"^\d{3}-?\d{3}-?\d{4}$",
            error="Customer ID must be 10 digits (hyphens optional)"
        ),
        metadata={"description": "Google Ads customer ID"}
    )

    manager_customer_id = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Regexp(
            r"^\d{3}-?\d{3}-?\d{4}$",
            error="Manager customer ID must be 10 digits (hyphens optional)"
        )
    )


# =========================================
# BOOST YOUTUBE VIDEO
# =========================================
class YouTubeBoostVideoSchema(Schema):

    customer_id = fields.Str(
        required=True,
        validate=validate.Regexp(r"^\d{3}-?\d{3}-?\d{4}$")
    )

    youtube_video_id = fields.Str(
        required=True,
        validate=validate.Regexp(
            r"^[a-zA-Z0-9_-]{11}$",
            error="Invalid YouTube video ID"
        )
    )

    headline = fields.Str(
        required=True,
        validate=validate.Length(max=30)
    )

    description = fields.Str(
        required=True,
        validate=validate.Length(max=90)
    )

    business_name = fields.Str(
        required=True,
        validate=validate.Length(max=25)
    )

    final_url = fields.Url(
        required=True
    )

    # 💰 Use Decimal for budget (never float)
    daily_budget_usd = fields.Decimal(
        required=True,
        as_string=True,
        validate=validate.Range(min=1)
    )

    duration_days = fields.Int(
        required=True,
        validate=validate.Range(min=1, max=365)
    )

    long_headline = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=90)
    )

    logo_image_url = fields.Url(
        load_default=None,
        allow_none=True
    )

    campaign_name = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=255)
    )

    bidding_strategy = fields.Str(
        load_default="maximizeConversions",
        validate=validate.OneOf([
            "maximizeConversions",
            "targetCpa",
            "maximizeClicks",
            "targetRoas"
        ])
    )

    target_cpa_usd = fields.Decimal(
        load_default=None,
        allow_none=True,
        as_string=True,
        validate=validate.Range(min=0)
    )

    breadcrumb1 = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=15)
    )

    breadcrumb2 = fields.Str(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=15)
    )

    targeting = fields.Dict(
        load_default=None,
        allow_none=True
    )

    scheduled_post_id = fields.Str(
        load_default=None,
        allow_none=True
    )

    auto_activate = fields.Bool(load_default=False)

    # =========================================
    # Custom Cross-Field Validation
    # =========================================
    @validates_schema
    def validate_bidding_logic(self, data, **kwargs):
        """
        If bidding_strategy is targetCpa,
        target_cpa_usd must be provided.
        """
        if data.get("bidding_strategy") == "targetCpa" and not data.get("target_cpa_usd"):
            raise ValidationError(
                "target_cpa_usd is required when bidding_strategy is targetCpa",
                field_name="target_cpa_usd"
            )






