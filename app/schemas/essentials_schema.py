import re
import uuid
import pymongo
import phonenumbers
from flask import request
from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates_schema
)
from werkzeug.datastructures import FileStorage
from app.extensions.db import db

from datetime import datetime

from ..utils.validation import (
    validate_phone, validate_dob, validate_iso3, validate_objectid,
    validate_dob, validate_future_on, validate_iso2
)


# Fetch valid tenant IDs from MongoDB Tenant collection
def get_valid_tenant_ids():
    """
    Query the Tenant collection to get a list of valid tenant_ids.
    """
    tenants_collection = db.get_collection("tenants") # Assuming 'tenants' is the collection name
    tenants = tenants_collection.find({}, {"_id": 0, "id": 1})  # Query all tenant_ids
    return [tenant["id"] for tenant in tenants]  # Return list of tenant_ids

@validates_schema
def validate_payment_type(self, data, **kwargs):
    """Custom validation for mno and routing_number based on payment_type"""
    payment_type = data.get("payment_type")
    
    if payment_type == "wallet" and not data.get("mno"):
        raise ValidationError("mno is required when payment_type is 'wallet'.", field_name="mno")
    
    if payment_type == "bank" and not data.get("routing_number"):
        raise ValidationError("routing_number is required when payment_type is 'bank'.", field_name="routing_number")

class BankSchema(Schema):
    country_iso3 = fields.Str(
        required=True,
        validate=[validate.Length(min=3, max=3), validate_iso3],
        error_messages={"required": "Country ISO 3 is required", "invalid": "Invalid ISO 3 code"}
    )  

class RateSchema(Schema):
    from_currency = fields.Str(
        required=True,
        validate=[validate.Length(min=3, max=3)],  # Dynamically set the valid tenant IDs
        error_messages={"required": "From currency is required", "invalid": "Invalid From currency"}
    )
    to_currency = fields.Str(
        required=True,
        validate=[validate.Length(min=3, max=3)],
        error_messages={"required": "To currency is required", "invalid": "Invalid To currency"}
    )
    account_type = fields.Str(
        required=True,
        validate=validate.OneOf(["BANK", "WALLET", "BILLPAY"]),
        error_messages={"required": "Account Type is required", "invalid": "Invalid account type"}
    )
    
class PostCodeSchema(Schema):
    country_iso2 = fields.Str(
        required=True,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"required": "Country ISO2 code is required", "invalid": "Invalid Country ISO2 Code"}
    )
    post_code = fields.Str(
        required=True,
        error_messages={"required": "Post code is required", "invalid": "Invalid Post code"}
    )
    
class AccountValidationSchema(Schema):
    receiving_country = fields.Str(
        required=True,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"required": "Receiving Country ISO2 code is required", "invalid": "Invalid Receiving Country ISO2 Code"}
    )
    account_number = fields.Str(
        required=True,
        error_messages={"required": "Account Number is required", "invalid": "Invalid Account Number"}
    )
    service_type = fields.Str(
        required=True,
        validate=validate.OneOf(["wallet", "bank"]),
        error_messages={"required": "Service Type is required", "invalid": "Invalid Service Type"}
    )
    mno = fields.Str(
        required=False,
        allow_null=True
    )
    routing_number = fields.Str(
        required=False,
        allow_null=True
    )
   
class CorridorSchema(Schema):
    country_iso2 = fields.Str(
        required=True,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"required": "Country ISO2 code is required", "invalid": "Invalid Country ISO2 Code"}
    )
    