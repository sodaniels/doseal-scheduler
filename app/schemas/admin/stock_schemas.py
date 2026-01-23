# schemas/stock_schemas.py
from marshmallow import Schema, fields, validate


class StockHistoryQuerySchema(Schema):
    """Query schema for stock movement history."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    product_id = fields.Str(required=True)
    composite_variant_id = fields.Str(allow_none=True)
    limit = fields.Int(
        allow_none=True,
        validate=validate.Range(min=1, max=500),
        dump_default=100,
        metadata={"description": "Maximum number of history entries to return"}
    )


class StockLevelsQuerySchema(Schema):
    """Query schema for current stock levels."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    filter = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["all", "low_stock", "out_of_stock"]),
        dump_default="all",
        metadata={"description": "Filter stock items by status"}
    )
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class StockDetailQuerySchema(Schema):
    """Query schema for detailed stock information."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    product_id = fields.Str(required=True)
    outlet_id = fields.Str(allow_none=True)
    composite_variant_id = fields.Str(allow_none=True)
    include_all_outlets = fields.Bool(
        allow_none=True,
        dump_default=False,
        metadata={"description": "Include stock levels across all outlets"}
    )


class StockSummaryQuerySchema(Schema):
    """Query schema for stock summary/analytics."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(
        allow_none=True,
        metadata={"description": "Filter to specific outlet, or omit for business-wide summary"}
    )