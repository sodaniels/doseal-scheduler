from marshmallow import Schema, fields, validate

class ChangePasswordSchema(Schema):
    current_password = fields.String(required=True, validate=validate.Length(min=8))
    new_password = fields.String(required=True, validate=validate.Length(min=8))