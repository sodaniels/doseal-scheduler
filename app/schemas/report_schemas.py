# schemas/report_schemas.py
from marshmallow import Schema, fields, validate
from datetime import datetime


class SalesReportQuerySchema(Schema):
    """Query schema for sales reports."""
    business_id = fields.Str(allow_none=True)
    start_date = fields.DateTime(required=True)
    end_date = fields.DateTime(required=True)
    outlet_id = fields.Str(allow_none=True)
    user_id = fields.Str(allow_none=True)
    limit = fields.Int(allow_none=True, validate=validate.Range(min=1, max=500), dump_default=50)


class InventoryReportQuerySchema(Schema):
    """Query schema for inventory reports."""
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(required=True)
    start_date = fields.DateTime(allow_none=True)
    end_date = fields.DateTime(allow_none=True)
    include_zero_stock = fields.Bool(allow_none=True, dump_default=False)
    

class CustomerReportQuerySchema(Schema):
    """Base schema for customer report queries."""
    business_id = fields.Str(required=False, allow_none=True)
    start_date = fields.DateTime(required=False, allow_none=True)
    end_date = fields.DateTime(required=False, allow_none=True)


class TopCustomersQuerySchema(CustomerReportQuerySchema):
    """Schema for top customers report query parameters."""
    limit = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=500),
        load_default=50
    )

# ===================== Customer =====================

class CustomerPurchaseHistoryQuerySchema(CustomerReportQuerySchema):
    """Schema for customer purchase history query parameters."""
    customer_id = fields.Str(required=True)
    limit = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=500),
        load_default=100
    )


class CustomerSegmentationQuerySchema(Schema):
    """Schema for customer segmentation query parameters."""
    business_id = fields.Str(required=False, allow_none=True)


class CustomerRetentionQuerySchema(Schema):
    """Schema for customer retention query parameters."""
    business_id = fields.Str(required=False, allow_none=True)


class NewVsReturningQuerySchema(CustomerReportQuerySchema):
    """Schema for new vs returning customers query parameters."""
    pass

class PerformanceReportQuerySchema(Schema):
    """
    Query parameters for performance report requests.
    Used for analytics dashboard: outlet, time-based, category, discount, affinity.
    """

    # Role-aware: only SUPER_ADMIN / SYSTEM_OWNER may query another business
    business_id = fields.Str(allow_none=True)

    # Required analytics period
    start_date = fields.Str(
        required=True,
        metadata={"description": "Start date in ISO-8601 format: YYYY-MM-DD"}
    )
    end_date = fields.Str(
        required=True,
        metadata={"description": "End date in ISO-8601 format: YYYY-MM-DD"}
    )

    # Report type selection
    report_type = fields.Str(
        required=True,
        validate=validate.OneOf([
            "outlet",
            "time",
            "category",
            "discount",
            "affinity"
        ]),
        metadata={
            "description": "Type of performance report to generate"
        }
    )

    # Optional outlet filter (for time & category reports)
    outlet_id = fields.Str(
        allow_none=True,
        metadata={
            "description": "Filter by specific outlet ID"
        }
    )


class OperationalReportQuerySchema(Schema):
    """
    Query parameters for operational reports.
    Used for: refunds/returns, voids, ATV, cashier performance.
    """

    # Only SUPER_ADMIN / SYSTEM_OWNER may override business_id
    business_id = fields.Str(allow_none=True)

    # Required reporting period (YYYY-MM-DD)
    start_date = fields.Str(required=True)
    end_date = fields.Str(required=True)

    # Report type selector
    report_type = fields.Str(
        required=True,
        validate=validate.OneOf([
            "refunds_returns",
            "voids",
            "atv",
            "cashier_performance",
        ])
    )

    # Optional outlet filter
    outlet_id = fields.Str(allow_none=True)

class InventoryOptimizationReportQuerySchema(Schema):
    """
    Query parameters for inventory optimization reports.

    report_type:
      - dead_stock
      - stock_turnover
      - stockout
      - abc_analysis
    """

    # Only SUPER_ADMIN / SYSTEM_OWNER may override business_id
    business_id = fields.Str(allow_none=True)

    # Period-based reports (required for all except dead_stock)
    start_date = fields.Str(allow_none=True)  # YYYY-MM-DD
    end_date = fields.Str(allow_none=True)    # YYYY-MM-DD

    # Report selector
    report_type = fields.Str(
        required=True,
        validate=validate.OneOf([
            "dead_stock",
            "stock_turnover",
            "stockout",
            "abc_analysis",
        ])
    )

    # Optional outlet filter
    outlet_id = fields.Str(allow_none=True)

    # Only used for dead_stock
    days_threshold = fields.Int(allow_none=True, validate=validate.Range(min=1))


class DateRangeQuerySchema(Schema):
    """Base schema for date range queries."""
    business_id = fields.Str(required=False, allow_none=True)
    outlet_id = fields.Str(required=False, allow_none=True)
    start_date = fields.DateTime(required=False, allow_none=True)
    end_date = fields.DateTime(required=False, allow_none=True)


class SingleDateQuerySchema(Schema):
    """Schema for single date queries (Z-Report)."""
    business_id = fields.Str(required=False, allow_none=True)
    outlet_id = fields.Str(required=False, allow_none=True)
    date = fields.DateTime(required=False, allow_none=True)


class DeadStockQuerySchema(Schema):
    """Schema for dead stock report."""
    business_id = fields.Str(required=False, allow_none=True)
    outlet_id = fields.Str(required=False, allow_none=True)
    days_threshold = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=365),
        load_default=60
    )


class AffinityQuerySchema(DateRangeQuerySchema):
    """Schema for product affinity analysis."""
    min_support = fields.Float(
        required=False,
        allow_none=True,
        validate=validate.Range(min=0.001, max=1.0),
        load_default=0.01
    )













