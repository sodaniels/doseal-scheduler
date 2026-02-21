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
    email = fields.Email(required=True, error_messages={"invalid": "Invalid email address"})
    password = fields.Str(required=True, load_only=True, error_messages={"required": "password is required"})

class ForgotPasswordInitiateSchema(Schema):
    """Schema for initiating forgot password."""
    
    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required"}
    )
    
    return_url = fields.Str(
        required=False,
        allow_none=True,
        load_default=None
    )


class ResetPasswordSchema(Schema):
    """Schema for resetting password."""
    
    token = fields.Str(
        required=True,
        error_messages={"required": "Reset token is required"}
    )
    
    password = fields.Str(
        required=True,
        validate=validate.Length(min=8),
        error_messages={
            "required": "Password is required",
            "invalid": "Password must be at least 8 characters"
        }
    )

class LoginExecuteSchema(Schema):
    email = fields.Email(required=True, error_messages={"invalid": "Invalid email address"})
    otp = fields.Str(required=True)


# --- Responses ---
class LoginInitiateResponseSchema(Schema):
    success = fields.Bool(required=True)
    status_code = fields.Int(required=True)
    message = fields.Str(required=True)
    message_to_show = fields.Str(required=False)


class LoginExecuteResponseSchema(Schema):
    success = fields.Bool(required=True)
    status_code = fields.Int(required=True)
    message = fields.Str(required=True)

    access_token = fields.Str(required=False)
    token_type = fields.Str(required=False)
    expires_in = fields.Int(required=False)