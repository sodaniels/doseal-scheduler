# schemas/pos_schemas.py
from marshmallow import (
    Schema, fields, validate, validates, ValidationError, validates_schema
)
from marshmallow.validate import Length

from ...utils.validation import validate_objectid


class CartLineSchema(Schema):
    """
    Single line item in the checkout cart.
    Mirrors the enhanced sale.cart.lines structure.
    """
    product_id = fields.Str(required=True)
    product_name = fields.Str(required=True)
    sku = fields.Str(allow_none=True)
    category = fields.Str(allow_none=True)

    quantity = fields.Float(required=True)
    unit_price = fields.Float(required=True)
    unit_cost = fields.Float(allow_none=True)

    # Tax tracking
    tax_rate = fields.Float(allow_none=True)           # e.g. 0.16
    tax_amount = fields.Float(allow_none=True)
    tax_exempt = fields.Bool(missing=False)

    # Line-level discount
    discount_amount = fields.Float(allow_none=True)
    discount_percentage = fields.Float(allow_none=True)

    # Calculated fields (you can treat as optional input or server-computed)
    subtotal = fields.Float(allow_none=True)           # quantity * unit_price
    line_total = fields.Float(allow_none=True)         # subtotal - discount + tax


class CartTotalsSchema(Schema):
    """
    Totals for the checkout cart.
    Mirrors sale.cart.totals in the enhanced schema.
    """
    subtotal = fields.Float(allow_none=True)           # Sum of line subtotals
    total_discount = fields.Float(allow_none=True)     # Sum of all discounts
    total_tax = fields.Float(allow_none=True)          # Sum of all tax_amount
    grand_total = fields.Float(allow_none=True)
    total_cost = fields.Float(allow_none=True)         # Sum of (qty * unit_cost)


class CartSchema(Schema):
    """
    Full cart structure for a checkout.
    """
    lines = fields.List(
        fields.Nested(CartLineSchema),
        required=True,
        validate=Length(min=1),
    )
    totals = fields.Nested(CartTotalsSchema, required=False)


class CheckoutRequestSchema(Schema):
    """
    Request body for creating a checkout / sale.

    This is the *input* schema for the POS checkout endpoint,
    mapped to the enhanced sale document structure.
    """

    # Core identifiers (business_id usually overridden from token
    # except for SUPER_ADMIN / SYSTEM_OWNER)
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(required=True)

    # Optional links
    customer_id = fields.Str(allow_none=True)
    cashier_id = fields.Str(allow_none=True)   # or derive from auth user if you prefer

    # Status & payment
    status = fields.Str(
        allow_none=True,
        validate=validate.OneOf([
            "Completed",
            "Pending",
            "Voided",
            "Refunded",
            "Partially_Refunded",
            "Failed",
        ]),
        metadata={"description": "Sale status. Default is 'Completed' for successful checkout."}
    )

    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf([
            "Cash",
            "Card",
            "Mobile_Money",
            "Bank_Transfer",
            "Credit",
            "Gift_Card",
            "Mixed",
        ]),
        metadata={"description": "Payment method used for this checkout."}
    )
    amount_paid = fields.Float(allow_none=True, validate=validate.Range(min=0))

    # High-level discount metadata
    discount_type = fields.Str(
        allow_none=True,
        validate=validate.OneOf([
            "percentage",
            "fixed_amount",
            "promotional",
            "coupon",
            "loyalty",
        ])
    )
    coupon_code = fields.Str(allow_none=True)
    promotion_id = fields.Str(allow_none=True)

    # Cart (lines + totals)
    cart = fields.Nested(CartSchema, required=True)

    # Metadata / extra fields
    transaction_number = fields.Str(allow_none=True)
    receipt_number = fields.Str(allow_none=True)
    cash_session_id = fields.Str(allow_none=True)
    device_id = fields.Str(allow_none=True)
    notes = fields.Str(allow_none=True)

    # Timestamps (usually server-side; kept as optional/allow_none)
    created_at = fields.DateTime(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)
    
    

