from marshmallow import Schema, fields, validate, ValidationError

class ValidateRegistrySchema(Schema):
   
    person = fields.Dict(
        required=True,
        error_messages={"required": "Person is required", "null": "Person cannot be null"}
    )
    address = fields.Dict(
        required=True,
        error_messages={"required": "Address is required", "null": "Address cannot be null"}
    )
    admin_id = fields.Str(
        required=False,
    )
    endpoint = fields.Str(
        required=False,
    )
    

  