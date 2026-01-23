import re
import uuid
from marshmallow import Schema, fields, validate, ValidationError, validates
from werkzeug.datastructures import FileStorage
from datetime import datetime

from ...utils.validation import (
    validate_phone, validate_image, validate_future_on, 
    validate_past_date, validate_date_format, validate_objectid, validate_store_url,
    validate_password
)

def create_permission_fields():
    """
    This function creates a validation rule for permission fields like view, add, edit, and delete.
    Ensures they are either '0' or '1'.
    """
    def permission_validator(value):
        if value not in ['0', '1']:
            raise validate.ValidationError("Permission must be either '0' or '1'.")
        return value
    return permission_validator


class RolesSchema(Schema):
    name = fields.Str(
        required=False,
        allow_none=True,
    )

class RoleAgentSchema(Schema):
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Name is required"}
    )
    
    email = fields.Email(
        required=True,
        validate=validate.Length(min=3, max=60),
        error_messages={"required": "Email is required"}
    )

    # Permission template
    permission_template = {
        "view": "0",
        "add": "0",
        "edit": "0",
        "delete": "0"
    }

    send_money = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    senders = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    beneficiaries = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    notice_boards = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    billpay_services = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    dail_transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    held_transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    check_rate = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    system_users = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    balance = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])

    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"
    )

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class RoleUpdateSchema(Schema):
    role_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Invalid Role ID. Ensure it's a valid Role ID."}
    )
    name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Name is required"}
    )

    # Permission template
    permission_template = {
        "view": "0",
        "add": "0",
        "edit": "0",
        "delete": "0"
    }

    send_money = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    senders = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    beneficiaries = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    notice_boards = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    billpay_services = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    dail_transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    held_transactions = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    check_rate = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    system_users = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
    balance = fields.List(fields.Dict(), required=False, allow_none=True, default=[permission_template])
   
    status = fields.Str(validate=validate.OneOf(["Active", "Inactive"]),default="Active")

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


# -----------------------ROLE-------------------------
# -----------------------EXPENSE SCHEMA-------------------------
class ExpenseSchema(Schema):
    name = fields.Str(
        required=True,
        error_messages={
            "required": "Expense name is required",
        }
    )
    description = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Description is required"}
    )
    category = fields.Str(
        required=False,
        allow_none=True
    )
    date = fields.Str(
        required=True,
        validate=validate_date_format, 
        error_messages={"required": "Date is required", "invalid": "Date is required"}
    )
    amount = fields.Float(
        required=True,
        default=0.0,
        error_messages={"required": "Amount is required", "invalid": "Date is required"}
    )
    status = fields.Str(
        required=True,
        validate=validate.OneOf(["Approved", "Pending"]),
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class ExpenseUpdateSchema(Schema):
    expense_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Expense ID is required", "invalid": "Expense ID "}
    )
    name = fields.Str(
        required=False,
        allow_none=True
    )
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=5, max=255),
    )
    category = fields.Str(
        required=False,
        allow_none=True
    )
    date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format, 
    )
    amount = fields.Float(
        required=True,
        allow_none=True,
        default=0.0,
    )
    status = fields.Str(
        required=True,
        validate=validate.OneOf(["Approved", "Pending"]),
    )
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# -----------------------EXPENSE SCHEMA-------------------------

# -----------------------SYSTEM USER SCHEMA-------------------------
class SystemUserSchema(Schema):

    fullname = fields.Str(
        required=True,
        error_messages={"required": "Full Name is required", "invalid": "Invalid Full Name"}
    )
    
    phone = fields.Str(
        required=True,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )

    email = fields.Email(
        required=True,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )

    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Image must be a valid file"}
    )

    file_path = fields.Str(
        required=False,
        allow_none=True
    )

    role = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Role ID"}
    )

    password = fields.Str(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=100),
        error_messages={"required": "Password is required", "min_length": "Password must be at least 8 characters"}
    )

    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"
    )

    date_of_birth = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_past_date,
        error_messages={"invalid": "Date of Birth"}
    )

    gender = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(["Male", "Female"]),
    )

    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )

    id_type = fields.Str(
        required=False,
        allow_none=True,
    )

    id_number = fields.Str(
        required=False,
        allow_none=True,
    )

    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )

    last_logged_in = fields.DateTime(required=False)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SystemUserUpdateSchema(Schema):

    system_user_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "System User ID is required", "invalid": "Invalid System User ID"}
    )
    fullname = fields.Str(
        required=False,
        allow_none=True
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"invalid": "Invalid phone number"}
    )

    email = fields.Email(
        required=False,
        allow_none=True,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )

    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Image must be a valid file"}
    )

    file_path = fields.Str(
        required=False,
        allow_none=True
    )

    role = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Role ID"}
    )
    
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"
    )

    date_of_birth = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_past_date,
        error_messages={"invalid": "Date of Birth"}
    )

    gender = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(["Male", "Female"]),
    )

    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )

    id_type = fields.Str(
        required=False,
        allow_none=True,
    )

    id_number = fields.Str(
        required=False,
        allow_none=True,
    )

    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )

    last_logged_in = fields.DateTime(required=False)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# -----------------------SYSTEM USER SCHEMA-------------------------


# Business ID Query
class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(
        required=True,
        validate=validate_objectid,
        description="The business_id of the store to fetch details."
    )

# Business ID Query
class AgentIdQuerySchema(Schema):
    agent_id = fields.Str(
        required=True,
        validate=validate_objectid,
        description="The agent_id of the item to fetch details."
    )
    
class AgentsQuerySchema(Schema):
    agent_id = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_objectid,
    )

class RoleIdQuerySchema(Schema):
    role_id = fields.Str(
        required=True,
        validate=validate_objectid,
        description="The role_id of the role to fetch details."
    )
    
class ExpensesSchema(Schema):
    page = fields.Int(
        required=False,
        all_null=True
    )
    per_page = fields.Int(
        required=False,
        all_null=True
    )
   
# Expense ID Query
class ExpenseIdQuerySchema(Schema):
    expense_id = fields.Str(
        required=True,
        validate=validate_objectid, 
        description="Expense ID of the Expense to fetch detail."
    )

# System User ID
class SystemAdminIdQuerySchema(Schema):
    admin_id = fields.Str(required=True, validate=validate_objectid, description="Admin ID of the User to fetch detail.")


class SystemUserIdQuerySchema(Schema):
    system_user_id = fields.Str(required=True, validate=validate_objectid, description="System User ID of the System User to fetch detail.")
