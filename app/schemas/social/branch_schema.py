# schemas/church/branch_schema.py

from marshmallow import Schema, fields, validate, EXCLUDE
from ...utils.validation import validate_objectid


# ─────────────────────────────────────────
# Enums
# ─────────────────────────────────────────

BRANCH_TYPES = ["Main", "Branch", "Campus", "Parish", "Satellite", "Online"]
STATUSES = ["Active", "Inactive", "Closed", "Pending", "Archived"]

DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


# ─────────────────────────────────────────
# Nested: service time entry
# ─────────────────────────────────────────

class ServiceTimeSchema(Schema):
    """Single service time entry."""
    class Meta:
        unknown = EXCLUDE

    day = fields.Str(required=True, validate=validate.OneOf(DAYS_OF_WEEK))
    time = fields.Str(required=True, validate=validate.Length(min=3, max=10))  # e.g. "09:00"
    label = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))  # e.g. "First Service"


# ─────────────────────────────────────────
# Create Branch
# ─────────────────────────────────────────

class BranchCreateSchema(Schema):
    """Schema for creating a new branch / campus / parish."""
    class Meta:
        unknown = EXCLUDE

    # ── Required ──
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"required": "Branch name is required"},
    )

    # ── Identifiers ──
    code = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))

    # ── Type & status ──
    branch_type = fields.Str(load_default="Branch", validate=validate.OneOf(BRANCH_TYPES))
    status = fields.Str(load_default="Active", validate=validate.OneOf(STATUSES))

    # ── Hierarchy ──
    parent_branch_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    region = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    district = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))

    # ── Address ──
    address_line_1 = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    address_line_2 = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    city = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    state_province = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    country = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    latitude = fields.Float(required=False, allow_none=True)
    longitude = fields.Float(required=False, allow_none=True)
    timezone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=50))

    # ── Contact ──
    phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    email = fields.Email(required=False, allow_none=True)

    # ── Leadership ──
    pastor_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    pastor_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=150))
    contact_person_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=150))
    contact_person_phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))

    # ── Service schedule ──
    service_times = fields.List(
        fields.Nested(ServiceTimeSchema),
        required=False,
        load_default=[],
    )

    # ── Capacity & metadata ──
    seating_capacity = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    year_established = fields.Int(required=False, allow_none=True, validate=lambda x: 1800 <= x <= 2100 if x is not None else True)
    logo_url = fields.Url(required=False, allow_none=True)
    cover_photo_url = fields.Url(required=False, allow_none=True)

    # ── Settings ──
    currency = fields.Str(required=False, allow_none=True, validate=validate.Length(equal=3))
    language = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))

    # ── Display ──
    display_order = fields.Int(load_default=0)
    is_headquarters = fields.Bool(load_default=False)


# ─────────────────────────────────────────
# Update Branch (partial)
# ─────────────────────────────────────────

class BranchUpdateSchema(Schema):
    """Schema for updating an existing branch (partial updates)."""
    class Meta:
        unknown = EXCLUDE

    branch_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Branch ID is required"},
    )

    name = fields.Str(required=False, allow_none=True, validate=validate.Length(min=1, max=200))
    code = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    description = fields.Str(required=False, allow_none=True, validate=validate.Length(max=1000))

    branch_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(BRANCH_TYPES))
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))

    parent_branch_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    region = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    district = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))

    address_line_1 = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    address_line_2 = fields.Str(required=False, allow_none=True, validate=validate.Length(max=255))
    city = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    state_province = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    postal_code = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    country = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    latitude = fields.Float(required=False, allow_none=True)
    longitude = fields.Float(required=False, allow_none=True)
    timezone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=50))

    phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))
    email = fields.Email(required=False, allow_none=True)

    pastor_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    pastor_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=150))
    contact_person_name = fields.Str(required=False, allow_none=True, validate=validate.Length(max=150))
    contact_person_phone = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))

    service_times = fields.List(fields.Nested(ServiceTimeSchema), required=False, allow_none=True)

    seating_capacity = fields.Int(required=False, allow_none=True, validate=lambda x: x > 0 if x is not None else True)
    year_established = fields.Int(required=False, allow_none=True, validate=lambda x: 1800 <= x <= 2100 if x is not None else True)
    logo_url = fields.Url(required=False, allow_none=True)
    cover_photo_url = fields.Url(required=False, allow_none=True)

    currency = fields.Str(required=False, allow_none=True, validate=validate.Length(equal=3))
    language = fields.Str(required=False, allow_none=True, validate=validate.Length(max=20))

    display_order = fields.Int(required=False, allow_none=True)
    is_headquarters = fields.Bool(required=False, allow_none=True)


# ─────────────────────────────────────────
# Query schemas
# ─────────────────────────────────────────

class BranchIdQuerySchema(Schema):
    """Query a single branch by ID."""
    branch_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Branch ID is required"},
    )
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)


class BranchListQuerySchema(Schema):
    """Query params for listing branches."""
    class Meta:
        unknown = EXCLUDE

    page = fields.Int(load_default=1, validate=lambda x: x >= 1)
    per_page = fields.Int(load_default=50, validate=lambda x: 1 <= x <= 200)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)

    # Filters
    status = fields.Str(required=False, allow_none=True, validate=validate.OneOf(STATUSES))
    branch_type = fields.Str(required=False, allow_none=True, validate=validate.OneOf(BRANCH_TYPES))
    parent_branch_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)
    region = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    district = fields.Str(required=False, allow_none=True, validate=validate.Length(max=100))
    include_archived = fields.Bool(load_default=False)


class BranchSearchQuerySchema(Schema):
    """Query params for searching branches."""
    search = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"required": "Search term is required"},
    )
    page = fields.Int(load_default=1, validate=lambda x: x >= 1)
    per_page = fields.Int(load_default=50, validate=lambda x: 1 <= x <= 200)
    business_id = fields.Str(required=False, allow_none=True, validate=validate_objectid)


class BranchArchiveSchema(Schema):
    """Schema for archiving or restoring a branch."""
    branch_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Branch ID is required"},
    )
