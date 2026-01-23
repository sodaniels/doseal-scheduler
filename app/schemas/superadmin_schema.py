import re
import uuid
from marshmallow import Schema, fields, validate, ValidationError, validates
from werkzeug.datastructures import FileStorage
from datetime import datetime

from ..utils.validation import (
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


# -----------------------BUSINESSE-------------------------
class BusinessSchema(Schema):
    
    business_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=200), 
        error_messages={"invalid": "Company name is required"}
    )
    start_date = fields.Str(
        required=True,
        validate=validate_date_format, 
        error_messages={"required": "Start date is required", "invalid": "Start date is required"}
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Image must be a valid file"}
    )
    business_contact = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Business Contact"}
    )
    country = fields.Str(
        required=True, 
        error_messages={"required": "Country is required", "invalid": "Country is required"}
    )
    city = fields.Str(
        required=True, 
        error_messages={"required": "City is required", "invalid": "City is required"}
    )
    state = fields.Str(
        required=True, 
        error_messages={"required": "State is required", "invalid": "State is required"}
    )
    postcode = fields.Str(
        required=True, 
        error_messages={"required": "Post Code is required", "invalid": "Post Code is required"}
    )
    landmark = fields.Str(
        required=False, 
        allow_none=True,
    )
    currency = fields.Str(
        required=True, 
        error_messages={"required": "Currency is required", "invalid": "Currency is required"}
    )
    website = fields.Str(
        required=False, 
        allow_none=True,
    )
    alternate_contact_number = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Contact Number"}
    )
    time_zone = fields.Str(
        required=True,
        error_messages={"required": "Time zone is required", "invalid": "Time zone is required"}
    )
    
    prefix = fields.Str(
        required=False, 
        error_messages={"required": "Prefix is required", "invalid": "Prefix is required"}
    )
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "First name is required", "null": "First name cannot be null"}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Last name is required", "null": "Last name cannot be null"}
    )
    username = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Username is required", "null": "Username cannot be null"}
    )
    password = fields.Str(
        required=True,
        load_only=True,
        validate=validate_password,
        error_messages={"required": "Password is required"},
    )
    email = fields.Email(
        required=True, 
        validate=validate.Length(min=5, max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    store_url = fields.Str(
        required=True,
        validate=validate_store_url,
        error_messages={"invalid": "Please provide a valid store URL. Minimum of 5 characters, all lowercase, no spaces, no special characters."}
    )
    package = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=30),
        error_messages={"required": "Package is required", "invalid": "Package is invalid"}
    )
    user_id = fields.Str(
        required=False,
        allow_none=True,
    )
    return_url = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=200),
        error_messages={"required": "Return URL is required", "invalid": "Return URL is invalid"}
    )
    callback_url = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=200),
        error_messages={"required": "Callback URL is required", "invalid": "Callback URL is invalid"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class BusinessUpdateSchema(Schema):
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID. Ensure it's a valid. Ensure you add a valid business ID."}
    )
    
    business_name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=200), 
        error_messages={"invalid": "Company name is required"}
    )
    start_date = fields.Str(
        required=False,
        validate=validate_date_format, 
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Image must be a valid file"}
    )
    business_contact = fields.Str(
        required=False,
        validate=validate_phone, 
    )
    country = fields.Str(
        required=False, 
    )
    city = fields.Str(
        required=False, 
    )
    state = fields.Str(
        required=False, 
    )
    postcode = fields.Str(
        required=False, 
    )
    landmark = fields.Str(
        required=False, 
        allow_none=True,
    )
    currency = fields.Str(
        required=False, 
    )
    website = fields.Str(
        required=False, 
        allow_none=True,
        validate=validate_store_url,
    )
    alternate_contact_number = fields.Str(
        required=False,
        validate=validate_phone
    )
    time_zone = fields.Str(
        required=False, 
    )
    prefix = fields.Str(
        required=False, 
    )
    first_name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=60),
    )
    last_name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=60),
    )
    username = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=60),
    )
    password = fields.Str(
        required=False,
        validate=validate_password,
    )
    email = fields.Email(
        required=False, 
        validate=validate.Length(min=5, max=100),
    )
    store_url = fields.Str(
        required=False,
        validate=validate_store_url,
    )
    packages = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=30),
    )
    user_id = fields.Str(
        required=False,
        allow_none=True,
    )
    return_url = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=200),
    )
    callback_url = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=200),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# -----------------------BUSINESSE-------------------------

# -----------------------ROLE-------------------------

class RoleSchema(Schema):
    name = fields.Str(
        required=True,
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

    # Dynamic fields based on new list
    system_users = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "System Users details are required",
                "invalid": "System Users must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    beneficiaries = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Beneficiaries details are required",
                "invalid": "Beneficiaries must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    senders = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Senders details are required",
                "invalid": "Senders must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    expenses = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Expenses details are required",
                "invalid": "Expenses must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    transactions = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Transactions details are required",
                "invalid": "Transactions must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    send_money = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Send Money details are required",
                "invalid": "Send Money must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    notice_board = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Notice Board details are required",
                "invalid": "Notice Board must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    bill_pay_services = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Bill Pay Services details are required",
                "invalid": "Bill Pay Services must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    check_current_rate = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Check Current Rate details are required",
                "invalid": "Check Current Rate must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

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
        error_messages={"required": "Role ID is required", "invalid": "Invalid Role ID. Ensure it's a valid. Ensure you add a valid Role ID."}
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

    # Dynamic fields based on new list
    system_users = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "System Users details are required",
                "invalid": "System Users must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    beneficiaries = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Beneficiaries details are required",
                "invalid": "Beneficiaries must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    senders = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Senders details are required",
                "invalid": "Senders must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    expenses = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Expenses details are required",
                "invalid": "Expenses must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    transactions = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Transactions details are required",
                "invalid": "Transactions must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    send_money = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Send Money details are required",
                "invalid": "Send Money must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    notice_board = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Notice Board details are required",
                "invalid": "Notice Board must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    bill_pay_services = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Bill Pay Services details are required",
                "invalid": "Bill Pay Services must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    check_current_rate = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            default=[permission_template],
            error_messages={
                "required": "Check Current Rate details are required",
                "invalid": "Check Current Rate must be a valid array"
            }
        ),
        required=False,
        allow_none=True
    )

    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"
    )

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
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
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

class RoleIdQuerySchema(Schema):
    role_id = fields.Str(
        required=True,
        validate=validate_objectid,
        description="The role_id of the role to fetch details."
    )

# Expense ID Query
class ExpenseIdQuerySchema(Schema):
    expense_id = fields.Str(
        required=True,
        validate=validate_objectid, 
        description="Expense ID of the Expense to fetch detail."
    )

# System User ID
class SystemUserIdQuerySchema(Schema):
    system_user_id = fields.Str(required=True, validate=validate_objectid, description="System User ID of the System User to fetch detail.")

