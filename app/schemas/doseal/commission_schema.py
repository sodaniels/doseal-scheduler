import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate
)
from ...utils.validation import validate_objectid

# Commission schema
class CommissionSchema(Schema):
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Name is required", "invalid": "Invalid Name"}
    )
    
    commission = fields.Int(
        required=True,
        error_messages={"required": "Commission is required", "invalid": "Invalid Commission"}
    )
    
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)
  
class CommissionUpdateSchema(Schema):
    commission_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Commission ID is required", "invalid": "Commission ID of sender"}
    )
    
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=60),
        error_messages={"required": "Name is required", "invalid": "Invalid Name"}
    )
    
    commission = fields.Int(
        required=True,
        error_messages={"required": "Commission is required", "invalid": "Invalid Commission"}
    )
    
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)
  
  
class CommissionIdQuerySchema(Schema):
    commission_id = fields.Str(required=True, validate=validate_objectid, description="Commission ID of the Commission to fetch detail.")


class CommissionsSchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True
    )
    per_page = fields.Str(
        required=False,
        allow_none=True
    )
