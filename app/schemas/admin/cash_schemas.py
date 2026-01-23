# schemas/cash_schemas.py
from marshmallow import Schema, fields, validate


class OpenSessionSchema(Schema):
    """Schema for opening a cash session."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    opening_float = fields.Float(required=True, validate=validate.Range(min=0))
    notes = fields.Str(allow_none=True, validate=validate.Length(max=500))


class CloseSessionSchema(Schema):
    """Schema for closing a cash session."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    session_id = fields.Str(required=True)
    actual_balance = fields.Float(required=True, validate=validate.Range(min=0))
    notes = fields.Str(allow_none=True, validate=validate.Length(max=500))


class CashMovementSchema(Schema):
    """Schema for recording cash movement."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    session_id = fields.Str(required=True)
    outlet_id = fields.Str(required=True)
    movement_type = fields.Str(required=True, validate=validate.OneOf(["IN", "OUT"]))
    amount = fields.Float(required=True, validate=validate.Range(min=0.01))
    reason = fields.Str(
        required=True,
        validate=validate.OneOf([
            "Bank_Deposit",
            "Bank_Withdrawal",
            "Petty_Cash",
            "Expense_Payment",
            "Float_Adjustment",
            "Correction",
            "Other"
        ])
    )
    notes = fields.Str(allow_none=True, validate=validate.Length(max=500))


class SessionIdQuerySchema(Schema):
    """Query schema for session operations."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    session_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(allow_none=True)


class SessionsListQuerySchema(Schema):
    """Query schema for listing sessions."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(required=True)
    status = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["Open", "Closed", "Reconciled"])
    )
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class MovementsListQuerySchema(Schema):
    """Query schema for listing movements."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    session_id = fields.Str(allow_none=True)
    outlet_id = fields.Str(allow_none=True)
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)