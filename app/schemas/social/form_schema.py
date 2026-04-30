# schemas/church/form_schema.py

from marshmallow import Schema, fields, validate, EXCLUDE
from ...utils.validation import validate_objectid

FIELD_TYPES = ["text","textarea","number","email","phone","dropdown","radio","checkbox","date","time","file","rating","section_header","paragraph"]
TEMPLATE_TYPES = ["Visitor Card","Membership Application","Baptism Request","Child Dedication","Counseling Request","Event Registration","Volunteer Application","Department Nomination","Prayer Request","Feedback","Custom"]
FORM_STATUSES = ["Draft","Published","Closed","Archived"]
PACKAGES = ["Starter","Growth","Pro","Enterprise"]

# ── Field Config (nested) ──
class FieldConfigSchema(Schema):
    class Meta: unknown = EXCLUDE
    field_id = fields.Str(required=False, allow_none=True, validate=validate.Length(max=50))
    field_type = fields.Str(required=True, validate=validate.OneOf(FIELD_TYPES))
    label = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    placeholder = fields.Str(required=False, allow_none=True, validate=validate.Length(max=200))
    required = fields.Bool(load_default=False)
    options = fields.List(fields.Str(validate=validate.Length(max=100)), required=False, load_default=[])
    max_length = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    validation_regex = fields.Str(required=False, allow_none=True, validate=validate.Length(max=200))
    order = fields.Int(required=False, allow_none=True)
    # Map to member profile field for auto-update
    profile_field_map = fields.Str(required=False, allow_none=True, validate=validate.Length(max=50))

# ════════════════════════ FORM ════════════════════════

class FormCreateSchema(Schema):
    class Meta: unknown = EXCLUDE
    title = fields.Str(required=True, validate=validate.Length(min=1, max=300))
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    template_type = fields.Str(load_default="Custom", validate=validate.OneOf(TEMPLATE_TYPES))
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=2000))
    slug = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    fields_config = fields.List(fields.Nested(FieldConfigSchema), load_default=[])
    status = fields.Str(load_default="Draft", validate=validate.OneOf(FORM_STATUSES))
    allow_anonymous = fields.Bool(load_default=False)
    require_login = fields.Bool(load_default=False)
    is_public = fields.Bool(load_default=False)
    is_embeddable = fields.Bool(load_default=False)
    max_submissions = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x else True)
    start_date = fields.Str(required=False, allow_none=True)
    end_date = fields.Str(required=False, allow_none=True)
    confirmation_message = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))
    redirect_url = fields.Url(required=False, allow_none=True)
    notification_emails = fields.List(fields.Email(), required=False, load_default=[])
    auto_update_profile = fields.Bool(load_default=False)
    max_file_size_mb = fields.Int(load_default=5, validate=lambda x: 1 <= x <= 25)

class FormUpdateSchema(Schema):
    class Meta: unknown = EXCLUDE
    form_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    title = fields.Str(required=False, allow_none=True, validate=validate.Length(min=1, max=300))
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=2000))
    fields_config = fields.List(fields.Nested(FieldConfigSchema), required=False, allow_none=True)
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(FORM_STATUSES))
    allow_anonymous = fields.Bool(required=False, allow_none=True)
    require_login = fields.Bool(required=False, allow_none=True)
    is_public = fields.Bool(required=False, allow_none=True)
    is_embeddable = fields.Bool(required=False, allow_none=True)
    max_submissions = fields.Int(required=False, allow_none=True)
    start_date = fields.Str(required=False, allow_none=True)
    end_date = fields.Str(required=False, allow_none=True)
    confirmation_message = fields.Str(required=False, allow_none=True)
    auto_update_profile = fields.Bool(required=False, allow_none=True)
    max_file_size_mb = fields.Int(required=False, allow_none=True)

class FormIdQuerySchema(Schema):
    form_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)

class FormSlugQuerySchema(Schema):
    slug = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    branch_id = fields.Str(required=True, validate=validate_objectid)

class FormListQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    page = fields.Int(load_default=1); per_page = fields.Int(load_default=50)
    template_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(TEMPLATE_TYPES))
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(FORM_STATUSES))
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

# ════════════════════════ SUBMISSION ════════════════════════

class SubmissionResponseSchema(Schema):
    class Meta: unknown = EXCLUDE
    field_id = fields.Str(required=True, validate=validate.Length(min=1, max=50))
    field_label = fields.Str(required=False, allow_none=True)
    value = fields.Raw(required=True)  # string, list, number, bool
    field_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(FIELD_TYPES))

class FormSubmitSchema(Schema):
    class Meta: unknown = EXCLUDE
    form_id = fields.Str(required=True, validate=validate_objectid)
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    responses = fields.List(fields.Nested(SubmissionResponseSchema), required=True, validate=validate.Length(min=1))
    member_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    submitter_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=200))
    submitter_email = fields.Email(required=False, allow_none=True)
    is_anonymous = fields.Bool(load_default=False)
    submission_time_seconds = fields.Int(required=False, allow_none=True, validate=lambda x: x >= 0 if x is not None else True)

class SubmissionIdQuerySchema(Schema):
    submission_id = fields.Str(required=True, validate=[validate.Length(min=1, max=36), validate_objectid])
    branch_id = fields.Str(required=True, validate=validate_objectid)

class SubmissionListQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid, error_messages={"required": "branch_id is required"})
    form_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    member_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    start_date = fields.Str(required=False, allow_none=True)
    end_date = fields.Str(required=False, allow_none=True)
    page = fields.Int(load_default=1); per_page = fields.Int(load_default=50)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

class FormAnalyticsQuerySchema(Schema):
    form_id = fields.Str(required=True, validate=validate_objectid)
    branch_id = fields.Str(required=True, validate=validate_objectid)

# ════════════════════════ STORAGE QUOTA ════════════════════════

class StorageQuotaQuerySchema(Schema):
    branch_id = fields.Str(required=True, validate=validate_objectid)

class StorageQuotaUpdateSchema(Schema):
    class Meta: unknown = EXCLUDE
    branch_id = fields.Str(required=True, validate=validate_objectid)
    package = fields.Str(required=True, validate=validate.OneOf(PACKAGES))
    
class StorageAddonPurchaseSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    addon_gb = fields.Int(
        required=True,
        validate=validate.OneOf([5, 10, 25, 50, 100]),
        error_messages={"required": "Storage amount is required"},
    )
    billing_period = fields.Str(load_default="monthly", validate=validate.OneOf(["monthly", "annually"]))

# ════════════════════════ FILE UPLOAD ════════════════════════

class FileUploadQuerySchema(Schema):
    class Meta: unknown = EXCLUDE
    form_id = fields.Str(required=True, validate=validate_objectid)
    branch_id = fields.Str(required=True, validate=validate_objectid)
    field_id = fields.Str(required=True, validate=validate.Length(min=1, max=50))
