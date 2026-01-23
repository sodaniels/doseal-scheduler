import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate
)
from ...utils.validation import validate_objectid

# Notice Board schema
class NoticeBoardSchema(Schema):
    title = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=200),
        error_messages={"required": "Title is required", "invalid": "Invalid Title"}
    )
    
    excerpt = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=600),
        error_messages={"required": "Excerpt is required", "invalid": "Invalid Excerpt"}
    )
    
    message = fields.Str(
        required=True,
        error_messages={"required": "Message is required"}
    )
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)
  
class NoticeBoardUpdateSchema(Schema):
    notice_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Notice ID is required", "invalid": "Invalid Notice ID"}
    )
    title = fields.Str(
        required=False,
        allow_none=True
    )
    
    excerpt = fields.Str(
        required=False,
        allow_none=True
    )
    
    message = fields.Str(
        required=False,
        allow_none=True
    )
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)
    
class NoticeBoardsSchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True
    )
    per_page = fields.Str(
        required=False,
        allow_none=True
    )

class UserIdQuerySchema(Schema):
    user_id = fields.Str(required=True,validate=validate_objectid,  description="The user_id of the user to fetch beneficaires.")

class NoticeBoardIdQuerySchema(Schema):
    notice_id = fields.Str(required=True, validate=validate_objectid, description="Notice ID of the Notice to fetch detail.")
