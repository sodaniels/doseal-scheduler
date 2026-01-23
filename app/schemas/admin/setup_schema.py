import re
import uuid
from marshmallow import Schema, fields, validate,validates_schema, ValidationError
from werkzeug.datastructures import FileStorage

from ...utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date, validate_objectid
)

# Store Schema Class
class StoreSchema(Schema):
    id = fields.Int(dump_only=True)  # Auto-generated ID, will be populated by the database

    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=200),
        error_messages={"required": "Store name is required", "min_length": "Store name must be at least 2 characters"}
    )
    phone = fields.Str(
        required=True,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    address1 = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Address 1 is required", "min_length": "Address must be at least 5 characters"}
    )
    address2 = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Address2 must be a string"}
    )
    code = fields.Str(
        required=False,
        validate=validate.Length(min=3, max=10),
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    city = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "City must be a string"}
    )
    town = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Town must be a string"}
    )
    postal_code = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Postal code must be a string"}
    )
    receipt_header = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Receipt header must be a string"}
    )
    receipt_footer = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Receipt footer must be a string"}
    )
    tax = fields.Str(
        required=False,
        validate=validate_tax,
        error_messages={"invalid": "Invalid tax value"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class StoreUpdateSchema(Schema):

    store_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Store ID is required", "min_length": "Store Id must be at least 5 characters"}
    )
    name = fields.Str(
        required=False,
        validate=validate.Length(min=2, max=200),
        error_messages={"required": "Store name is required", "min_length": "Store name must be at least 2 characters"}
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    address1 = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Address 1 is required", "min_length": "Address must be at least 5 characters"}
    )
    address2 = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Address2 must be a string"}
    )
    code = fields.Str(
        required=False,
        validate=validate.Length(min=3, max=10),
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    city = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "City must be a string"}
    )
    town = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Town must be a string"}
    )
    postal_code = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Postal code must be a string"}
    )
    receipt_header = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Receipt header must be a string"}
    )
    receipt_footer = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Receipt footer must be a string"}
    )
    tax = fields.Str(
        required=False,
        validate=validate_tax,
        error_messages={"invalid": "Invalid tax value"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )

# Unit Schema Class
class UnitSchema(Schema):

    unit = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "min_length": "Unit must be at least 1 characters"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "invalid": "Unit name"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class UnitUpdateSchema(Schema):

    unit_id = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Unit_id is required", "invalid": "Unit id"},
        description="The user_id of the user to fetch details."
        )
    unit = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "min_length": "Unit must be at least 1 characters"}
    )
    name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "invalid": "Unit name"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Unit Schema Class

# Category schemas
class CategorySchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Category name is required", "invalid": "Category name"}
    )
    slug = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Slug is required", "min_length": "Slug must be at least 1 character"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class CategoryUpdateSchema(Schema):

    category_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "category_id is required", "invalid": "Category id"}
        )
    name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Category name is required", "invalid": "Category name"}
    )
    slug = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Slug is required", "min_length": "Slug must be at least 1 character"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Category schemas

# SubCategory schemas
class SubCategorySchema(Schema):
    category_id = fields.Str(
            required=True,
            validate=[validate.Length(min=1, max=36), validate_objectid],
            error_messages={"required": "Category ID is required", "invalid": "Category ID"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "SubCategory name is required", "invalid": "Category name"}
    )
   
    code = fields.Str(
        required=False,
        validate=validate.Length(min=3, max=10),
    )
    
    description = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Address2 must be a string"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SubCategoryUpdateSchema(Schema):
    
    subcategory_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Subcategory ID is required", "invalid": "Subcategory ID"}
    )
    name = fields.Str(
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "SubCategory name is required", "invalid": "Category name"}
    )
   
    code = fields.Str(
        required=False,
        validate=validate.Length(min=3, max=10),
    )
    
    description = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Address2 must be a string"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# SubCategory schemas

