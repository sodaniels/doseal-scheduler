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
    
class TransactionSchema(Schema):
    
    tenant_id = fields.Int(
        required=False,
        validate=validate.OneOf(get_valid_tenant_ids()),  # Dynamically set the valid tenant IDs
        error_messages={"required": "Tenant ID is required", "invalid": "Invalid Tenant ID"}
    )
    
    business_id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Business User ID"}
    )
    
    user_id = fields.Str(
        required=False,
        error_messages={"required": "User ID is required", "invalid": "User ID"}
    )
    
    user__id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "User ID is required", "invalid": "User ID"}
    )
    
    beneficiary_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Beneficiary ID is required", "invalid": "Beneficiary ID"}
    )
    beneficiary_account = fields.Dict(
        keys=fields.Str(),
        values=fields.Str()
    )
    sender_account = fields.Dict(
        keys=fields.Str(),
        values=fields.Str()
    ) 
    sender_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Sender ID is required", "invalid": "Sender ID"}
    )
    billpay_id = fields.Str(
        required=False
    )
    
    extr_id = fields.Str(
        required=False
    )
    
    receiver_country = fields.Str(
        required=False
    )
    
    system_reference = fields.Str(
        required=False
    )
    
    common_identifier = fields.Str(
        required=False
    )
    
    is_agent = fields.Bool(
        required=False
    )
    
    access_mode = fields.Str(
        required=False
    )
    
    payment_mode = fields.Str(
        required=False,
        validate=validate.OneOf(["Card", "Cash"])
    )
    
    account_id = fields.Str(
        required=False
    )
    
    user_contact_id = fields.Str()
    
    account = fields.Str()
    
    transaction_type = fields.Str()
    
    zeepay_id = fields.Str()
    
    trans_id = fields.Str()
    
    checksum = fields.Str()
    
    medium = fields.Str()
    
    is_card = fields.Bool(
        required=False
    )
    
    receiver_msisdn = fields.Str(
        required=False
    )
    
    transaction_status = fields.Str()
    
    status_message = fields.Str()
    
    sender_details = fields.Dict(
        keys=fields.Str(),
        values=fields.Str()
    )
    
    recipient_details = fields.Dict(
        keys=fields.Str(),
        values=fields.Str()
    )
    
    fraud_kyc = fields.List(fields.Str())
    
    payable = fields.Bool()
    
    amount_details = fields.List(fields.Str())
    
    extra = fields.List(fields.Str())
    
    address = fields.List(fields.Str())
    
    card_expiry = fields.List(fields.Str())
    
    description = fields.Str()
    
    internal_reference = fields.Str(
        required=False
    )
    
    external_reference = fields.Str(
        required=False
    )
    
    send_amount = fields.Float(
        required=True,
        error_messages={"required": "Send Amount is required", "invalid": "Send Amount"}
    )
    
    external_response = fields.Str()
    
    gift_card_provider = fields.Str()
    
    user_payload = fields.Str()
    
    payload = fields.List(fields.Str())
    
    payment_type = fields.Str()
    
    gateway_id = fields.Str()
    
    status = fields.Str()
    
    status_code = fields.Int(
        required=False,
        default=411
    )
    
    provider = fields.Str()
    
    cr_created = fields.Bool()
    
    reversed = fields.Bool()
    
    transaction_type = fields.Str(
        required=False
    )
    
    created_by = fields.Str(
        required=False
    )
    
    referrer = fields.Str(
        required=False
    )
    
    callback_url = fields.Str()
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            valid_ids = get_valid_tenant_ids()
            self.fields["tenant_id"].validate.append(
                validate.OneOf(valid_ids, error="Invalid tenant ID.")
            )
        except Exception:
            pass  # Optional: log the error if needed
    
    class Meta:
        unknown = INCLUDE  # This will allow unknown fields
      
class TranactionIdQuerySchema(Schema):
    transaction_id = fields.Str(required=True, validate=validate_objectid, description="Transaction ID of the Transaction to fetch detail.")

class AgentIdQuerySchema(Schema):
    agent_id = fields.Str(required=True, validate=validate_objectid, description="Agent ID of the Transaction to fetch detail.")

