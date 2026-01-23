
# schemas/product_schemas.py
import json
from marshmallow import (
    Schema, fields, validate, validates_schema, ValidationError
)

from ...utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date, validate_date_format, validate_objectid
)


class ProductSchema(Schema):
    """Schema for creating a product."""
    
    # Required fields
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    product_type = fields.Str(
        required=True,
        validate=validate.OneOf(["Single", "Variable", "Combo"])
    )
    
    # Optional core fields
    brand = fields.Str(allow_none=True)
    description = fields.Str(allow_none=True)
    tags = fields.List(fields.Str(), allow_none=True)
    category = fields.Str(allow_none=True)
    subcategory = fields.Str(allow_none=True)
    unit = fields.Str(allow_none=True)
    
    # POS and inventory settings
    sell_on_point_of_sale = fields.Int(
        allow_none=True,
        validate=validate.OneOf([0, 1]),
        dump_default=1
    )
    track_inventory = fields.Int(
        allow_none=True,
        validate=validate.OneOf([0, 1]),
        dump_default=1
    )
    alert_quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))
    
    # Product identification
    sku = fields.Str(allow_none=True, validate=validate.Length(max=100))
    barcode_symbology = fields.Str(
        allow_none=True,
        validate=validate.OneOf([
            "Code128", "Code39", "EAN8", "EAN13", "UPC",
            "ITF14", "QR_Code", "None"
        ])
    )
    
    # Pricing and tax
    tax = fields.List(fields.Str(), allow_none=True)

    # NOTE: form-data string, e.g. '{"supply_price": 1000, "retail_price": 1100}'
    prices = fields.Str(allow_none=True)
    selling_price_group = fields.Str(allow_none=True)
    
    # Suppliers and location
    suppliers = fields.List(fields.Str(), allow_none=True)
    product_location = fields.Str(allow_none=True)
    
    # Variants (for variable products)
    variants = fields.List(fields.Str(), allow_none=True)
    
    # Composite products (for combo/bundle products)
    composite_product = fields.Raw(allow_none=True)
    
    # Product metadata
    status = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["Active", "Inactive"]),
        dump_default="Active"
    )
    warranty = fields.Str(allow_none=True)
    manufacturer = fields.Str(allow_none=True)
    manufactured_date = fields.DateTime(allow_none=True)
    expiry_on = fields.DateTime(allow_none=True)
    
    # Images (handled separately as file upload)
    images = fields.List(fields.Raw(type='file'), allow_none=True)
    
    # Role-aware business selection
    business_id = fields.Str(allow_none=True)

    @validates_schema
    def validate_prices(self, data, **kwargs):
        """
        For create:
        - prices may be omitted or null
        - if provided, must be JSON string like:
          {"supply_price": 1000, "retail_price": 1100}
        """
        raw_prices = data.get("prices")
        if raw_prices in (None, "", "null"):
            return

        # Parse JSON from the form-data string
        try:
            parsed = json.loads(raw_prices)
            if not isinstance(parsed, dict):
                raise ValidationError(
                    {"prices": ["'prices' must be a JSON object string."]}
                )
        except (ValueError, TypeError):
            raise ValidationError(
                {"prices": ["'prices' must be a valid JSON string."]}
            )

        required_keys = ("supply_price", "retail_price")
        missing = [k for k in required_keys if k not in parsed]
        if missing:
            raise ValidationError(
                {"prices": [f"'prices' must include keys: {', '.join(missing)}"]}
            )

        # Optional: type check for numeric values
        for key in required_keys:
            try:
                float(parsed[key])
            except (TypeError, ValueError):
                raise ValidationError(
                    {"prices": [f"'{key}' must be a numeric value."]}
                )

