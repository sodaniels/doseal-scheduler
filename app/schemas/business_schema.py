import re
from marshmallow import Schema, fields, validate, ValidationError
from app.extensions.db import db

from ..utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on,
    validate_past_date, validate_date_format, validate_objectid, validate_store_url,
    validate_password,
)


def get_valid_tenant_ids():
    """
    Query the Tenant collection to get a list of valid tenant_ids.
    """
    try:
        tenants_collection = db.get_collection("tenants")
        tenants = tenants_collection.find({}, {"_id": 0, "id": 1})
        return [tenant["id"] for tenant in tenants]
    except Exception:
        return []


class BusinessSchema(Schema):
    tenant_id = fields.Str(
        required=True,
        validate=[],  # ✅ Initialize as list so we can append in __init__
        error_messages={
            "required": "Tenant ID is required",
            "invalid": "Invalid Tenant ID"
        }
    )

    business_name = fields.Str(required=True, validate=validate.Length(min=2, max=200))
    start_date = fields.Str(required=True, validate=validate_date_format)
    image = fields.Raw(required=False, allow_none=True, validate=validate_image)
    business_contact = fields.Str(required=True, validate=validate.Length(min=10, max=15))
    country = fields.Str(required=True)
    city = fields.Str(required=True)
    state = fields.Str(required=True)
    postcode = fields.Str(required=True)
    landmark = fields.Str(required=False, allow_none=True)
    currency = fields.Str(required=True)
    website = fields.Str(required=False, allow_none=True)
    alternate_contact_number = fields.Str(required=True, validate=validate.Length(min=10, max=15))
    time_zone = fields.Str(required=True)
    prefix = fields.Str(required=False)
    first_name = fields.Str(required=True, validate=validate.Length(min=2, max=60))
    last_name = fields.Str(required=True, validate=validate.Length(min=2, max=60))
    username = fields.Str(required=True, validate=validate.Length(min=2, max=60))
    password = fields.Str(required=True, load_only=True, validate=validate_password)
    email = fields.Email(required=True, validate=validate.Length(min=5, max=100))
    store_url = fields.Str(
        required=True,
        validate=validate_store_url,
        error_messages={
            "invalid": "Store URL must be lowercase, no spaces, and only letters or digits."
        }
    )
    package = fields.Str(required=False, validate=validate.Length(min=5, max=30))
    user_id = fields.Str(required=False, allow_none=True)
    return_url = fields.Str(required=True, validate=validate.Length(min=5, max=200))
    callback_url = fields.Str(required=False, validate=validate.Length(min=5, max=200))
    status = fields.Str(validate=validate.OneOf(["Active", "Inactive"]), load_default="Active")
    account_type = fields.Str(validate=validate.OneOf(["system_owner","business_owner", "super_admin"]))
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        valid_tenant_ids = get_valid_tenant_ids()
        self.fields["tenant_id"].validate.append(
            validate.OneOf(valid_tenant_ids, error="Invalid tenant ID.")
        )


class OAuthCredentialsSchema(Schema):
    client_id = fields.Str(
        required=True,
        validate=validate.Length(max=100),
        error_messages={"required": "Client ID is required", "null": "Client ID cannot be null"}
    )
    
