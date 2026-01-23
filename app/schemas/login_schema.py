from marshmallow import Schema, fields

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
