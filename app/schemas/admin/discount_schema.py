# schemas/discount_schema.py

from marshmallow import Schema, fields, validate, validates, ValidationError
from datetime import datetime


def validate_date_format(value):
    """Validate ISO date format (YYYY-MM-DD or ISO datetime)."""
    if not value:
        return True
    
    try:
        # Try parsing as datetime
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except (ValueError, AttributeError):
        raise ValidationError("Invalid date format. Use ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")


def validate_discount_amount(value):
    """Validate discount amount is positive."""
    if value is not None and value < 0:
        raise ValidationError("Discount amount must be positive")
    return True


def validate_percentage(value):
    """Validate percentage is between 0 and 100."""
    if value is not None and (value < 0 or value > 100):
        raise ValidationError("Percentage must be between 0 and 100")
    return True


class DiscountSchema(Schema):
    """Schema for Discount validation."""
    
    # Core fields
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=100),
        error_messages={
            "required": "Discount name is required",
            "invalid": "Discount name must be a string"
        }
    )
    
    discount_type = fields.Str(
        required=True,
        validate=validate.OneOf(
            ["percentage", "fixed_amount", "buy_x_get_y"],
            error="Discount type must be 'percentage', 'fixed_amount', or 'buy_x_get_y'"
        ),
        error_messages={
            "required": "Discount type is required"
        }
    )
    
    discount_amount = fields.Float(
        required=True,
        validate=validate_discount_amount,
        error_messages={
            "required": "Discount amount is required",
            "invalid": "Discount amount must be a number"
        }
    )
    
    # Scope
    scope = fields.Str(
        required=False,
        validate=validate.OneOf(
            ["product", "category", "cart"],
            error="Scope must be 'product', 'category', or 'cart'"
        ),
        load_default="cart",
        dump_default="cart"
    )
    
    # Coupon code
    code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=3, max=20),
        error_messages={
            "invalid": "Coupon code must be between 3 and 20 characters"
        }
    )
    
    # Product/Category targeting
    product_ids = fields.List(
        fields.Str(),
        required=False,
        allow_none=True,
        load_default=[]
    )
    
    category_names = fields.List(
        fields.Str(),
        required=False,
        allow_none=True,
        load_default=[]
    )
    
    # Location/Outlet
    location = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=100)
    )
    
    outlet_ids = fields.List(
        fields.Str(),
        required=False,
        allow_none=True,
        load_default=[]
    )
    
    # Validation rules
    minimum_purchase = fields.Float(
        required=False,
        allow_none=True,
        validate=lambda x: x >= 0 if x is not None else True,
        error_messages={
            "invalid": "Minimum purchase must be a positive number"
        }
    )
    
    maximum_discount = fields.Float(
        required=False,
        allow_none=True,
        validate=lambda x: x >= 0 if x is not None else True,
        error_messages={
            "invalid": "Maximum discount must be a positive number"
        }
    )
    
    # Date range
    start_date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format,
        error_messages={
            "invalid": "Invalid start date format"
        }
    )
    
    end_date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format,
        error_messages={
            "invalid": "Invalid end date format"
        }
    )
    
    # Usage limits
    max_uses = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x is not None else True,
        error_messages={
            "invalid": "Maximum uses must be a positive integer"
        }
    )
    
    max_uses_per_customer = fields.Int(
        required=False,
        allow_none=True,
        validate=lambda x: x > 0 if x is not None else True,
        error_messages={
            "invalid": "Maximum uses per customer must be a positive integer"
        }
    )
    
    current_uses = fields.Int(
        required=False,
        dump_only=True,
        load_default=0
    )
    
    # Priority
    priority = fields.Int(
        required=False,
        allow_none=True,
        load_default=0,
        validate=lambda x: x >= 0 if x is not None else True
    )
    
    # Legacy fields (for backward compatibility)
    selling_price_group_id = fields.Str(
        required=False,
        allow_none=True
    )
    
    apply_in_customer_groups = fields.Int(
        required=False,
        load_default=0
    )
    
    # Status
    status = fields.Str(
        required=False,
        validate=validate.OneOf(
            ["Active", "Inactive", "Expired"],
            error="Status must be 'Active', 'Inactive', or 'Expired'"
        ),
        load_default="Active",
        dump_default="Active"
    )
    
    # Description (optional)
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(max=500),
        error_messages={
            "invalid": "Description must not exceed 500 characters"
        }
    )
    
    # Timestamps (dump only - set by backend)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    
    # Custom validations
    @validates('discount_amount')
    def validate_discount_amount_by_type(self, value):
        """Validate discount amount based on discount type."""
        discount_type = self.context.get('discount_type')
        
        if discount_type == 'percentage' and value > 100:
            raise ValidationError("Percentage discount cannot exceed 100")
        
        if value <= 0:
            raise ValidationError("Discount amount must be greater than 0")
    
    @validates('end_date')
    def validate_end_date_after_start(self, value):
        """Ensure end_date is after start_date."""
        start_date = self.context.get('start_date')
        
        if value and start_date:
            try:
                start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                end = datetime.fromisoformat(value.replace('Z', '+00:00'))
                
                if end <= start:
                    raise ValidationError("End date must be after start date")
            except (ValueError, AttributeError):
                pass  # Date format validation handled elsewhere


class DiscountUpdateSchema(Schema):
    """Schema for updating discounts (all fields optional)."""
    
    name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=100)
    )
    
    discount_type = fields.Str(
        required=False,
        validate=validate.OneOf(["percentage", "fixed_amount", "buy_x_get_y"])
    )
    
    discount_amount = fields.Float(
        required=False,
        validate=validate_discount_amount
    )
    
    scope = fields.Str(
        required=False,
        validate=validate.OneOf(["product", "category", "cart"])
    )
    
    code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=3, max=20)
    )
    
    product_ids = fields.List(fields.Str(), required=False)
    category_names = fields.List(fields.Str(), required=False)
    location = fields.Str(required=False, allow_none=True)
    outlet_ids = fields.List(fields.Str(), required=False)
    
    minimum_purchase = fields.Float(required=False, allow_none=True)
    maximum_discount = fields.Float(required=False, allow_none=True)
    
    start_date = fields.Str(required=False, allow_none=True, validate=validate_date_format)
    end_date = fields.Str(required=False, allow_none=True, validate=validate_date_format)
    
    max_uses = fields.Int(required=False, allow_none=True)
    max_uses_per_customer = fields.Int(required=False, allow_none=True)
    
    priority = fields.Int(required=False, allow_none=True)
    status = fields.Str(required=False, validate=validate.OneOf(["Active", "Inactive", "Expired"]))
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=500))
    
    updated_at = fields.DateTime(dump_only=True)