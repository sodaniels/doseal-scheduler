# app/schemas/social/schwriter_schema.py

from __future__ import annotations

from marshmallow import Schema, fields, validate, validates_schema, ValidationError


class SchWriterContentSchema(Schema):
    text = fields.Str(required=False, allow_none=True)
    link = fields.Str(required=False, allow_none=True)
    media = fields.Raw(required=False, allow_none=True)


class SchWriterRequestSchema(Schema):
    # ✅ accept string OR list
    platform = fields.Raw(required=True)

    action = fields.Str(
        required=False,
        load_default="full",
        validate=validate.OneOf([
            "fix_grammar",
            "optimize_length",
            "adjust_tone",
            "inspire_engagement",
            "full",
        ])
    )

    content = fields.Nested(SchWriterContentSchema, required=True)
    brand = fields.Dict(required=False, allow_none=True)
    preferences = fields.Dict(required=False, allow_none=True)

    @validates_schema
    def validate_payload(self, data, **kwargs):
        content = data.get("content") or {}
        text = (content.get("text") or "").strip()
        media = content.get("media")

        if not text and not media:
            raise ValidationError({"content": ["Provide at least 'text' or 'media'"]})

        p = data.get("platform")
        if isinstance(p, str):
            if not p.strip():
                raise ValidationError({"platform": ["platform cannot be empty"]})
        elif isinstance(p, list):
            if not p or not all(isinstance(x, str) and x.strip() for x in p):
                raise ValidationError({"platform": ["platform must be a non-empty list of strings"]})
        else:
            raise ValidationError({"platform": ["platform must be a string or array of strings"]})