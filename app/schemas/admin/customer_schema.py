import re
import uuid
from marshmallow import Schema, fields, validate, ValidationError
from werkzeug.datastructures import FileStorage

from ...utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date,  validate_objectid,
)

# Custom Validator for Phone Number
def validate_phone(value):
    if not isinstance(value, str):
        raise ValidationError("Phone number must be a string.")
    if len(value) < 10 or len(value) > 15:
        raise ValidationError("Phone number must be between 10 and 15 characters.")
    if not value.isdigit():
        raise ValidationError("Phone number must only contain digits.")
    return value

# Custom Validator for Tax (if required)
def validate_tax(value):
    if value and not re.match(r'^\d+(\.\d{1,2})?$', value):  # Ensure tax is a valid decimal number
        raise ValidationError("Tax must be a valid number with up to two decimal places.")
    return value

def validate_image(value):
    """
    Custom validation for image field to ensure it's a file, not just text.
    """
    if value and not isinstance(value, FileStorage):
        raise ValidationError("Image must be a valid file.")
    
    return value

# Customer schema
class CustomerSchema(Schema):
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    address = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Address is required", "min_length": "Address must be at least 5 characters"}
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    city = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "City must be a string"}
    )
    town = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Town must be a string"}
    )
    postal_code = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Postal code must be a string"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class CustomerUpdateSchema(Schema):
    customer_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Customer ID is required", "invalid": "Customer ID"}
    )
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    address = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Address is required", "min_length": "Address must be at least 5 characters"}
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    city = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "City must be a string"}
    )
    town = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Town must be a string"}
    )
    postal_code = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Postal code must be a string"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Customer Schema  

# Customer Group Schema
class CustomerGroupSchema(Schema):
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Customer Group is required", "invalid": "Customer Group"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class CustomerGroupUpdateSchema(Schema):
    customer_group_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Customer Group ID is required", "invalid": "Customer Group ID"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Customer Group Schema

# System User schema
class SystemUserSchema(Schema):
    
    username = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    display_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    outlet = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet is required"}
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
    
    admin_id = fields.Str(
        required=False,
        allow_none=True,
    )
    
    phone = fields.Str(
        required=True,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    ################################################################
   
    date_of_birth = fields.Str(
        required=False,
        validate=validate_past_date, 
        error_messages={"required": "Date of Birth is required", "invalid": "Date of Birth"}
    )
    
    gender = fields.Str(
        validate=validate.OneOf(["Male", "Female"]),
    )
    
    marital_status = fields.Str(
        validate=validate.OneOf(["Married", "Unmarried", "Divorced"]),
    )
    
    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    
    family_contact_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    twitter_link = fields.Str(
        required=False,
        allow_none=True,
    )
    id_type = fields.Str(
        required=False,
        allow_none=True,
    )
    id_number = fields.Str(
        required=False,
        allow_none=True,
    )
    permanent_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    sort_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    branch = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    tax_payer_id = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )

    
    last_logged_in = fields.DateTime(required=False)
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SystemUserUpdateSchema(Schema):
    system_user_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Customer ID is required", "invalid": "Customer ID"}
    )
    username = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    display_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    outlet = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet is required"}
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
    
    admin_id = fields.Str(
        required=False,
        allow_none=True,
    )
    
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    ################################################################
   
    date_of_birth = fields.Str(
        required=False,
        validate=validate_past_date, 
        error_messages={"required": "Date of Birth is required", "invalid": "Date of Birth"}
    )
    
    gender = fields.Str(
        validate=validate.OneOf(["Male", "Female"]),
    )
    
    marital_status = fields.Str(
        validate=validate.OneOf(["Married", "Unmarried", "Divorced"]),
    )
    
    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    
    family_contact_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    twitter_link = fields.Str(
        required=False,
        allow_none=True,
    )
    id_type = fields.Str(
        required=False,
        allow_none=True,
    )
    id_number = fields.Str(
        required=False,
        allow_none=True,
    )
    permanent_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    sort_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    branch = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    tax_payer_id = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    
    last_logged_in = fields.DateTime(required=False)
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# System User schema






class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(required=True,validate=validate_objectid,  description="The business_id of the store to fetch details.")

class CustomerIdQuerySchema(Schema):
    customer_id = fields.Str(required=True, validate=validate_objectid, description="Customer ID of the Customer to fetch detail.")
# CustomerGroup ID
class CustomerGroupIdQuerySchema(Schema):
    customer_group_id = fields.Str(required=True, validate=validate_objectid, description="Customer Group ID of the Customer Group to fetch detail.")
# System User ID
class SystemUserIdQuerySchema(Schema):
    system_user_id = fields.Str(required=True, validate=validate_objectid, description="System User ID of the System User to fetch detail.")