class SenderdQuerySchema(Schema):
    sender_id = fields.Str(required=False, validate=validate_objectid, description="Sender ID of the Transaction to fetch detail.")

class TransactionExecuteSchema(Schema):
    checksum = fields.Str(
        required=True,
        validate=[
            validate.Length(equal=64, error="Checksum must be 64 characters long"),
            validate.Regexp(r'^[A-Fa-f0-9]{64}$', error="Checksum must be a valid SHA-256 hex string")
        ],
        error_messages={"invalid": "Invalid checksum"}
    )

class TransactionQuerySchema(Schema):
    start_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'Start Date'."
        }
    )
    
    end_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'End Date'."
        }
    )
    page = fields.Integer(
        required=False,
        validate=validate.Range(min=1),
        error_messages={
            "invalid": "PageSize must be a positive integer."
        }
    )
    per_page = fields.Integer(
        required=False,
        validate=validate.Range(min=0),
        error_messages={
            "invalid": "Per_page must be a non-negative integer."
        }
    )
    partner_name = fields.String(
        required=False,
        allow_none=True,
    )
    
class TransactionAgentQuerySchema(Schema):
    start_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'Start Date'."
        }
    )
    end_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'End Date'."
        }
    )
    page = fields.Integer(
        required=False,
        validate=validate.Range(min=1),
        error_messages={
            "invalid": "PageSize must be a positive integer."
        }
    )
    per_page = fields.Integer(
        required=False,
        validate=validate.Range(min=0),
        error_messages={
            "invalid": "Per_page must be a non-negative integer."
        }
    )
    agent_id = fields.Str(
        required=True, 
        validate=validate_objectid, 
        description="Agent ID of the Transaction to fetch detail."
    )

class TransactionSenderQuerySchema(Schema):
    start_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'Start Date'."
        }
    )
    end_date = fields.Str(
        required=False,
        error_messages={
            "invalid": "Invalid date-time format for 'End Date'."
        }
    )
    page = fields.Integer(
        required=False,
        validate=validate.Range(min=1),
        error_messages={
            "invalid": "PageSize must be a positive integer."
        }
    )
    per_page = fields.Integer(
        required=False,
        validate=validate.Range(min=0),
        error_messages={
            "invalid": "Per_page must be a non-negative integer."
        }
    )
    sender_id = fields.Str(
        required=True, 
        validate=validate_objectid, 
        description="Sender ID of the Transaction to fetch detail."
    )

class TransactionPinNumberAndIRQuerySchema(Schema):
    pin_number = fields.Str(
        required=False,
        allow_none=True,
        description="Pin number of the Transaction to fetch detail."
    )
    internal_reference = fields.Str(
        required=False,
        allow_none=True,
        description="Internal Reference of the Transaction to fetch detail."
    )

    @validates_schema
    def validate_at_least_one(self, data, **kwargs):
        if not data.get('pin_number') and not data.get('internal_reference'):
            raise ValidationError(
                "At least one of 'pin_number' or 'internal_reference' must be provided."
            )

class TransactionSearchQuerySchema(Schema):
    pin_number = fields.Str(
        required=False,
        allow_none=True,
        description="Pin number of the Transaction to fetch detail."
    )
    internal_reference = fields.Str(
        required=False,
        allow_none=True,
        description="Internal Reference of the Transaction to fetch detail."
    )
    receiverId = fields.Str(
        required=False,
        allow_none=True,
        description="Receiver ID of the Transaction to fetch detail."
    )
    senderId = fields.Str(
        required=False,
        allow_none=True,
        description="Sender ID of the Transaction to fetch detail."
    )
    account = fields.Str(
        required=False,
        allow_none=True,
        description="Account number of the Transaction to fetch detail."
    )

    @validates_schema
    def validate_at_least_one(self, data, **kwargs):
        if not any([
            data.get('pin_number'),
            data.get('internal_reference'),
            data.get('receiverId'),
            data.get('senderId'),
            data.get('account')
        ]):
            raise ValidationError(
                "At least one of 'pin_number', 'internal_reference', 'receiverId', 'senderId', or 'account' must be provided."
            )

class TransactionSummaryQuerySchema(Schema):
    partner_name = fields.Str(
        required=False,
        allow_none=True,
    )













