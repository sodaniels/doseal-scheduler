import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates_schema
)
from werkzeug.datastructures import FileStorage
from app.extensions.db import db

from datetime import datetime

from ..utils.validation import (
    validate_phone, validate_dob, validate_iso3, validate_objectid,
    validate_dob, validate_future_on
)

# Custom validator to check if the phone number is from the correct country
def validate_phone_number(value, tenant_id):
    country_iso_3 = get_country_iso_3_for_tenant(tenant_id)
    if not country_iso_3:
        raise ValidationError("Invalid tenant ID or tenant not found.")
    
    try:
        phone_number = phonenumbers.parse(value, country_iso_3)
        if not phonenumbers.is_valid_number(phone_number):
            raise ValidationError(f"Phone number {value} is not valid for country {country_iso_3}.")
    except phonenumbers.phonenumberutil.NumberParseException:
        raise ValidationError(f"Phone number {value} could not be parsed for country {country_iso_3}.")

@pre_load
def validate_username(self, data, **kwargs):
        """
        This method will be executed before the actual deserialization happens.
        We use this to perform the validation for the phone number (username).
        """
        tenant_id = data.get('tenant_id')
        username = data.get('username')
        
        if tenant_id and username:
            validate_phone_number(username, tenant_id)  # Call custom phone number validation
        return data


# Fetch valid tenant IDs from MongoDB Tenant collection
def get_valid_tenant_ids():
    """
    Query the Tenant collection to get a list of valid tenant_ids.
    """
    tenants_collection = db.get_collection("tenants") # Assuming 'tenants' is the collection name
    tenants = tenants_collection.find({}, {"_id": 0, "id": 1})  # Query all tenant_ids
    return [tenant["id"] for tenant in tenants]  # Return list of tenant_ids

# Fetch the country_iso_3 from the Tenant collection for the given tenant_id
def get_country_iso_3_for_tenant(tenant_id):
    """
    Query the Tenant collection to get the country_iso_3 for a given tenant_id.
    """
    tenants_collection = db.get_collection("tenants")
    tenant = tenants_collection.find_one({"id": tenant_id})
    print(tenant)
    if tenant:
        return tenant.get("country_iso_3")
    return None


# System Sender schema
class SenderSchema(Schema):
    # user_id = fields.Str(
    #     required=True,
    #     validate=[validate.Length(min=1, max=36), validate_objectid],
    #     error_messages={"required": "Agent ID is required", "invalid": "Invalid Agent ID"}
    # )
    
    full_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Full Name is required", "invalid": "Invalid Full Name"}
    )
    
    phone_number = fields.Str(
        required=True,
        validate=[validate.Length(min=10, max=15), validate_phone],
        error_messages={"required": "Phone Number is required", "invalid": "Invalid Phone Number"}
    )
    
    dob = fields.Str(
        required=True,
        validate=validate_dob,
        error_messages={"required": "Date of Birth is required", "invalid": "Invalid Date of Birth"}
    )
    
    post_code_address = fields.Raw(
        required=True,
        error_messages={"required": "Post Code is required", "invalid": "Invalid Post Code"}
    )
    
    id_number = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "ID Number is required", "invalid": "Invalid ID Number"}
    )
    
    id_type = fields.Raw(
        required=True,
        validate=validate.OneOf(["Passport", "Driving Licence", "National Identity Card"]),
        error_messages={"required": "ID Type is required", "invalid": "Invalid ID Type"}
    )
    
    id_expiry = fields.Str(
        required=True,
        validate=validate_future_on,
        error_messages={"required": "ID Expiry is required", "invalid": "Invalid ID Expiry"}
    )
    
    proof_of_address = fields.List(
        fields.Raw(),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid proof of address"}
    )
    
    proof_of_address_onboarding_status = fields.Str(
        validate=validate.OneOf(["UPLOADED", "APPROVED", "REJECTED"]),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Proof of Address Onboarding Status"}
    )
    
    approved_by = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"invalid": "Invalid Approved By"}
    )
    
    date_approved = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Date Approved"}
    )
    
    proof_of_source_of_funds = fields.List(
        fields.Raw(),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid proof of source of funds"}
    )
    
    proof_of_source_of_funds_onboarding_status = fields.Str(
        validate=validate.OneOf(["UPLOADED", "APPROVED", "REJECTED"]),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Proof of Source of Funds Onboarding Status"}
    )
    
    reviewed_by = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"invalid": "Invalid Reviewed By"}
    )
    
    poa_date_reviewed = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid POA Date Reviewed"}
    )
    
    posof_date_reviewed = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid POSOF Date Reviewed"}
    )
    
    created_at = fields.DateTime(
        dump_only=True,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid created_at format"}
    )
    
    updated_at = fields.DateTime(
        dump_only=True,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid updated_at format"}
    )