# Brand schemas
class BrandSchema(Schema):
    
    brand_id = fields.Str(
            required=False,
            allow_none=True,
            validate=validate.Length(min=1, max=50),
            error_messages={"required": "Brand ID is required", "invalid": "Brand ID"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Brand name is required", "invalid": "Brand name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class BrandUpdateSchema(Schema):
    
    brand_id = fields.Str(
            required=True,
            validate=[validate.Length(min=1, max=36), validate_objectid],
            error_messages={"required": "Brand ID is required", "invalid": "Brand ID"}
    )
    name = fields.Str(
        required=False,
        allow_empty=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Brand name is required", "invalid": "Brand name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

#Brand schemas 

# Variant schemas
class VariantSchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "invalid": "Unit name"}
    )
    values = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Values name is required", "min_length": "Values must be at least 1 characters"}
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class VariantUpdateSchema(Schema):

    variant_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Variant Id is required", "invalid": "Variant Id"}
    )
    name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Variant name is required", "invalid": "Variant name"}
    )
    values = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Values name is required", "min_length": "Values must be at least 1 characters"}
    )
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# Variant schemas 

# Tax schemas
class TaxSchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Tax name is required", "invalid": "Tax name"}
    )
    rate = fields.Float(
        required=True,
        error_messages={"required": "Rate name is required", "min_length": "Rate must be at least 1 characters"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class TaxUpdateSchema(Schema):
    tax_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Tax Id is required", "invalid": "Tax Id"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Tax name is required", "invalid": "Tax name"}
    )
    rate = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=5),
        error_messages={"required": "Tax rate is required", "min_length": "Tax rate be at least 1 characters"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# Tax schemas 

# Composite Variant
class CompositeVariantSchema(Schema):

    thumbnail = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Thumbnail must be a valid file"}
    )
    barcode_symbology = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Barcode Symbology is required", "invalid": "Barcode Symbology"}
    )
    code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    image = fields.List(
        fields.Raw(
            required=False,
            allow_none=True,
            validate=validate_image,
            error_messages={"invalid": "Image must be a valid file"}
        ),
        required=False,
        allow_none=True,
        error_messages={"invalid": "Image must be a list of valid files"}
    )
    quantity = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    quantity_alert = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    tax_type = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    tax = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=5),
    )
    discount_type = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    discount_value = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Composite Variant

