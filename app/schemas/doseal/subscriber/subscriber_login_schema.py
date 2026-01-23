from marshmallow import Schema, fields, validate
from ....utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date,  validate_objectid, validate_pin, validate_iso2,
    validate_future_on
)



class SubscriberLoginInitSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True,
        error_messages={"required": "Username is required", "invalid": "Invalid phone number"}
    )
    device_id = fields.Str(
        required=True, 
        error_messages={"invalid": "Device Id is required."}
    )
    location = fields.Str(
        required=True, 
        error_messages={"invalid": "Location is required."}
    )
    pin = fields.Str(
        required=False, 
        allow_none=True
    )
    
    
    


class SubscriberLoginExecSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True, 
        error_messages={"required": "Username is required", "invalid": "Invalid phone number"}
    )
    otp = fields.Str(
        required=True,
        validate=validate.Length(equal=6, error="OTP must be 6 characters long"),
        error_messages={"required": "OTP is required", "invalid": "Invalid OTP"}
    )
    device_checksum = fields.Str(
        required=True, 
        error_messages={"required": "Device Checksum is required", "invalid": "Device Checksum is not valid"}
    )