class CheckoutLineItemSchema(Schema):
    """Schema for a single line item in checkout request."""
    product_id = fields.Str(required=True)
    product_name = fields.Str(required=True)
    unit_price = fields.Float(required=True, validate=validate.Range(min=0))
    quantity = fields.Float(required=True, validate=validate.Range(min=0.001))
    composite_variant_id = fields.Str(allow_none=True)
    variant_name = fields.Str(allow_none=True)
    tax_rate = fields.Float(allow_none=True, validate=validate.Range(min=0, max=100))
    discount_type = fields.Str(allow_none=True, validate=validate.OneOf(["Fixed", "Percentage"]))
    discount_value = fields.Float(allow_none=True, validate=validate.Range(min=0))


# class CheckoutRequestSchema(Schema):
#     """Schema for POS checkout request."""
#     outlet_id = fields.Str(required=True)
#     lines = fields.List(fields.Nested(CheckoutLineItemSchema), required=True, validate=validate.Length(min=1))
#     customer_id = fields.Str(allow_none=True)
#     payment_method = fields.Str(
#         required=True,
#         validate=validate.OneOf(["Cash", "Card", "Mobile_Money", "Bank_Transfer", "Credit", "Gift_Card", "Mixed"])
#     )
#     amount_paid = fields.Float(allow_none=True, validate=validate.Range(min=0))
#     reference_note = fields.Str(allow_none=True)
#     business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class CheckoutQuerySchema(Schema):
    """Query parameters for checkout (role-aware)."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    


class VoidSaleRequestSchema(Schema):
    """Schema for voiding a sale."""
    sale_id = fields.Str(required=True)
    reason = fields.Str(allow_none=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class VoidSaleQuerySchema(Schema):
    """Query parameters for void sale."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class SaleIdQuerySchema(Schema):
    """Query schema for fetching a single sale."""
    sale_id = fields.Str(required=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class SalesListQuerySchema(Schema):
    """Query schema for listing sales."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Outlet ID is required", "invalid": "Invalid Outlet ID"}
    )
    status = fields.Str(allow_none=True, validate=validate.OneOf([
        "Completed", "Pending", "Voided", "Refunded", "Partially_Refunded"
    ]))
    page = fields.Int(allow_none=True, validate=validate.Range(min=1))
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100))


class StockAdjustmentSchema(Schema):
    """Schema for manual stock adjustments."""
    outlet_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Outlet ID is required", "invalid": "Invalid Outlet ID"}
    )
    product_id = fields.Str(required=True)
    composite_variant_id = fields.Str(allow_none=True)
    quantity = fields.Float(required=True)  # Positive for increase, negative for decrease
    adjustment_type = fields.Str(
        required=True,
        validate=validate.OneOf(["OPENING_STOCK", "ADJUSTMENT", "DAMAGE", "TRANSFER_IN", "TRANSFER_OUT"])
    )
    note = fields.Str(allow_none=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class StockQuerySchema(Schema):
    """Query schema for stock inquiries."""
    outlet_id = fields.Str(required=True)
    product_id = fields.Str(required=True)
    composite_variant_id = fields.Str(allow_none=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    

class StockTransferSchema(Schema):
    """Schema for stock transfer between outlets."""
    from_outlet_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "From Outlet ID is required", "invalid": "Invalid From Outlet ID"}
    )
    to_outlet_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "To Outlet ID is required", "invalid": "Invalid To Outlet ID"}
    )
    product_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Product ID is required", "invalid": "Invalid Product ID"}
    )
    composite_variant_id = fields.Str(allow_none=True)
    quantity = fields.Float(required=True)  # Always positive for transfers
    note = fields.Str(allow_none=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER

    @validates_schema
    def validate_outlets_and_quantity(self, data, **kwargs):
        # Ensure source and destination outlets are different
        if data.get("from_outlet_id") == data.get("to_outlet_id"):
            raise ValidationError(
                "from_outlet_id and to_outlet_id must be different.",
                field_name="to_outlet_id"
            )

        # Ensure quantity is positive
        qty = data.get("quantity")
        if qty is None or qty <= 0:
            raise ValidationError(
                "quantity must be a positive number.",
                field_name="quantity"
            )





