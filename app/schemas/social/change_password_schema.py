from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from ...utils.validation import (
    validate_password
)

class ChangePasswordSchema(Schema):
    current_password = fields.String(required=True, validate=validate.Length(min=8))
    new_password = fields.String(required=True, validate=validate.Length(min=8))
    
class ChoosePasswordSchema(Schema):
    token = fields.Str(
        required=True,
        error_messages={
            "required": "Token is required",
            "invalid": "Invalid token"
        }
    )

    password = fields.Str(
        required=True,
        load_only=True,
        validate=validate_password
    )

    confirm_password = fields.Str(
        required=True,
        load_only=True,
        validate=validate_password
    )

    @validates_schema
    def validate_passwords_match(self, data, **kwargs):
        """
        Ensure password and confirm_password match.
        """
        password = data.get("password")
        confirm_password = data.get("confirm_password")

        if password and confirm_password and password != confirm_password:
            raise ValidationError(
                {"confirm_password": ["Passwords do not match."]}
            )