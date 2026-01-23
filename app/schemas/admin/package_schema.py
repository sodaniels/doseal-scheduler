# schemas/admin/package_schema.py

from marshmallow import Schema, fields, validate
from ...utils.validation import  validate_objectid
from ...constants.payment_methods import PAYMENT_METHODS, get_all_payment_methods




class PackageSchema(Schema):
    """Schema for Package validation."""
    
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"required": "Package name is required"}
    )
    
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=500)
    )
    
    tier = fields.Str(
        required=True,
        validate=validate.OneOf([
            "Free", "Starter", "Professional", "Enterprise", "Custom"
        ]),
        error_messages={"required": "Package tier is required"}
    )
    
    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf([
            "monthly", "quarterly", "yearly", "lifetime"
        ]),
        error_messages={"required": "Billing period is required"}
    )
    
    price = fields.Float(
        required=True,
        validate=lambda x: x >= 0,
        error_messages={"required": "Price is required"}
    )
    
    currency = fields.Str(
        load_default="USD",
        validate=validate.Length(equal=3)
    )
    
    setup_fee = fields.Float(
        load_default=0.0,
        validate=lambda x: x >= 0
    )
    
    trial_days = fields.Int(
        load_default=0,
        validate=lambda x: x >= 0
    )
    
    max_users = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_outlets = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_products = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_transactions_per_month = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    storage_limit_gb = fields.Float(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    
    features = fields.Dict(required=False, load_default={})
    
    is_popular = fields.Bool(load_default=False)
    display_order = fields.Int(load_default=0)
    
    status = fields.Str(
        load_default="Active",
        validate=validate.OneOf(["Active", "Inactive", "Deprecated"])
    )

class PackageUpdateSchema(Schema):
    """Schema for Package validation."""
    package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Package ID is required", "invalid": "Invalid Package ID"}
    )
    
    name = fields.Str(
        required=False,
        allow_none=True
    )
    
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=500)
    )
    
    tier = fields.Str(
        required=False,
        allow_none=True
    )
    
    billing_period = fields.Str(
        required=False,
        allow_none=True
    )
    
    price = fields.Float(
        required=False,
        allow_none=True
    )
    
    currency = fields.Str(
        required=False,
        allow_none=True
    )
    
    setup_fee = fields.Float(
        load_default=0.0,
        validate=lambda x: x >= 0
    )
    
    trial_days = fields.Int(
        load_default=0,
        validate=lambda x: x >= 0
    )
    
    max_users = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_outlets = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_products = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    max_transactions_per_month = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    storage_limit_gb = fields.Float(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    
    features = fields.Dict(required=False, load_default={})
    
    is_popular = fields.Bool(load_default=False)
    display_order = fields.Int(load_default=0)
    
    status = fields.Str(
        load_default="Active",
        validate=validate.OneOf(["Active", "Inactive", "Deprecated"])
    )

class PackageQuerySchema(Schema):
    """Schema for Package validation."""
    package_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Package ID is required", "invalid": "Invalid Package ID"}
    )
    

class SubscriptionSchema(Schema):
    """Schema for Subscription validation."""
    
    package_id = fields.Str(
        required=True,
        error_messages={"required": "Package ID is required"}
    )
    
    billing_period = fields.Str(
        required=True,
        validate=validate.OneOf(["monthly", "quarterly", "yearly", "lifetime"])
    )
    
    payment_method = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(get_all_payment_methods())
    )
    
    payment_reference = fields.Str(required=False, allow_none=True)
    auto_renew = fields.Bool(load_default=True)



class CancelSubscriptionSchema(Schema):
    """Schema for subscription cancellation."""
    
    reason = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=500)
    )