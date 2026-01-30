from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from ....utils.json_response import prepared_response
from ....utils.crypt import decrypt_data
from ....constants.service_code import SYSTEM_USERS
from .admin_business_resource import token_required
from ....utils.rate_limits import crud_write_limiter
from ....models.product_model import Product
from ....schemas.admin.product_schema import (
    ProductImportItemSchema
)
from marshmallow import Schema, fields

blp_product_import = Blueprint("product_import", __name__, description="Bulk product import")

class BulkImportSchema(Schema):
    mode = fields.Str(allow_none=True)  # create|upsert
    dry_run = fields.Int(allow_none=True)
    items = fields.List(fields.Nested(ProductImportItemSchema), required=True)

@blp_product_import.route("/products/bulk/import")
class ProductsBulkResource(MethodView):

    @token_required
    @crud_write_limiter("products_bulk")
    @blp_product_import.arguments(BulkImportSchema, location="form")
    @blp_product_import.response(200)
    def post(self, data):
        user_info = g.get("current_user", {}) or {}
        auth_business_id = str(user_info.get("business_id"))
        role = user_info.get("account_type") if user_info.get("account_type") else None

        mode = (data.get("mode") or "upsert").lower()
        dry_run = int(data.get("dry_run") or 0) == 1
        items = data.get("items") or []

        if mode not in ("create", "upsert"):
            return prepared_response(False, "BAD_REQUEST", "mode must be create or upsert")

        if dry_run:
            # validation already happened via schema
            return prepared_response(True, "OK", "Dry run successful. Payload is valid.", data={"count": len(items)})

        # If you want SUPER_ADMIN to import into another business, add business_id field to BulkImportSchema
        target_business_id = auth_business_id

        result = Product.bulk_upsert(
            business_id=target_business_id,
            user_info=user_info,
            items=items,
            mode=mode
        )

        return prepared_response(True, "OK", "Bulk import completed.", data=result)