# Warranty Schema
class WarrantySchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Warranty name is required", "invalid": "Warranty name"}
    )
    duration = fields.Int(
        required=True,
        validate=validate.Range(min=1, max=50),
        error_messages={
            "required": "Duration is required", 
            "null": "Duration cannot be null", 
            "invalid": "Duration must be an integer",
            "min": "Duration must be at least 1", 
            "max": "Duration must be at most 5"
        }
    )
    period = fields.Str(
        required=True,
        validate=validate.OneOf(["Month", "Year"]),
        error_messages={"required": "Period is required", "min_length": "Duration must be at least 1 characters"}
    )
    description = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Description must be a string"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class WarrantyUpdateSchema(Schema):

    warranty_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Warranty ID is required", "invalid": "Warranty ID"}
    )
    name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    duration = fields.Int(
        required=False,
        allow_none=True,
        validate=validate.Range(min=1, max=50),
        error_messages={
            "null": "Duration cannot be null", 
            "invalid": "Duration must be an integer",
            "min": "Duration must be at least 1", 
            "max": "Duration must be at most 5"
        }
    )
    period = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(["Month", "Year"]),
        error_messages={"min_length": "Duration must be at least 1 characters"}
    )
    description = fields.Str(
        required=False,
        allow_none=True,
        error_messages={"invalid": "Description must be a string"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# Warranty Schema 

#Supplier Schema
class SupplierSchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "invalid": "Unit name"}
    )
    description = fields.Str(
        required=False,
        allow_none=True,
    )
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
    )
    last_name = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    company = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    email = fields.Email(
        required=False,
        allow_none=True,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={ "invalid": "Invalid phone number"}
    )
    fax = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    website = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    twitter = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    street = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    suburb = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    city = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    state = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    zipcode = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    country = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SupplierUpdateSchema(Schema):

    supplier_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Supplier ID is required", "invalid": "Supplier ID"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Unit name is required", "invalid": "Unit name"}
    )
    description = fields.Str(
        required=False,
        allow_none=True,
    )
    first_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
    )
    last_name = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
    )
    company = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    email = fields.Email(
        required=False,
        allow_none=True,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={ "invalid": "Invalid phone number"}
    )
    fax = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    website = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    twitter = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    street = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    suburb = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    city = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    state = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    zipcode = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    country = fields.Str(
        required=True,
        allow_none=True,
        validate=validate.Length(min=1, max=100),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
#Supplier Schema 

# Tag Schema
class TagSchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Tag name is required", "invalid": "Tag name"}
    )
    Number_of_products = fields.Int(
        required=False,
        default=0,  # Default value if not provided
        validate=lambda value: isinstance(value, int) or value == 0,  # Ensure it's an integer or 0
        error_messages={"invalid": "Number of products must be an integer."}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class TagUpdateSchema(Schema):
    tag_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Tax Id is required", "invalid": "Tax Id"}
    )
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Tag name is required", "invalid": "Tag name"}
    )
    Number_of_products = fields.Int(
        required=False,
        default=0,  # Default value if not provided
        validate=lambda value: isinstance(value, int) or value == 0,  # Ensure it's an integer or 0
        error_messages={"invalid": "Number of products must be an integer."}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

#Tag Schema

# Gift Card Schema 
class GiftCardSchema(Schema):

    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Gift card name is required", "invalid": "Gift card"}
    )
    customer_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Customer ID is required", "min_length": "Customer ID must be at least 1 characters"}
    )
    issue_date = fields.Str(
        required=True,
        error_messages={"required": "Issue date is required", "invalid": "Issue date"}
    )
    
    expiry_date = fields.Str(
        required=True,
        validate=validate_future_on, 
        error_messages={"required": "Expiry date is required", "invalid": "Expiry date"}
    )
    amount = fields.Int(
        required=True,
        error_messages={"required": "Amount is required"}
    )
    reference = fields.Str(
        required=False,
        allow_none = True,
        validate=validate.Length(min=16, max=16),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class GiftCardUpdateSchema(Schema):
    gift_card_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Gift Card ID is required", "min_length": "Gift Card ID must be at least 1 characters"}
    )
    name = fields.Str(
        required=False,
        allow_none = True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Gift card name is required", "invalid": "Gift card"}
    )
    customer_id = fields.Str(
        required=False,
        allow_none = True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Customer ID is required", "min_length": "Customer ID must be at least 1 characters"}
    )
    issue_date = fields.Str(
        required=False,
        allow_none = True,
        error_messages={"required": "Issue date is required", "invalid": "Issue date"}
    )
    
    expiry_date = fields.Str(
        required=False,
        allow_none = True,
        validate=validate_future_on, 
        error_messages={"required": "Expiry date is required", "invalid": "Expiry date"}
    )
    amount = fields.Int(
        required=False,
        allow_none = True,
        error_messages={"required": "Amount is required"}
    )
    reference = fields.Str(
        required=False,
        allow_none = True,
        validate=validate.Length(min=16, max=16),
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  # Set "Active" as the default value
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# Gift Card Schema

# Outlets and Register
class OutletSchema(Schema):

    location = fields.List(
        fields.Dict(
            required=True,
            validate=validate.Length(min=1),  # Add length validation for the dictionary
        ),
        required=False
    )
    
    time_zone = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Time Zone is required", "min_length": "Time Zone must be at least 1 characters"}
    )
    
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet name is required"}
    )
    
    registers = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=True,
        allow_none=True,
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class OutletUpdateSchema(Schema):
    outlet_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Outlet is required", "min_length": "Outlet must be at least 1 characters"}
    )
    location = fields.List(
        fields.Dict(
            required=False,
            validate=validate.Length(min=1),  # Add length validation for the dictionary
        ),
        required=False
    )
    
    time_zone = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Time Zone is required", "min_length": "Time Zone must be at least 1 characters"}
    )
    
    name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet name is required"}
    )
    
    registers = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=False,
        allow_none=True,
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# Outlets and Register

