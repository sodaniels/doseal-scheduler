import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate
)
from ...utils.validation import validate_objectid

class LocationDetialSchema(Schema):
    latitude = fields.Float(
        required=True,
        error_messages={"required": "Latitude is required", "invalid": "Latitude must be a number"}
    )
    longitude = fields.Float(
        required=True,
        error_messages={"required": "Longitude is required", "invalid": "Longitude must be a number"}
    )
    address = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=300),
        error_messages={"required": "Address is required", "invalid": "Address must be a string"}
    )
    
# Collection schema
class CollectionSchema(Schema):
    
    admin = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_objectid,  
    )
    
    amount = fields.Float(
        required=True,
        error_messages={"required": "Amount is required", "invalid": "Invalid Title"}
    )
    
    signature = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"required": "Full name is required", "invalid": "Invalid Full name"}
    )
    
    message = fields.Str(
        required=False,
        allow_none=True
    )
    
    location = fields.Nested(LocationDetialSchema, required=True, allow_none=False)
    
    status = fields.Dict(
        keys=fields.Str(
            required=True,
            error_messages={
                "invalid": "Status key must be INITIATED, CONFIRMED, or APPROVED"
            }
        ),
        values=fields.Raw(
            required=False,
            allow_none=True
        ),
        required=False,
        allow_none=True
    )
    
    createdAt = fields.DateTime(dump_only=True)
    
    updatedAt = fields.DateTime(dump_only=True)
  
# Optional: when Content-Type is multipart/form-data, we read text fields from form
class CollectionFormSchema(Schema):
    admin = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    amount = fields.Float(required=True)
    message = fields.Str(
        required=False,
        allow_none=True
    )
    signature = fields.Str(required=True, validate=validate.Length(min=1, max=60))
    location = fields.Str(required=True, description="JSON string of LocationDetialSchema")
    date = fields.Str(required=True, description="Date is required")
    
class CollectionsSchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True
    )
    per_page = fields.Str(
        required=False,
        allow_none=True
    )
    
class CollectionsQuerySchema(Schema):
    page = fields.Integer(load_default=None, validate=validate.Range(min=1))
    per_page = fields.Integer(load_default=None, validate=validate.Range(min=1, max=100))
    agent = fields.Str(load_default=None)
    confirmed = fields.Boolean(
        load_default=None,
        truthy={"true", "1", "yes", "on", "True", "TRUE"},
        falsy={"false", "0", "no", "off", "False", "FALSE"},
    )

    
class UserIdQuerySchema(Schema):
    user_id = fields.Str(required=True,validate=validate_objectid,  description="The user_id of the user to fetch beneficaires.")

class CollectionIdQuerySchema(Schema):
    collection_id = fields.Str(required=True, validate=validate_objectid, description="Collection ID of the Collection to fetch detail.")

class ConfirmCollectionIdQuerySchema(Schema):
    collection_id = fields.Str(required=True, validate=validate_objectid, description="Collection ID of the Collection to fetch detail.")
    images = fields.List(fields.Dict(), required=True, allow_none=True),
    barcode = fields.Str(required=True, description="The barcode is required")
    message = fields.Str(
        required=False,
        allow_none=True,
    )
    

class ApprovalCollectionIdQuerySchema(Schema):
    
    collection_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Collection ID is required", "invalid": "Invalid Collection ID"}
    )
    barcode = fields.Str(
        required=True,
        error_messages={"required": "Barcode is required", "invalid": "Invalid Barcode"}
    )
    remark = fields.Str(
        required=False,
        allow_none=True,
    )
    flag_collection = fields.Str(
        required=False,
        allow_none=True,
    )
