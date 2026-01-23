from marshmallow import Schema, fields, validate
from datetime import datetime



# ====================== SCHEMAS ======================

class FinancialReportBaseQuerySchema(Schema):
    """
    Common query params for date-range financial reports.
    """
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(allow_none=True)
    start_date = fields.DateTime(allow_none=True)
    end_date = fields.DateTime(allow_none=True)


class CashFlowReportQuerySchema(Schema):
    """
    Query schema for cash flow report (single date).
    """
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(allow_none=True)
    date = fields.DateTime(allow_none=True)


class ZReportQuerySchema(Schema):
    """
    Query schema for Z-report (end-of-day).
    """
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(required=True)
    date = fields.DateTime(allow_none=True)
    cashier_id = fields.Str(allow_none=True)


class FinancialAnalyticsDashboardQuerySchema(Schema):
    """
    Combined analytics dashboard query.
    """
    business_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(allow_none=True)
    start_date = fields.DateTime(allow_none=True)
    end_date = fields.DateTime(allow_none=True)