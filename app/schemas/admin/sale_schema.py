from marshmallow import Schema, fields, validate

class CartLineSchema(Schema):
    """Individual line item in the cart."""
    
    product_id = fields.Str(required=True)
    product_name = fields.Str(required=True)
    sku = fields.Str(allow_none=True)
    category = fields.Str(required=True)
    
    quantity = fields.Float(required=True, validate=validate.Range(min=0.001))
    unit_price = fields.Float(required=True, validate=validate.Range(min=0))
    unit_cost = fields.Float(required=True, validate=validate.Range(min=0))
    
    tax_rate = fields.Float(required=True, validate=validate.Range(min=0, max=1))
    tax_amount = fields.Float(required=True, validate=validate.Range(min=0))
    
    discount_amount = fields.Float(load_default=0, validate=validate.Range(min=0))
    
    subtotal = fields.Float(required=True, validate=validate.Range(min=0))
    line_total = fields.Float(required=True, validate=validate.Range(min=0))


class CartTotalsSchema(Schema):
    """Cart totals aggregation."""
    
    subtotal = fields.Float(required=True, validate=validate.Range(min=0))
    total_discount = fields.Float(required=True, validate=validate.Range(min=0))
    total_tax = fields.Float(required=True, validate=validate.Range(min=0))
    total_cost = fields.Float(required=True, validate=validate.Range(min=0))
    grand_total = fields.Float(required=True, validate=validate.Range(min=0))


class CartSchema(Schema):
    """Complete cart structure."""
    
    lines = fields.List(fields.Nested(CartLineSchema), required=True, validate=validate.Length(min=1))
    totals = fields.Nested(CartTotalsSchema, required=True)


class SaleSchema(Schema):
    """Complete sale/checkout schema."""
    
    # CORE - REQUIRED
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(required=True)
    transaction_number = fields.Str(allow_none=True)
    cashier_id = fields.Str(allow_none=True)
    
    status = fields.Str(
        load_default="Completed",
        validate=validate.OneOf(["Completed", "Pending", "Voided", "Refunded", "Partially_Refunded", "Failed"])
    )
    
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(["Cash", "Card", "Mobile_Money", "Bank_Transfer", "Credit", "Gift_Card", "Mixed"])
    )
    
    amount_paid = fields.Float(allow_none=True, validate=validate.Range(min=0))
    
    # CUSTOMER - OPTIONAL
    customer_id = fields.Str(allow_none=True)
    
    # CART - REQUIRED
    cart = fields.Nested(CartSchema, required=True)
    
    # TRACKING - OPTIONAL
    receipt_number = fields.Str(allow_none=True)
    cash_session_id = fields.Str(allow_none=True)
    device_id = fields.Str(allow_none=True)
    
    # REFUND/VOID - CONDITIONAL
    refund_reason = fields.Str(allow_none=True)
    void_reason = fields.Str(allow_none=True)
    authorized_by = fields.Str(allow_none=True)
    
    # DISCOUNT - OPTIONAL
    discount_type = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["Percentage", "Fixed_Amount", "Promotional", "Coupon", "Loyalty"])
    )
    promotion_id = fields.Str(allow_none=True)
    coupon_code = fields.Str(allow_none=True)
    
    # METADATA
    notes = fields.Str(allow_none=True)
    
    # TIMESTAMPS
    created_at = fields.DateTime(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)

class CartPreviewItemSchema(Schema):
    product_id = fields.Str(required=True)
    quantity = fields.Float(required=True, validate=validate.Range(min=0.001))


class CartPreviewRequestSchema(Schema):
    business_id = fields.Str(allow_none=True)  # optional, for SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    customer_id = fields.Str(allow_none=True)
    payment_method = fields.Str(required=True)
    amount_paid = fields.Float(required=True)
    device_id = fields.Str(required=True)
    notes = fields.Str(allow_none=True)
    coupon_code = fields.Str(allow_none=True)
    items = fields.List(fields.Nested(CartPreviewItemSchema), required=True, validate=validate.Length(min=1))


class CartExecuteRequestSchema(Schema):
    checksum = fields.Str(
        required=True,
    )
    device_id = fields.Str(required=True)



















