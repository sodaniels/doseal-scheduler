import re
import uuid
import pymongo
import phonenumbers
from marshmallow import (
    Schema, fields, validate
)
from ...utils.validation import (
    validate_excel, validate_objectid, validate_future_datetime_on
)


# Contact Upload schema
class ContactUPloadSchema(Schema):
    
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=100),
        error_messages={"required": "Name is required", "invalid": "Invalid Name"}
    )
    file = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_excel,
        error_messages={"invalid": "File must be a valid Excel file"}
    )


class ContactsSchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True
    )
    per_page = fields.Str(
        required=False,
        allow_none=True
    )
    
class GetParamsSchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True
    )
    per_page = fields.Str(
        required=False,
        allow_none=True
    )
    
    
class QuickSendSchema(Schema):
    
    contact_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Contact List ID is required", "invalid": "Invalid Contact List ID"}
    )
    message = fields.Str(
        required=True,
        error_messages={"required": "Message is required", "invalid": "Invalid Message"}
    )

class ScheduleSendSchema(Schema):
    
    contact_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Contact List ID is required", "invalid": "Invalid Contact List ID"}
    )
    message = fields.Str(
        required=True,
        error_messages={"required": "Message is required", "invalid": "Invalid Message"}
    )
    schedule_date = fields.Str(
        required=True,
        validate=validate_future_datetime_on,
        error_messages={"required": "Date is required", "invalid": "Invalid Date"}
    )

class MessageStatusSchema(Schema):
    sid = fields.Str(
        required=True,
        error_messages={"required": "SID is required", "invalid": "Invalid SID"}
    )
    







