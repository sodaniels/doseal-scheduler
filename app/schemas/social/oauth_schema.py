# app/schemas/social/oauth_schema.py
from marshmallow import Schema, fields

class OAuthStartSchema(Schema):
    platform = fields.Str(required=True)

class OAuthCallbackSchema(Schema):
    code = fields.Str(required=True)
    state = fields.Str(required=True)