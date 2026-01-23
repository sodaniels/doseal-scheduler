import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates
)
from werkzeug.datastructures import FileStorage
from app.extensions.db import db

from datetime import datetime

from ...utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date,  validate_objectid, validate_pin, validate_iso2
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
    try:
        tenants_collection = db.get_collection("tenants")
        tenants = tenants_collection.find({}, {"_id": 0, "id": 1})
        return [tenant["id"] for tenant in tenants]
    except Exception:
        return []
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


def validate_image(value):
        """
        Custom validation for image field to ensure it's a file, not just text.
        """
        if value and not isinstance(value, FileStorage):
            raise ValidationError("Image must be a valid file.")
        
        return value


class OAuthCredentialsSchema(Schema):
    client_id = fields.Str(
        required=True,
        validate=validate.Length(max=100),
        error_messages={"required": "Client ID is required", "null": "Client ID cannot be null"}
    )
    

class CollectorLoginInitSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    
class CollectorLoginExecuteSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    otp = fields.Str(
        required=True, 
        validate=validate.Length(equal=6),
        error_messages={"required": "OTP is required", "invalid": "OTP is not valid"}
    )
     
    

# System Collector schema
class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(required=True,validate=validate_objectid,  description="The business_id of the store to fetch details.")

class CollectorIdQuerySchema(Schema):
    collector_id = fields.Str(required=True, validate=validate_objectid, description="Collector ID of the Collector to fetch detail.")
