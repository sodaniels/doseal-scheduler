from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates_schema
)
from ...utils.validation import (
    validate_iso2, validate_objectid
)


class UpdateUsernameSchema(Schema):
    username = fields.Str(
        required=True,
        error_messages={"required": "Username is required"},
    )
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate.Length(min=2, max=2), validate_iso2],
        error_messages={"required": "Country ISO 2 is required", "invalid": "Invalid ISO 2 code"}
    )

class GetAgentsQuerySchema(Schema):
    page = fields.Integer(
        required=False,
        validate=validate.Range(min=1),
        error_messages={
            "invalid": "PageSize must be a positive integer."
        }
    )
    per_page = fields.Integer(
        required=False,
        validate=validate.Range(min=0),
        error_messages={
            "invalid": "Per_page must be a non-negative integer."
        }
    )
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Business ID is required",
            "invalid": "Invalid Business ID"
        }
    )


class GetAgentQuerySchema(Schema):
    username = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid username"}
    )
    agent_id = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Invalid agent ID"}
    )
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Business ID is required",
            "invalid": "Invalid Business ID"
        }
    )

    @validates_schema
    def validate_username_or_agent_id(self, data, **kwargs):
        """
        Ensure that at least one of username or agent_id is provided.
        """
        if not data.get("username") and not data.get("agent_id"):
            raise ValidationError(
                "Either 'username' or 'agent_id' must be provided.",
                field_name="username"
            )

class GetAgentByAgentIdQuerySchema(Schema):
    agent_id = fields.Str(
        required=True,
        error_messages={"required": "Username is required"},
    )
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )


class UpdateAgentAccountBalanceSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    agent_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Agent ID is required", "invalid": "Invalid Agent ID"}
    )
    amount = fields.Float(
        required=True,
        default=0,
        error_messages={"required": "Amount is required", "invalid": "Invalid amount"}
    )


class TreasureInitialTopupSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    amount = fields.Float(
        required=True,
        default=0,
        error_messages={"required": "Amount is required", "invalid": "Invalid amount"}
    )

class TreasurePlaceHoldSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    agent_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Agent ID is required", "invalid": "Invalid Agent ID"}
    )
    amount = fields.Float(
        required=True,
        default=0,
        error_messages={"required": "Amount is required", "invalid": "Invalid amount"}
    )
    
    internal_reference = fields.Str(
        required=True,
        error_messages={"required": "Internal Reference is required", "invalid": "Invalid Internal Reference"}
    )
    purpose = fields.Str(
        required=True,
        error_messages={"required": "Purpose is required", "invalid": "Invalid Purpose"}
    )

class TreasureCaptureHoldSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    hold_id = fields.Str(
        required=True,
        error_messages={"required": "Hold ID is required", "invalid": "Invalid Hold ID"}
    )
    
    payout_network_account = fields.Str(
        required=False,
        allow_none=True
    )

class TreasureReleaseHoldSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    hold_id = fields.Str(
        required=True,
        error_messages={"required": "Hold ID is required", "invalid": "Invalid Hold ID"}
    )


class TreasureRefundCaptureSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    original_txn_id = fields.Str(
        required=True,
        error_messages={"required": "Transaction ID is required", "invalid": "Invalid Transaction ID"}
    )
    reason = fields.Str(
        required=True,
        error_messages={"required": "Reason is required", "invalid": "Invalid Reason"}
    )

class TreasureGetAgentAccountSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
    agent_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Agent ID is required", "invalid": "Invalid Agent ID"}
    )

class TreasureGetAccountsSchema(Schema):
    
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Invalid Business ID"}
    )
