# Receipt Template schema
class ReceiptTemplateSchema(Schema):
    name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Template name is required", "min_length": "Template name must be at least 1 characters"}
    )
    location = fields.List(
        fields.Dict(
            required=False,
            validate=validate.Length(min=1),  # Add length validation for the dictionary
        ),
        required=False
    )
    
    time_zone = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Time Zone is required", "min_length": "Time Zone must be at least 1 characters"}
    )
    
    name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet name is required"}
    )
    
    registers = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=True,
        allow_none=True,
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# Receipt Template schema

#-----------------------BUSINESS LOCATION -----------------------------------------
class BusinessLocationSchema(Schema):
    
    name = fields.Str(
        required=True,
        validate=validate.Length(min=2, max=200), 
        error_messages={"invalid": "Location name is required"}
    )
    location_id = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=36), 
    )
    city = fields.Str(
        required=True, 
        error_messages={"required": "City is required", "invalid": "City is required"}
    )
    
    state = fields.Str(
        required=True, 
        error_messages={"required": "State is required", "invalid": "State is required"}
    )
    phone = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Phone Number"}
    )
    email = fields.Email(
        required=True, 
        validate=validate.Length(min=5, max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    landmark = fields.Str(
        required=True, 
        error_messages={"required": "Post Code is required", "invalid": "Post Code is required"}
    )
    invoice_scheme_for_pos = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice scheme for POS is required", "invalid": "Invoice scheme for POS is required"}
    )
    invoice_layout_for_pos = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice layout for POS is required", "invalid": "Invoice layout for POS is required"}
    )
    default_selling_price_group = fields.Str(
        validate=[validate.Length(min=1, max=36), validate_objectid],
    )
    landmark = fields.Str(
        required=False, 
        allow_none=True,
    )
    post_code = fields.Str(
        required=True, 
        error_messages={"required": "Post code is required", "invalid": "Post code is required"}
    )
    country = fields.Str(
        required=True, 
        error_messages={"required": "Country is required", "invalid": "Country is required"}
    )
    alternate_contact_number = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Contact Number"}
    )
    website = fields.Str(
        required=False, 
        allow_none=True,
    )
    invoice_scheme_for_sale = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice scheme for sale is required", "invalid": "Invoice scheme for sale is required"}
    )
    invoice_layout_for_sale = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice layout for sale is required", "invalid": "Invoice layout for sale is required"}
    )
    pos_screen_featured_products = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=False,
        allow_none=True,
    )
    # Payment methods
    payment_options = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            error_messages={
                "required": "Role details are required",
                "invalid": "Role must be a valid array with view, add, edit, and delete as keys"
            },
            default=[{
                "Cassh": "0",
                "Card": "0",
                "Check": "0",
                "Bank Transfer": "0",
                "Other": "0"
            }]
        ),
        required=False,
        allow_none=True,
        error_messages={
            "required": "Role is required",
            "invalid": "Role must be a valid array"
        }
    )
    status = fields.Str(
        required=False,
        default="Active",
        allow_none=True
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class BusinessLocationUpdateSchema(Schema):
    business_location_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business location is required"}
    )
    name = fields.Str(
        required=False,
    )
    location_id = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=36), 
    )
    city = fields.Str(
        required=True, 
        error_messages={"required": "City is required", "invalid": "City is required"}
    )
    
    state = fields.Str(
        required=True, 
        error_messages={"required": "State is required", "invalid": "State is required"}
    )
    phone = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Phone Number"}
    )
    email = fields.Email(
        required=True, 
        validate=validate.Length(min=5, max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    landmark = fields.Str(
        required=True, 
        error_messages={"required": "Post Code is required", "invalid": "Post Code is required"}
    )
    invoice_scheme_for_pos = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice scheme for POS is required", "invalid": "Invoice scheme for POS is required"}
    )
    invoice_layout_for_pos = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice layout for POS is required", "invalid": "Invoice layout for POS is required"}
    )
    default_selling_price_group = fields.Str(
        validate=[validate.Length(min=1, max=36), validate_objectid],
    )
    landmark = fields.Str(
        required=False, 
        allow_none=True,
    )
    post_code = fields.Str(
        required=True, 
        error_messages={"required": "Post code is required", "invalid": "Post code is required"}
    )
    country = fields.Str(
        required=True, 
        error_messages={"required": "Country is required", "invalid": "Country is required"}
    )
    alternate_contact_number = fields.Str(
        required=False,
        validate=validate.Length(min=10, max=15), 
        error_messages={"invalid": "Invalid Contact Number"}
    )
    website = fields.Str(
        required=False, 
        allow_none=True,
    )
    invoice_scheme_for_sale = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice scheme for sale is required", "invalid": "Invoice scheme for sale is required"}
    )
    invoice_layout_for_sale = fields.Str(
        required=True, 
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Invoice layout for sale is required", "invalid": "Invoice layout for sale is required"}
    )
    pos_screen_featured_products = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=False,
        allow_none=True,
    )
    # Payment methods
    payment_options = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            error_messages={
                "required": "Role details are required",
                "invalid": "Role must be a valid array with view, add, edit, and delete as keys"
            },
            default=[{
                "Cassh": "0",
                "Card": "0",
                "Check": "0",
                "Bank Transfer": "0",
                "Other": "0"
            }]
        ),
        required=False,
        allow_none=True,
        error_messages={
            "required": "Role is required",
            "invalid": "Role must be a valid array"
        }
    )
    status = fields.Str(
        required=False,
        default="Active",
        allow_none=True
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

#-----------------------BUSINESS LOCATION -----------------------------------------

class CompositeVariantIdQuerySchema(Schema):
    """
    Query schema for fetching/deleting a single composite variant.

    Used in:
      - GET /compositvariant?variant_id=...&business_id=...
      - DELETE /compositvariant?variant_id=...&business_id=...
    """
    composit_variant_id = fields.String(required=True)
    business_id = fields.String(load_default=None)  # optional override for SYS_OWNER / SUPER_ADMIN


class CompositeVariantSchema(Schema):
    """
    Main schema for creating / returning a CompositeVariant.
    Used for POST body and GET response.
    """

    # Identifiers
    variant_id = fields.String(dump_only=True)
    business_id = fields.String(load_default=None)   # optional in POST for SYS_OWNER / SUPER_ADMIN
    user_id = fields.String(load_default=None)
    user__id = fields.String(load_default=None)

    # Core variant values (e.g. combination of attributes: size/color/etc.)
    # Stored encrypted; can be list/dict/string – so keep it flexible.
    values = fields.Raw(required=True)

    # Status / meta
    status = fields.String(load_default="Active")

    # Visuals / codes
    thumbnail = fields.String(allow_none=True, load_default=None)
    barcode_symbology = fields.String(allow_none=True, load_default=None)
    code = fields.String(allow_none=True, load_default=None)
    image = fields.String(allow_none=True, load_default=None)

    # Inventory-related
    quantity = fields.String(allow_none=True, load_default=None)
    quantity_alert = fields.String(allow_none=True, load_default=None)

    # Tax / discount
    tax_type = fields.String(allow_none=True, load_default=None)
    tax = fields.String(allow_none=True, load_default=None)
    discount_type = fields.String(allow_none=True, load_default=None)
    discount_value = fields.String(allow_none=True, load_default=None)

    # File system path for image
    file_path = fields.String(allow_none=True, load_default=None)

    # Timestamps
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class CompositeVariantUpdateSchema(Schema):
    """
    Schema for PATCHing an existing CompositeVariant.
    Only `variant_id` is required; all other fields are optional.
    """

    # Required to identify the variant
    composit_variant_id = fields.String(required=True)

    # Optional business override for SYS_OWNER / SUPER_ADMIN
    business_id = fields.String(load_default=None)

    # Optional fields to update
    values = fields.Raw(load_default=None)
    status = fields.String(load_default=None)

    thumbnail = fields.String(allow_none=True, load_default=None)
    barcode_symbology = fields.String(allow_none=True, load_default=None)
    code = fields.String(allow_none=True, load_default=None)
    image = fields.String(allow_none=True, load_default=None)

    quantity = fields.String(allow_none=True, load_default=None)
    quantity_alert = fields.String(allow_none=True, load_default=None)

    tax_type = fields.String(allow_none=True, load_default=None)
    tax = fields.String(allow_none=True, load_default=None)
    discount_type = fields.String(allow_none=True, load_default=None)
    discount_value = fields.String(allow_none=True, load_default=None)

    file_path = fields.String(allow_none=True, load_default=None)



class StoreQuerySchema(Schema):
    store_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        description="The store_id of the store to fetch detail."
    )

