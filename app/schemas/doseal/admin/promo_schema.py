import re
import uuid
import pymongo
from datetime import datetime
import phonenumbers
from marshmallow import (
    Schema, fields, validate, validates_schema, ValidationError
)

from ....utils.validation import (
    validate_objectid,
    validate_future_datetime_on,
    validate_future_datetime_on_including_today
)


# ---------------------------------------------------
# Create Promo Schema
# ---------------------------------------------------
class PromoSchema(Schema):
    promo_name = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=100),
        error_messages={"required": "Promo name is required", "invalid": "Invalid promo name"}
    )

    promo_amount = fields.Float(
        required=True,
        error_messages={"required": "Promo amount is required", "invalid": "Invalid promo amount"}
    )

    promo_category = fields.Str(
        required=True,
        validate=validate.OneOf(["Subscriber", "Agent"]),
        error_messages={"required": "Promo category is required"}
    )

    promo_start_date = fields.Str(
        required=True,
        validate=validate_future_datetime_on_including_today,
        error_messages={"required": "Promo start date is required", "invalid": "Invalid promo start date"}
    )

    promo_end_date = fields.Str(
        required=True,
        validate=validate_future_datetime_on,
        error_messages={"required": "Promo end date is required", "invalid": "Invalid promo end date"}
    )

    promo_limit = fields.Float(
        required=False,
        allow_none=True
    )

    promo_threshold = fields.Int(
        required=True,
        error_messages={"required": "Promo threshold is required", "invalid": "Invalid promo threshold"}
    )
    promo_total_allowable_limit = fields.Int(
        required=True,
        error_messages={"required": "Promo Total Allowable Limit is required", "invalid": "Invalid Promo Total Allowable Limit"}
    )


    promo_status = fields.Bool(
        required=True,
        error_messages={"required": "Promo status is required"}
    )

    createdAt = fields.DateTime(dump_only=True)
    updatedAt = fields.DateTime(dump_only=True)


# ---------------------------------------------------
# Query Schema: GET /promo?promo_id=...
# ---------------------------------------------------
class PromoIdQuerySchema(Schema):
    promo_id = fields.Str(
        required=True,
        validate=validate_objectid,
        error_messages={"required": "promo_id is required", "invalid": "Invalid promo_id"}
    )

class ActivePromoByCategorySchema(Schema):
    promo_category = fields.Str(
        required=True,
        error_messages={"required": "Promo Category is required", "invalid": "Invalid Promo Category"}
    )


# ---------------------------------------------------
# Update Promo Schema (PATCH)
# ---------------------------------------------------
class PromoUpdateSchema(Schema):
    promo_id = fields.Str(
        required=True,
        validate=validate_objectid,
        error_messages={"required": "promo_id is required", "invalid": "Invalid promo_id"}
    )

    promo_name = fields.Str(required=False, validate=validate.Length(min=5, max=100))
    promo_amount = fields.Float(required=False)
    promo_category = fields.Str(required=False, validate=validate.OneOf(["Subscriber", "Agent"]))
    promo_start_date = fields.Str(required=False, validate=validate_future_datetime_on_including_today)
    promo_end_date = fields.Str(required=False, validate=validate_future_datetime_on)
    promo_limit = fields.Float(required=False, allow_none=True)
    promo_total_allowable_limit = fields.Int(required=False, allow_none=True)
    promo_threshold = fields.Int(required=False)
    promo_status = fields.Bool(required=False)

    @validates_schema
    def validate_date_ordering(self, data, **kwargs):
        """
        If both start and end dates are updated, ensure end >= start.
        """
        start = data.get("promo_start_date")
        end = data.get("promo_end_date")

        if start and end:
            try:
                sdt = datetime.fromisoformat(start)
                edt = datetime.fromisoformat(end)
            except Exception:
                return  # Let field validators handle invalid format

            if edt < sdt:
                raise ValidationError(
                    {"promo_end_date": ["promo_end_date must be on/after promo_start_date"]}
                )


# ---------------------------------------------------
# Pagination + Filters: GET /promos
# ---------------------------------------------------
class PromosQuerySchema(Schema):
    page = fields.Int(required=False)
    per_page = fields.Int(required=False)

    promo_status = fields.Bool(required=False)
    promo_category = fields.Str(required=False, validate=validate.OneOf(["Subscriber", "Agent"]))
