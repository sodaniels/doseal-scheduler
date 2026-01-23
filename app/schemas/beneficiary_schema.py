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
    validate_phone, validate_iso2, validate_iso3, validate_objectid,
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
    tenants_collection = db.get_collection("tenants") 
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


# System Beneficiary schema
from marshmallow import Schema, fields, validate, validates_schema, ValidationError

from marshmallow import Schema, fields, validate, validates_schema, ValidationError

class BeneficiarySchema(Schema):
    sender_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Sender ID is required", "invalid": "Sender ID of sender"}
    )

    payment_mode = fields.Str(
        required=True,
        validate=validate.OneOf(["wallet", "bank"]),
        error_messages={"required": "Payment mode is required", "invalid": "Invalid payment mode"}
    )

    country = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"invalid": "Invalid country"}
    )

    address = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid address"}
    )

    flag = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid flag"}
    )

    currency_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=10),
        error_messages={"invalid": "Invalid currency code"}
    )

    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"invalid": "Invalid bank name"}
    )

    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"invalid": "Invalid account name"}
    )

    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=10, max=100),
        error_messages={"invalid": "Invalid account number"}
    )

    recipient_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"invalid": "Invalid recipient name"}
    )

    recipient_phone_number = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15),
        error_messages={"invalid": "Invalid phone number"}
    )

    mno = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid MNO"}
    )

    routing_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid routing number"}
    )

    verified_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Verified name is required", "invalid": "Invalid verified name"}
    )

    recipient_country_iso2 = fields.Str(
        required=False,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"invalid": "Invalid ISO 2 code"}
    )

    recipient_country_iso3 = fields.Str(
        required=False,
        validate=[validate.Length(min=3, max=3), validate_iso3],
        error_messages={"invalid": "Invalid ISO 3 code"}
    )

    date = fields.DateTime(required=False, allow_none=True)

    createdAt = fields.DateTime(dump_only=True)
    updatedAt = fields.DateTime(dump_only=True)

    # --- Conditional Validation ---
    @validates_schema
    def validate_required_fields(self, data, **kwargs):
        payment_mode = data.get("payment_mode")

        wallet_required = ["country", "recipient_country_iso2", "recipient_country_iso3",
                           "recipient_phone_number", "mno"]
        
        bank_required = ["country", "recipient_country_iso2", "recipient_country_iso3",
                         "recipient_phone_number", "bank_name", "account_name",
                         "account_number", "routing_number"]

        if payment_mode == "wallet":
            missing = [f for f in wallet_required if not data.get(f)]
            if missing:
                raise ValidationError({f: ["This field is required for wallet payment mode"] for f in missing})

        elif payment_mode == "bank":
            missing = [f for f in bank_required if not data.get(f)]
            if missing:
                raise ValidationError({f: ["This field is required for bank payment mode"] for f in missing})

class BeneficiaryUpdateSchema(Schema):
    beneficiary_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Beneficiary ID is required", "invalid": "Beneficiary User ID"}
    )
    sender_id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Sender ID is required", "invalid": "Sender ID of sender"}
    )
    payment_mode = fields.Str(
        required=False,
        validate=validate.OneOf(["Wallet", "Bank"]),
        error_messages={"required": "Payment mode is required", "invalid": "Invalid payment mode"}
    )
    
    country = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Country is required", "invalid": "Invalid country"}
    )
    
    address = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"required": "Address is required"}
    )
    
    flag = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid flag"}
    )
    
    currency_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=10),
        error_messages={"invalid": "Invalid currency code"}
    )
    
    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"invalid": "Invalid bank name"}
    )
    
    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"invalid": "Invalid account name"}
    )
    
    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=10, max=100),
        error_messages={"invalid": "Invalid account number"}
    )
    
    recipient_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"invalid": "Invalid recipient name"}
    )
    
    recipient_phone_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=10, max=15),
        error_messages={"invalid": "Invalid phone number"}
    )
    
    mno = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid MNO"}
    )
    
    routing_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid routing number"}
    )
    
    verified_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"invalid": "Invalid verified name"}
    )
    
    recipient_country_iso2 = fields.Str(
        required=False,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"required": "Recipient Country ISO 2 is required", "invalid": "Invalid ISO 2 code"}
    )

    recipient_country_iso3 = fields.Str(
        required=False,
        validate=[validate.Length(min=3, max=3), validate_iso3],
        error_messages={"required": "Recipient Country ISO 3 is required", "invalid": "Invalid ISO 3 code"}
    )
    
    date = fields.DateTime(
        required=False,
        all_none=True
    )
    
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)

class BeneficiariesSchema(Schema):
    page = fields.Int(
        required=False,
        all_null=True
    )
    per_page = fields.Int(
        required=False,
        all_null=True
    )
  
class BeneficiarySearchSchema(Schema):
    
    recipient_phone_number = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid phone number"}
    )

    account_number = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid account number"}
    )
    
    recipient_country_iso2 = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid country IS2"}
    )

    @validates_schema
    def validate_either_phone_or_account(self, data, **kwargs):
        """
        Ensure at least one of recipient_phone_number or account_number is provided.
        """
        if not data.get("recipient_phone_number") and not data.get("account_number"):
            raise ValidationError(
                "Either recipient_phone_number or account_number must be provided."
            )

# System Beneficiary schema

class UserIdQuerySchema(Schema):
    user_id = fields.Str(required=True,validate=validate_objectid,  description="The user_id of the user to fetch beneficaires.")

class BeneficiaryIdQuerySchema(Schema):
    beneficiary_id = fields.Str(required=True, validate=validate_objectid, description="Beneficiary ID of the Beneficiary to fetch detail.")

class SenderIdQuerySchema(Schema):
    sender_id = fields.Str(required=True, validate=validate_objectid, description="Sender ID of the Beneficiaries to fetch detail.")
