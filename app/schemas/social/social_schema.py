from marshmallow import Schema, fields, validate, ValidationError, validates_schema

class MediaSchema(Schema):
    type = fields.Str(required=True, validate=validate.OneOf(["none", "image", "video"]))
    url = fields.Str(required=False, allow_none=True)       # public URL for IG/Threads/Pinterest
    file_path = fields.Str(required=False, allow_none=True) # local file for YouTube

class SchedulePostSchema(Schema):
    caption = fields.Str(required=True, validate=validate.Length(min=1, max=2200))
    platforms = fields.List(fields.Str(), required=True)
    scheduled_for = fields.DateTime(required=True)  # ISO datetime
    link = fields.Str(required=False, allow_none=True)
    media = fields.Nested(MediaSchema, required=False)
    extra = fields.Dict(required=False)

    @validates_schema
    def validate_platforms(self, data, **kwargs):
        allowed = {"facebook", "instagram", "threads", "x", "linkedin", "pinterest", "youtube", "tiktok"}
        plats = set(data.get("platforms") or [])
        bad = plats - allowed
        if bad:
            raise ValidationError({"platforms": [f"Unsupported platforms: {', '.join(sorted(bad))}"]})

class PaginationSchema(Schema):
    page = fields.Int(required=False, allow_none=True)
    per_page = fields.Int(required=False, allow_none=True)