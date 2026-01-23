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
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    agreed_terms_and_conditions = fields.Bool(
        required=True, 
        error_messages={"invalid": "agreed_terms_and_conditions is required."}
    )
    device_id = fields.Str(
        required=True, 
        error_messages={"invalid": "Device Id is required."}
    )
    location = fields.Str(
        required=True, 
        error_messages={"invalid": "Location is required."}
    )

class SubscriberVerifyOTPSchema(Schema):
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    otp = fields.Str(
        required=True, 
        validate=validate.Length(min=6, max=6),
        error_messages={"required": "OTP is required", "invalid": "Invalid phone number"}
    )
    device_checksum = fields.Str(
        required=True,
        error_messages={"required": "Device Checksum required", "invalid": "Invalid Device Checksum"}
    )
   
class SubscriberRegistrationChoosePinSchema(Schema):
    
    pin = fields.Str(
        required=True, 
        validate=validate_pin
    )

class SubscriberIdQuerySchema(Schema):
   subscriber_id = fields.Str(
        required=False,
        allow_none=True,
    )

class SubscriberRegistrationBasicKYCSchema(Schema):
   
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"required": "First Name is required", "invalid": "Invalid First Name"}
    )
    middle_name = fields.Str(
        required=False,
        allow_none=True
    )
    last_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"required": "Last Name is required", "invalid": "Invalid Last Name"}
    )
    gender = fields.Str(
        required=True,
        validate=validate.OneOf(["Male", "Female"]),
        error_messages={"required": "Gender is required"}
    )
    email = fields.Email(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"required": "Email is required", "invalid": "Invalid Email"}
    )
    referral_code = fields.Str(
        required=False,
        allow_none=True,
    )
    post_code = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=10),
        error_messages={"required": "Post code is required", "invalid": "Invalid Post code"}
    )
    address = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"required": "Post code address is required", "invalid": "Invalid Post code address"}
    )

class SubscriberRegistrationEmailSchema(Schema):

    return_url = fields.Str(
        required=True,
        error_messages={"required": "Return is required", "invalid": "Return of the agent"}
    )
  
class SubscriberRegistrationVerifyEmailSchema(Schema):
    
    token = fields.Str(
        required=True,
        error_messages={"required": "Token is required", "invalid": "Token of the regsitration session the agent"}
    )
    
    user_id = fields.Str(
        required=True,
        error_messages={"required": "Subscriber ID is required", "invalid": "Subscriber ID of the agent"}
    )
 
class SubscriberRegistrationUploadIDDocumentsSchema(Schema):
    id_type = fields.Str( 
        required=True,
        validate=validate.OneOf(["Passport", "Driving Licence", "National Identity Card"]),
        error_messages={"invalid": "Invalid ID type"}
    )
    
    id_number = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid ID number"}
    )
    
    id_expiry = fields.Str(
        required=True,
        validate=validate_future_on,
        error_messages={"invalid": "Invalid ID Expiry"}
    )
    
    
    id_front_image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "ID Front must be a valid file"}
    )
    
    id_back_image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "ID Back must be a valid file"}
    )
 
class SubscriberRegistrationPoAUploadDocumentsSchema(Schema):
    poa_type = fields.Str( 
        required=True,
        validate=validate.OneOf(["Utility Bill", "Bank Statement", "Council Tax Bill", "Tenancy Agreement"]),
        error_messages={"invalid": "Invalid PoA type"}
    )
    proof_of_address = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Proof of address must be a valid file"}
    )
 
















