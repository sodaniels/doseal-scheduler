
from marshmallow import Schema, fields, validate

class BusinessEmailVerificationSchema(Schema):
   
    return_url = fields.Str(
        required=True,
        error_messages={"required": "Return is required", "invalid": "Return of the agent"}
    )