class BusinessIdAndUserIdQuerySchema(Schema):
    user_id = fields.Str(
        required=False, 
        description="The user_id of the user to fetch details."
    )
    business_id = fields.Str(
        required=False, 
        description="The business_id of the store to fetch details."
    )
    page = fields.Str(
        required=False, 
        allow_none=True
    )
    per_page = fields.Str(
        required=False, 
        allow_none=True
    )
    

    # @validates_schema
    # def validate_at_least_one(self, data, **kwargs):
    #     if not data.get("user_id") and not data.get("business_id"):
    #         raise ValidationError(
    #             "At least one of 'user_id' or 'business_id' must be provided."
    #         )

class UnitQuerySchema(Schema):
    unit_id = fields.Str(required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        description="The unit_id of the unit to fetch detail.")
    business_id = fields.Str(required=False, description="The business_id of the store to fetch details.")

class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(
        required=True, 
       validate=[validate.Length(min=1, max=36), validate_objectid],
        description="The business_id of the store to fetch details."
    )

class UnitQueryUnitIdSchema(Schema):
    unit_id = fields.Str(required=True, validate=validate_objectid, description="The unit_id of the unit to fetch detail.")
 
class CategoryIdQuerySchema(Schema):
    category_id = fields.Str(required=True, validate=validate_objectid, description="The Category_id of the category to fetch detail.")
 
