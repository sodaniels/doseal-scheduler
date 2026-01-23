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

class LimitSchema(Schema):
    amount = fields.Float(
        required=True,
        error_messages={"required": "Amount is required", "invalid": "Invalid Amount"}
    )  
