import re
import uuid
import pymongo
import phonenumbers
from app.extensions.db import db
import os
from datetime import datetime

from ..utils.validation import (
    validate_phone, validate_iso2, validate_iso3, validate_objectid,
)

from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates_schema, INCLUDE
)
from werkzeug.datastructures import FileStorage

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

def validate_currency(value):
    if len(value) != 3 or not value.isalpha():
        raise ValidationError("Must be a valid 3-letter ISO currency code.")
    
class BillerListSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    
    
class AccountValidationSchema(Schema):

    billpay_id = fields.Str(
        required=True,
        error_messages={"required": "billpay_id is required"}
    )

    account_id = fields.Str(
        required=False,
        allow_none=True
    )
    
    sender_id = fields.Str(
        required=False,
        allow_none=True
    )
    
    payment_mode = fields.Str(
        required=False,
        validate=validate.OneOf(["Card", "Cash"]),
        allow_none=True
    )
    
    beneficiary_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Beneficiary ID is required", "invalid": "Beneficiary User ID"}
    )
    
    send_amount = fields.Float(
        required=True,
        error_messages={"required": "send_amount is required"}
    )

class InitiatePaymentSchema(Schema):

    checksum = fields.Str(
        required=True,
        error_messages={"required": "Checksum is required"}
    )

    pin = fields.Str(
        required=True,
        error_messages={"required": "PIN is required"}
    )










