# schemas/payment_schema.py

from marshmallow import Schema, fields, validate, validates, ValidationError
from ...constants.payment_methods import get_all_payment_methods


class InitiatePaymentSchema(Schema):
    """Schema for initiating a payment."""
    
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