class ProductUpdateSchema(Schema):
    """Schema for updating a product."""
    
    product_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Product ID is required", "invalid": "Product ID"}
    )
    
    # All other fields optional
    name = fields.Str(allow_none=True, validate=validate.Length(min=1, max=200))
    product_type = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["Single", "Variable", "Combo"])
    )
    brand = fields.Str(allow_none=True)
    description = fields.Str(allow_none=True)
    tags = fields.List(fields.Str(), allow_none=True)
    category = fields.Str(allow_none=True)
    subcategory = fields.Str(allow_none=True)
    unit = fields.Str(allow_none=True)
    
    sell_on_point_of_sale = fields.Int(
        allow_none=True,
        validate=validate.OneOf([0, 1])
    )
    track_inventory = fields.Int(
        allow_none=True,
        validate=validate.OneOf([0, 1])
    )
    alert_quantity = fields.Float(allow_none=True, validate=validate.Range(min=0))
    
    sku = fields.Str(allow_none=True, validate=validate.Length(max=100))
    barcode_symbology = fields.Str(
        allow_none=True,
        validate=validate.OneOf([
            "Code128", "Code39", "EAN8", "EAN13", "UPC",
            "ITF14", "QR_Code", "None"
        ])
    )
    
    tax = fields.List(fields.Str(), allow_none=True)
    prices = fields.Str(allow_none=True)  # same as create
    selling_price_group = fields.Str(allow_none=True)
    
    suppliers = fields.List(fields.Str(), allow_none=True)
    product_location = fields.Str(allow_none=True)
    variants = fields.List(fields.Str(), allow_none=True)
    composite_product = fields.Raw(allow_none=True)
    
    status = fields.Str(
        allow_none=True,
        validate=validate.OneOf(["Active", "Inactive"])
    )
    warranty = fields.Str(allow_none=True)
    manufacturer = fields.Str(allow_none=True)
    manufactured_date = fields.DateTime(allow_none=True)
    expiry_on = fields.DateTime(allow_none=True)
    
    business_id = fields.Str(allow_none=True)

    @validates_schema
    def validate_prices(self, data, **kwargs):
        """
        For update:
        - if 'prices' not present at all → we don't touch it
        - if present (non-empty), must be JSON string with
          supply_price & retail_price
        """
        if "prices" not in data:
            return

        raw_prices = data.get("prices")
        if raw_prices in (None, "", "null"):
            return

        try:
            parsed = json.loads(raw_prices)
            if not isinstance(parsed, dict):
                raise ValidationError(
                    {"prices": ["'prices' must be a JSON object string."]}
                )
        except (ValueError, TypeError):
            raise ValidationError(
                {"prices": ["'prices' must be a valid JSON string."]}
            )

        required_keys = ("supply_price", "retail_price")
        missing = [k for k in required_keys if k not in parsed]
        if missing:
            raise ValidationError(
                {"prices": [f"'prices' must include keys: {', '.join(missing)}"]}
            )

        for key in required_keys:
            try:
                float(parsed[key])
            except (TypeError, ValueError):
                raise ValidationError(
                    {"prices": [f"'{key}' must be a numeric value."]}
                )

class ProductIdQuerySchema(Schema):
    """Query schema for single product retrieval."""
    product_id = fields.Str(required=True)
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER


