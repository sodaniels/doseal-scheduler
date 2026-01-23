from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from enum import Enum
from ...utils.validation import validate_objectid

# --- Payment Status Enum ---
class PaymentStatus(str, Enum):
    """
    Enumeration of possible statuses for a scheduled payable.
    """
    PENDING = "pending"        # created, waiting for scheduling
    SCHEDULED = "scheduled"    # has due date & reminders configured
    NOTIFIED = "notified"      # reminder(s) already sent
    COMPLETED = "completed"    # payment made
    CANCELLED = "cancelled"    # cancelled by admin
    OVERDUE = "overdue"        # past due, unpaid

class PayableNextJobsSchema(Schema):
    include_payable = fields.Str(
        required=False,
        allow_none=True
    )
    limit = fields.Int(
        required=False,
        allow_none=True
    )
    only_future = fields.Str(
        required=False,
        allow_none=True
    )
    
    


# --- Payable Schema ---
class PayableSchema(Schema):
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=120),
        error_messages={"required": "Name is required"}
    )

    reference = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"required": "Reference is required"}
    )

    # 3-letter ISO currency code, e.g., GHS, USD, NGN
    currency = fields.Str(
        required=True,
        validate=validate.Length(equal=3),
        error_messages={"required": "Currency is required"}
    )

    # Example input: "2025-09-25T12:00:00Z"
    due_at = fields.Str(
        required=True,
        error_messages={"required": "Due Date is required"}
    )

    # Offsets (days before due_at when reminders fire), e.g., [7, 2]
    reminder_offsets_days = fields.List(
        fields.Integer(validate=validate.Range(min=0, max=365)),
        required=True,
        error_messages={"required": "Reminder offsets are required"}
    )

    amount = fields.Float(
        required=True,
    )

    # Who created this payable (user id, email, or ObjectId as str)
    created_by = fields.Str(
        required=False,
        allow_none=True
    )

    # Default status when created: "pending"
    status = fields.Str(
        required=False,
        validate=validate.OneOf([s.value for s in PaymentStatus]),
        error_messages={
            "required": "Status is required",
            "invalid": "Invalid status"
        }
    )

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    # --- Custom validations ---
    @validates_schema
    def validate_amount_and_offsets(self, data, **kwargs):
        if "amount" in data and data["amount"] < 0:
            raise ValidationError({"amount": "Amount cannot be negative"})
        if "reminder_offsets_days" in data:
            offs = data["reminder_offsets_days"]
            if len(offs) != len(set(offs)):
                raise ValidationError({"reminder_offsets_days": "Duplicate offsets are not allowed"})

class PayableUpdateSchema(Schema):
    payable_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Payable ID is required", "invalid": "Invalid Payable ID"}
    )
    name = fields.Str(
        required=False,
        allow_none=True
    )

    reference = fields.Str(
        required=False,
        allow_none=True
    )

    currency = fields.Str(
        required=False,
        allow_none=True
    )

    # Example input: "2025-09-25T12:00:00Z"
    due_at = fields.Str(
        required=False,
        allow_none=True
    )

    reminder_offsets_days = fields.List(
        fields.Integer(validate=validate.Range(min=0, max=365)),
        required=False,
    )

    amount = fields.Float(
        required=False,
        allow_none=True
    )

    # Who created this payable (user id, email, or ObjectId as str)
    created_by = fields.Str(
        required=False,
        allow_none=True
    )

    # Default status when created: "pending"
    status = fields.Str(
        required=False,
        allow_none=True
    )

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class PayableWindowSchema(Schema):
    start_date = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=120),
        error_messages={"required": "Start Date is required"}
    )
    end_date = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=120),
        error_messages={"required": "End Date is required"}
    )
    
    limit = fields.Str(
        required=None,
        allow_none=True
    )
    
    include_payable = fields.Str(
        required=None,
        allow_none=True
    )
    

class PayableIDQuerySchema(Schema):
    payable_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=120),
        error_messages={"required": "Payable ID is required"}
    )