class SubCategoryIdQuerySchema(Schema):
    subcategory_id = fields.Str(required=True,validate=validate_objectid, description="The SubCategory_id of the category to fetch detail.")
 # Brand id

class BrandIdQuerySchema(Schema):
    brand_id = fields.Str(required=True, validate=validate_objectid, description="The brand ID of the brand to fetch detail.")
# Varient id
class VariantIdQuerySchema(Schema):
    variant_id = fields.Str(required=True, validate=validate_objectid, description="The Variant ID of the variant to fetch detail.")
 # Tax ID
class TaxIdQuerySchema(Schema):
    tax_id = fields.Str(required=True, validate=validate_objectid, description="The Tax ID of the Tax to fetch detail.")
 # Warranty ID

class WarrantyIdQuerySchema(Schema):
    warranty_id = fields.Str(required=True, validate=validate_objectid, description="The Warranty ID of the Warranty to fetch detail.")
 # Supplier ID
class SupplierIdQuerySchema(Schema):
    supplier_id = fields.Str(required=True, validate=validate_objectid, description="Supplier ID of the Supplier to fetch detail.")
# Tag ID
class TagIdQuerySchema(Schema):
    tag_id = fields.Str(required=True, validate=validate_objectid, description="Tag ID of the Tag to fetch detail.")
# Gift Card ID
class GiftCardIdQuerySchema(Schema):
    gift_card_id = fields.Str(required=True, validate=validate_objectid, description="Gift Card ID of the Gift Card to fetch detail.")
 # Outlets 

class OutletIdQuerySchema(Schema):
    outlet_id = fields.Str(required=True, validate=validate_objectid, description="Outlet ID of the Outletto fetch detail.")
    
class BusinessLocationQuerySchema(Schema):
    business_location_id = fields.Str(required=True, validate=validate_objectid, description="Business Location ID of the data fetch detail.")
    
 