class BusinessIdAndUserIdQuerySchema(Schema):
    """Query schema for product listing with role-aware filters."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    user_id = fields.Str(allow_none=True)  # For filtering by creator
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class POSProductsQuerySchema(Schema):
    """Query schema for POS product listing."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(allow_none=True)  # For outlet-specific filtering
    category_id = fields.Str(allow_none=True)  # Filter by category
    search_term = fields.Str(allow_none=True, validate=validate.Length(max=100))  # Search name/sku
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class BusinessIdAndUserIdQuerySchema(Schema):
    """Query schema for product listing with role-aware filters."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    user_id = fields.Str(allow_none=True)  # For filtering by creator
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class POSProductsQuerySchema(Schema):
    """Query schema for POS product listing."""
    business_id = fields.Str(allow_none=True)  # For SUPER_ADMIN/SYSTEM_OWNER
    outlet_id = fields.Str(allow_none=True)  # For outlet-specific filtering
    category_id = fields.Str(allow_none=True)  # Filter by category
    search_term = fields.Str(allow_none=True, validate=validate.Length(max=100))  # Search name/sku
    page = fields.Int(allow_none=True, validate=validate.Range(min=1), dump_default=1)
    per_page = fields.Int(allow_none=True, validate=validate.Range(min=1, max=100), dump_default=50)


class ProductImportItemSchema(Schema):
    name = fields.Str(required=True, validate=validate.Length(min=1, max=200))
    product_type = fields.Str(required=True, validate=validate.OneOf(["Single", "Variable", "Combo"]))

    sku = fields.Str(allow_none=True)
    brand = fields.Str(allow_none=True)
    category = fields.Str(allow_none=True)
    subcategory = fields.Str(allow_none=True)
    unit = fields.Str(allow_none=True)

    sell_on_point_of_sale = fields.Int(allow_none=True, validate=validate.OneOf([0, 1]))
    track_inventory = fields.Int(allow_none=True, validate=validate.OneOf([0, 1]))
    alert_quantity = fields.Float(allow_none=True)

    status = fields.Str(allow_none=True, validate=validate.OneOf(["Active", "Inactive"]))
    prices = fields.Raw(allow_none=True)  # accept dict OR JSON string
    tax = fields.Raw(allow_none=True)     # accept list OR CSV string
    tags = fields.Raw(allow_none=True)    # accept list OR CSV string
    suppliers = fields.Raw(allow_none=True)

    # stock import option
    opening_stock = fields.Float(allow_none=True)
    outlet_id = fields.Str(allow_none=True)

    @validates_schema
    def normalize_payload(self, data, **kwargs):
        # Convert prices JSON string -> dict
        if isinstance(data.get("prices"), str):
            try:
                data["prices"] = json.loads(data["prices"])
            except Exception:
                raise ValidationError({"prices": ["prices must be a JSON object or dict"]})

        # Convert "a,b,c" -> ["a","b","c"]
        for k in ["tax", "tags", "suppliers"]:
            v = data.get(k)
            if isinstance(v, str):
                data[k] = [x.strip() for x in v.split(",") if x.strip()]

# ------------------PRODUCT SALES-----------------------------

# Define allowed statuses and sale types centrally
SALE_STATUS_CHOICES = (
    "Draft",
    "PendingPayment",
    "Completed",
    "Closed",
    "Voided",
    "Refunded",
    "PartiallyRefunded",
)

SALE_TYPE_CHOICES = (
    "SALE",
    "REFUND",
    "RETURN",
    "ADJUSTMENT",
    "VOID",
)


class SaleSchema(Schema):
    customer_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Customer ID is required",
            "invalid": "Invalid Customer ID. Ensure you add a valid customer ID."
        }
    )

    supplier_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Supplier ID is required",
            "invalid": "Invalid Supplier ID. Ensure you add a valid supplier ID."
        }
    )

    product_ids = fields.List(
        fields.Str(
            validate=[validate.Length(min=1, max=36), validate_objectid],
        ),
        required=True,
        error_messages={
            "required": "Product IDs are required",
            "invalid": "Product IDs must be a valid array of product ObjectIds"
        }
    )

    date = fields.Str(
        required=True,
        validate=validate_date_format,
        error_messages={
            "required": "Date is required",
            "invalid": "Date is required and must be in a valid format"
        }
    )

    purchase_price = fields.Float(required=False, allow_none=True, default=0.0)
    order_tax = fields.Float(required=False, allow_none=True, default=0.0)
    discount = fields.Float(required=False, allow_none=True, default=0.0)
    shipping = fields.Float(required=False, allow_none=True, default=0.0)
    grand_total = fields.Float(required=False, allow_none=True, default=0.0)

    # Lifecycle + type
    status = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(SALE_STATUS_CHOICES),
        default="Draft",
    )

    sale_type = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(SALE_TYPE_CHOICES),
        default="SALE",
    )

    # For REFUND / RETURN / ADJUSTMENT transactions
    original_sale_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "invalid": "Invalid original_sale_id. Ensure you add a valid sale ID."
        }
    )

    # Optional metadata / notes / reason
    notes = fields.Str(required=False, allow_none=True)
    reason = fields.Str(required=False, allow_none=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SaleUpdateSchema(Schema):
    sale_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Sale ID is required",
            "invalid": "Invalid Sale ID. Ensure it is a valid ObjectId."
        }
    )

    # In many POS systems you wouldn’t allow changing all of these once Completed/Closed,
    # but schema-wise we keep them optional and enforce in the resource.
    customer_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "invalid": "Invalid Customer ID. Ensure you add a valid customer ID."
        }
    )
    supplier_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "invalid": "Invalid Supplier ID. Ensure you add a valid supplier ID."
        }
    )
    product_ids = fields.List(
        fields.Str(
            validate=[validate.Length(min=1, max=36), validate_objectid],
        ),
        required=False,
        allow_none=True,
        error_messages={
            "invalid": "Product IDs must be a valid array of product ObjectIds"
        }
    )
    date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format,
        error_messages={
            "invalid": "Date must be in a valid format"
        }
    )
    purchase_price = fields.Float(required=False, allow_none=True)
    order_tax = fields.Float(required=False, allow_none=True)
    discount = fields.Float(required=False, allow_none=True)
    shipping = fields.Float(required=False, allow_none=True)
    grand_total = fields.Float(required=False, allow_none=True)

    status = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(SALE_STATUS_CHOICES),
    )

    # DO NOT allow clients to change sale_type / original_sale_id through PATCH;
    # we’ll only set those server-side in special endpoints.
    notes = fields.Str(required=False, allow_none=True)
    reason = fields.Str(required=False, allow_none=True)

    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# ----------------------- SPECIAL ACTION SCHEMAS -------------------------

class SaleVoidSchema(Schema):
    sale_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Sale ID is required",
            "invalid": "Invalid Sale ID. Ensure it is a valid ObjectId."
        }
    )
    business_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
    )
    reason = fields.Str(
        required=False,
        allow_none=True,
        error_messages={
            "invalid": "Reason must be a string if provided."
        }
    )


class SaleRefundSchema(Schema):
    sale_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Sale ID is required for refund",
            "invalid": "Invalid Sale ID. Ensure it is a valid ObjectId."
        }
    )
    
    outlet_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={
            "required": "Outlet ID is required for refund",
            "invalid": "Invalid Outlet ID. Ensure it is a valid ObjectId."
        }
    )
    
    business_id = fields.Str(
        required=False,
        allow_none=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
    )
    # Optional: if not provided, we’ll do a full refund
    refund_amount = fields.Float(
        required=False,
        allow_none=True,
        error_messages={
            "invalid": "Refund amount must be a valid number."
        }
    )
    date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format,
        error_messages={
            "invalid": "Date must be in a valid format"
        }
    )
    reason = fields.Str(required=False, allow_none=True)

# ------------------PRODUCT SALES-----------------------------

# -----------------------EXPENSE SCHEMA-------------------------
class ExpenseSchema(Schema):
    name = fields.Str(
        required=True,
        error_messages={
            "required": "Expense name is required",
        }
    )
    description = fields.Str(
        required=True,
        validate=validate.Length(min=5, max=255),
        error_messages={"required": "Description is required"}
    )
    category = fields.Str(
        required=False,
        allow_none=True
    )
    date = fields.Str(
        required=True,
        validate=validate_date_format, 
        error_messages={"required": "Date is required", "invalid": "Date is required"}
    )
    amount = fields.Float(
        required=True,
        default=0.0,
        error_messages={"required": "Amount is required", "invalid": "Date is required"}
    )
    # status = fields.Str(
    #     required=False,
    #     allow_none=True
    # )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class ExpenseUpdateSchema(Schema):
    expense_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Expense ID is required", "invalid": "Expense ID "}
    )
    name = fields.Str(
        required=False,
        allow_none=True
    )
    description = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=5, max=255),
    )
    category = fields.Str(
        required=False,
        allow_none=True
    )
    date = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_date_format, 
    )
    amount = fields.Float(
        required=True,
        allow_none=True,
        default=0.0,
    )
    status = fields.Str(
        required=True,
        validate=validate.OneOf(["Approved", "Pending"]),
    )
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

# -----------------------EXPENSE SCHEMA-------------------------

# -----------------------DISCOUNT-------------------------
# class DiscountSchema(Schema):
#     name = fields.Str(
#         required=True,
#         error_messages={
#             "required": "Discount name is required",
#         }
#     )
#     product_ids = fields.List(
#         fields.Str(validate=validate.Length(min=1, max=36)),
#         required=True,
#         error_messages={"required": "Product IDs are required", "invalid": "Product IDs must be valid array of IDs"}
#     )
#     location = fields.Str(
#         required=True,
#         error_messages={"required": "Location are required"},
#     )
#     priority = fields.Int(
#         required=False,
#         allow_none=True
#     )
#     discount_type = fields.Str(
#         required=True,
#         validate=validate.OneOf(["Fixed", "Percentage"]),
#     )
#     discount_amount = fields.Float(
#         required=True,
#         error_messages={"required": "Location are required"},
#     )
#     start_date = fields.Str(
#         required=True,
#         validate=validate_date_format, 
#         error_messages={"required": "Start date is required", "invalid": "Start date is required"}
#     )
#     end_date = fields.Str(
#         required=True,
#         validate=validate_date_format, 
#         error_messages={"required": "End date is required", "invalid": "End date is required"}
#     )
#     selling_price_group_id = fields.Str(
#         required=False,
#         validate=[validate.Length(min=1, max=36), validate_objectid],
#         error_messages={
#             "required": "Group ID is required",
#             "invalid": "Invalid Group ID. Ensure it's a valid. Ensure you add a valid group ID."
#         }
#     )
#     apply_in_customer_groups = fields.Int(
#         required=False,
#         validate=validate.OneOf([0, 1]),
#         default=0
#     )
#     status = fields.Str(
#         required=False,
#         allow_none=True,
#         validate=validate.OneOf(["Active", "Inactive"]),
#     )
#     created_at = fields.DateTime(dump_only=True)
#     updated_at = fields.DateTime(dump_only=True)

# class DiscountUpdateSchema(Schema):
#     discount_id = fields.Str(
#         required=True,
#         validate=[validate.Length(min=1, max=36), validate_objectid],
#         error_messages={"required": "Discount ID is required", "invalid": "Discount ID must be valid"}
#     )
#     name = fields.Str(
#         required=False,
#     )
#     product_ids = fields.List(
#         fields.Str(validate=validate.Length(min=1, max=36)),
#         required=False,
#     )
#     location = fields.Str(
#         required=False,
#     )
#     priority = fields.Int(
#         required=False,
#     )
#     discount_type = fields.Str(
#         required=False,
#         validate=validate.OneOf(["Fixed", "Percentage"]),
#     )
#     discount_amount = fields.Float(
#         required=False,
#     )
#     start_date = fields.Str(
#         required=False,
#         validate=validate_date_format, 
#     )
#     end_date = fields.Str(
#         required=False,
#         validate=validate_date_format, 
#     )
#     selling_price_group_id = fields.Str(
#         required=False,
#         validate=[validate.Length(min=1, max=36), validate_objectid],
#     )
#     apply_in_customer_groups = fields.Int(
#         required=False,
#         validate=validate.OneOf([0, 1]),
#         default=0
#     )
#     status = fields.Str(
#         required=False,
#         validate=validate.OneOf(["Active", "Inactive"]),
#     )
#     created_at = fields.DateTime(dump_only=True)
#     updated_at = fields.DateTime(dump_only=True)

# -----------------------DISCOUNT-------------------------

# -----------------------SELLING PRICE GROUP-------------------------
class SellingPriceGroupSchema(Schema):
    name = fields.Str(
        required=True,
        error_messages={
            "required": "Discount name is required",
        }
    )
    description = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=500),
        error_messages={"required": "Description is required", "min_length": "Description must be at least 5 characters"}
    )
    status = fields.Str(
        required=False,
        allow_none=True
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SellingPriceGroupUpdateSchema(Schema):
    selling_price_group_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Group ID is required", "invalid": "Invalid Group ID. Ensure it's a valid. Ensure you add a valid group ID."}
    )
    name = fields.Str(
        required=False,
    )
    description = fields.Str(
        required=False,
        validate=validate.Length(min=5, max=500),
    )
    status = fields.Str(
        required=False,
        validate=validate.OneOf(["Active", "Inactive"]),
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# -----------------------SELLING PRICE GROUP-------------------------



# Business ID Query
class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        description="The business_id of the store to fetch details."
    )
# Supplier ID query
class SupplierIdQuerySchema(Schema):
    supplier_id = fields.Str(
        required=True,
        validate=validate_objectid,
        description="Supplier ID of the Supplier to fetch detail."
    )
# Product ID 
class ProductIdQuerySchema(Schema):
    product_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        description="Product ID of the Product to fetch detail."
    )
# Sales ID Query
class SaleIdQuerySchema(Schema):
    sale_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        description="Sale ID of the Sale to fetch detail."
    )
# Expense ID Query

class ExpenseIdQuerySchema(Schema):
    expense_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid], 
        description="Expense ID of the Expense to fetch detail."
    )
# Discount ID Query
class DiscountIdQuerySchema(Schema):
    discount_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid], 
        description="Discount ID of the discount to fetch detail."
    )
# Selling Price Group ID Query
class SellingPriceGroupIdQuerySchema(Schema):
    selling_price_group_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid], 
        description="Selling Price Group ID of the Selling Price Group to fetch detail."
    )


class WarrantyQuerySchema(Schema):
    page = fields.Str(
        required=False,
        allow_none=True,
    )



