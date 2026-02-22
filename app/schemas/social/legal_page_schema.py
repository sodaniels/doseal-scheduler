from marshmallow import Schema, fields, validate

class LegalPageCreateSchema(Schema):
    page_type = fields.String(
        required=True,
        validate=validate.OneOf(["terms", "privacy", "refund", "cookies"])
    )
    title = fields.String(required=True)
    content = fields.String(required=True)
    version = fields.String(required=False)

class LegalPageUpdateSchema(Schema):
    page_id = fields.String(required=True)
    title = fields.String()
    content = fields.String()
    version = fields.String()
    status = fields.String(validate=validate.OneOf(["draft", "published", "archived"]))

class LegalPageQuerySchema(Schema):
    page_type = fields.String(required=True)

class LegalPageListSchema(Schema):
    pass