class SenderUserSchema(Schema):
    sender_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Sender ID is required", "invalid": "Invalid Sender ID"}
    )
    user_id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Agent ID is required", "invalid": "Invalid Agent ID"}
    )
    
    full_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Full Name is required", "invalid": "Invalid Full Name"}
    )
    
    phone_number = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15),
        error_messages={"required": "Phone Number is required", "invalid": "Invalid Phone Number"}
    )
    
    dob = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=20),  # Adjust length based on your date format (e.g., YYYY-MM-DD)
        error_messages={"required": "Date of Birth is required", "invalid": "Invalid Date of Birth"}
    )
    
    post_code_address = fields.Raw(
        required=False,
        allow_none=True,
        error_messages={"required": "Post Code is required", "invalid": "Invalid Post Code"}
    )
    
    id_type = fields.Raw(
        required=False,
        error_messages={"required": "ID Type is required", "invalid": "Invalid ID Type"}
    )
    
    id_number = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "ID Number is required", "invalid": "Invalid ID Number"}
    )
    
    id_expiry = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "ID Expiry is required", "invalid": "Invalid ID Expiry"}
    )
    
    proof_of_address = fields.List(
        fields.Raw(),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid proof of address"}
    )
    
    proof_of_address_onboarding_status = fields.Str(
        validate=validate.OneOf(["UPLOADED", "APPROVED", "REJECTED"]),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Proof of Address Onboarding Status"}
    )
    
    approved_by = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"invalid": "Invalid Approved By"}
    )
    
    date_approved = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Date Approved"}
    )
    
    proof_of_source_of_funds = fields.List(
        fields.Raw(),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid proof of source of funds"}
    )
    
    proof_of_source_of_funds_onboarding_status = fields.Str(
        validate=validate.OneOf(["UPLOADED", "APPROVED", "REJECTED"]),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid Proof of Source of Funds Onboarding Status"}
    )
    
    reviewed_by = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"invalid": "Invalid Reviewed By"}
    )
    
    poa_date_reviewed = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid POA Date Reviewed"}
    )
    
    posof_date_reviewed = fields.DateTime(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid POSOF Date Reviewed"}
    )
    
    created_at = fields.DateTime(
        dump_only=True,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid created_at format"}
    )
    
    updated_at = fields.DateTime(
        dump_only=True,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid updated_at format"}
    )

class SendersSchema(Schema):
    page = fields.Int(
        required=False,
        all_null=True
    )
    per_page = fields.Int(
        required=False,
        all_null=True
    )
    
class SearchSenderQuerySchema(Schema):
    search_term = fields.Str(required=True, description="Search term is required")
    business_id = fields.Str(required=True, validate=validate_objectid, description="Business ID of the User to fetch detail.")
    page = fields.Int(
        required=False,
        all_null=True
    )
    per_page = fields.Int(
        required=False,
        all_null=True
    )
  
    
   

# System Sender schema

class SenderIdQuerySchema(Schema):
    sender_id = fields.Str(required=True, validate=validate_objectid, description="Sender ID of the sender to fetch detail.")
