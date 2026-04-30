# schemas/payment_schema.py

from marshmallow import Schema, fields, validate, validates, ValidationError
from ...constants.payment_methods import get_all_payment_methods
from ...utils.validation import validate_objectid

from marshmallow import Schema, fields, validate, validates_schema, ValidationError, EXCLUDE
from ...utils.validation import validate_objectid


class InitiatePaymentSchema(Schema):
    """Schema for initiating a payment."""

    class Meta:
        unknown = EXCLUDE

    tenant_id = fields.Int(
        required=True,
        error_messages={"required": "Tenant ID is required"},
    )
    
    provider = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(["paystack", "hubtel", "asoriba", "flutterwave", "mpesa", "stripe", "paypal"])
    )

    branch_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid]
    )

    purchase_type = fields.Str(
        load_default="subscription",
        validate=validate.OneOf(["subscription", "storage_addon"]),
        error_messages={"invalid": "purchase_type must be either 'subscription' or 'storage_addon'"},
    )

    # Subscription purchase
    package_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
    )
    addon_users = fields.Int(
        required=False,
        allow_none=True,
        load_default=0,
    )

    # Storage addon purchase
    storage_addon_gb = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.OneOf([5, 10, 25, 50, 100]),
    )

    return_url = fields.Str(
        required=False,
        error_messages={"required": "Return URL is required"},
    )

    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(["monthly", "quarterly", "yearly", "lifetime"]),
    )

    # Discount code
    discount_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=3, max=30),
    )

    # Customer details
    customer_phone = fields.Str(required=False, allow_none=True)
    customer_email = fields.Email(required=False, allow_none=True)
    customer_name = fields.Str(required=False, allow_none=True)

    # URLs
    callback_url = fields.Url(required=False, allow_none=True)
    redirect_url = fields.Url(required=False, allow_none=True)

    # Additional metadata
    metadata = fields.Dict(required=False, load_default={})
    notes = fields.Str(required=False, allow_none=True)

    @validates_schema
    def validate_purchase_type_requirements(self, data, **kwargs):
        purchase_type = data.get("purchase_type", "subscription")
        billing_period = data.get("billing_period")
        addon_users = data.get("addon_users")

        if addon_users is not None and addon_users < 0:
            raise ValidationError(
                {"addon_users": ["addon_users cannot be less than 0."]}
            )

        if purchase_type == "subscription":
            if not data.get("package_id"):
                raise ValidationError(
                    {"package_id": ["package_id is required when purchase_type is 'subscription'."]}
                )

            if data.get("storage_addon_gb") is not None:
                raise ValidationError(
                    {"storage_addon_gb": ["storage_addon_gb is not allowed when purchase_type is 'subscription'."]}
                )

        elif purchase_type == "storage_addon":
            if not data.get("storage_addon_gb"):
                raise ValidationError(
                    {"storage_addon_gb": ["storage_addon_gb is required when purchase_type is 'storage_addon'."]}
                )

            if data.get("package_id"):
                raise ValidationError(
                    {"package_id": ["package_id is not allowed when purchase_type is 'storage_addon'."]}
                )

            if addon_users not in (None, 0):
                raise ValidationError(
                    {"addon_users": ["addon_users is not applicable to storage_addon purchases."]}
                )

            if billing_period not in ["monthly", "yearly"]:
                raise ValidationError(
                    {"billing_period": ["billing_period for storage_addon must be either 'monthly' or 'yearly'."]}
                )

class ExecutePaymentSchema(Schema):
    """Schema for initiating a payment."""
    
    checksum = fields.Str(
        required=True,
        error_messages={"required": "Checksum is required"}
    )
    provider = fields.Str(required=False, allow_none=True)
    branch_id = fields.Str(required=False, allow_none=True)
    metadata = fields.Dict(required=False, load_default={})
    
    
class InitiatePaymentPlanChangeSchema(Schema):
    """Schema for initiating a payment."""
    
    old_package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Old Package ID is required"}
    )
    
    new_package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "New Package ID is required"}
    )
    
    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(["monthly", "quarterly", "yearly", "lifetime"])
    )
    
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(get_all_payment_methods()),
        error_messages={"required": "Payment method is required"}
    )
    
    # Customer details (required for some gateways)
    customer_phone = fields.Str(required=False, allow_none=True)
    customer_email = fields.Email(required=False, allow_none=True)
    customer_name = fields.Str(required=False, allow_none=True)
    
    # URLs
    callback_url = fields.Url(required=False, allow_none=True)
    redirect_url = fields.Url(required=False, allow_none=True)
    
    # Additional metadata
    metadata = fields.Dict(required=False, load_default={})
    notes = fields.Str(required=False, allow_none=True)


class VerifyPaymentSchema(Schema):
    """Schema for verifying payment status."""
    
    payment_id = fields.Str(required=False, allow_none=True)
    checkout_request_id = fields.Str(required=False, allow_none=True)
    gateway_transaction_id = fields.Str(required=False, allow_none=True)
    
    @validates('payment_id')
    def validate_at_least_one(self, value):
        """Ensure at least one identifier is provided."""
        # This will be checked in the resource
        pass


class ManualPaymentSchema(Schema):
    """Schema for manual payment confirmation (admin only)."""
    
    package_id = fields.Str(
        required=True,
        error_messages={"required": "Package ID is required"}
    )
    
    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(["monthly", "quarterly", "yearly", "lifetime"])
    )
    
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(get_all_payment_methods())
    )
    
    payment_reference = fields.Str(
        required=True,
        error_messages={"required": "Payment reference is required"}
    )
    
    amount = fields.Float(
        required=True,
        validate=lambda x: x > 0,
        error_messages={"required": "Amount is required"}
    )
    
    currency = fields.Str(load_default="USD")
    
    customer_phone = fields.Str(required=False, allow_none=True)
    customer_email = fields.Email(required=False, allow_none=True)
    customer_name = fields.Str(required=False, allow_none=True)
    
    notes = fields.Str(required=False, allow_none=True)