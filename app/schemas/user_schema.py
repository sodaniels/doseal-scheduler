from marshmallow import Schema, fields, validate, ValidationError
import re

from ..utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date,  validate_objectid,
)


class UserSchema(Schema):
    agent_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Role ID"}
    )
    fullname = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=200),
        error_messages={"required": "Full name is required", "null": "Full name cannot be null"}
    )
    email = fields.Email(
        required=True, 
        validate=validate.Length(min=5, max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    phone_number = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid phone number"}
    )
    role = fields.Str(
        required=True, 
        validate=validate.OneOf(["subscriber", "admin", "super_admin"]),
        error_messages={"required": "Role is required"}
    )

    status = fields.Str(validate=validate.OneOf(["Active", "Inactive", "Blocked"]))
    last_logged_in = fields.DateTime(required=False)
    password = fields.Str(
        required=False,
        load_only=True,
    )
    pin = fields.Str(
        required=False,
        load_only=True,
    )

