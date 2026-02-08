from marshmallow import Schema, fields, validate

class LoginSchema(Schema):
    email = fields.Email(
        required=True, 
        error_messages={"invalid": "Invalid email address"}
        )
    password = fields.Str(
        required=True,
        load_only=True, 
        error_messages={"required": "password is required"},
        )
    
class LoginInitiateSchema(Schema):
    email = fields.Email(
        required=True, 
        error_messages={"invalid": "Invalid email address"}
        )
    password = fields.Str(
        required=True,
        load_only=True, 
        error_messages={"required": "password is required"},
        )

class LoginExecuteSchema(Schema):
    email = fields.Email(
        required=True, 
        error_messages={"invalid": "Invalid email address"}
        )
    otp = fields.Str(
        required=True,
        validate=validate.Length(equal=6, error="OTP must be 6 characters long"),
        error_messages={"required": "OTP is required", "invalid": "Invalid OTP"}
    )