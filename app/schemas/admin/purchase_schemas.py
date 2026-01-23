# schemas/purchase_schemas.py
from marshmallow import Schema, fields, validate


class OrderedItemSchema(Schema):
    """Schema for an item in a purchase order."""
    product_id = fields.Str(required=True)
    composite_variant_id = fields.Str(allow_none=True)
    quantity = fields.Float(required=True, validate=validate.Range(min=0.001))
    unit_cost = fields.Float(required=True, validate=validate.Range(min=0))
    line_total = fields.Float(dump_only=True)  # Calculated automatically


class PurchaseOrderCreateSchema(Schema):
    """Schema for creating a purchase order."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    supplier_id = fields.Str(required=True)
    ordered_items = fields.List(
        fields.Nested(OrderedItemSchema),
        required=True,
        validate=validate.Length(min=1)
    )
    expected_date = fields.DateTime(allow_none=True)
    notes = fields.Str(allow_none=True, validate=validate.Length(max=1000))


class PurchaseOrderUpdateSchema(Schema):
    """Schema for updating a purchase order (only in Draft status)."""
    po_id = fields.Str(required=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    ordered_items = fields.List(
        fields.Nested(OrderedItemSchema),
        allow_none=True
    )
    expected_date = fields.DateTime(allow_none=True)
    notes = fields.Str(allow_none=True, validate=validate.Length(max=1000))


class PurchaseOrderIdQuerySchema(Schema):
    """Query schema for PO operations requiring ID."""
    po_id = fields.Str(required=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    reason = fields.Str(allow_none=True)  # For cancellation


class PurchaseOrdersListQuerySchema(Schema):
    """Query schema for listing purchase orders."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    status = fields.Str(
        allow_none=True,
        validate=validate.OneOf([
            "Draft", "Issued", "Partially_Received", "Completed", "Cancelled"
        ])
    )
    supplier_id = fields.Str(allow_none=True)
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class ReceivedItemSchema(Schema):
    """Schema for an item being received."""
    product_id = fields.Str(required=True)
    composite_variant_id = fields.Str(allow_none=True)
    quantity_received = fields.Float(required=True, validate=validate.Range(min=0.001))


class ReceiveStockSchema(Schema):
    """Schema for receiving stock against a PO."""
    po_id = fields.Str(required=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    received_items = fields.List(
        fields.Nested(ReceivedItemSchema),
        required=True,
        validate=validate.Length(min=1)
    )
    receive_note = fields.Str(allow_none=True, validate=validate.Length(max=500))