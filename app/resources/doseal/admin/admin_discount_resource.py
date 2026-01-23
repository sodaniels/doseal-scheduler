import bcrypt
import jwt
import os
import time
import secrets

from bson import ObjectId
from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, g, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue



from datetime import datetime, timedelta
#helper functions
from ....utils.file_upload import (
    upload_file, 
    delete_old_image, 
    upload_files
)
#helper functions
from ....utils.json_response import prepared_response
from ....utils.generators import generate_sku
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from .admin_business_resource import token_required
from app.utils.logger import Log # import logging
from app.constants.service_code import (
    HTTP_STATUS_CODES,
    SYSTEM_USERS
)
from ....utils.helpers import make_log_tag
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
    sale_refund_limiter,
    products_read_limiter,
    products_write_limiter,
    products_delete_limiter
)


# schemas
from ....schemas.admin.product_schema import (
    BusinessIdQuerySchema, ProductSchema, ProductUpdateSchema, ProductIdQuerySchema,
    ExpenseUpdateSchema, ExpenseIdQuerySchema, DiscountIdQuerySchema, SellingPriceGroupSchema,
    SellingPriceGroupUpdateSchema, SellingPriceGroupIdQuerySchema, POSProductsQuerySchema
    
)
from ....schemas.admin.discount_schema import (
    DiscountSchema, DiscountUpdateSchema,
)
from ....schemas.admin.setup_schema import BusinessIdAndUserIdQuerySchema
# model
from ....models.product_model import (
    Product, Sale, Discount, SellingPriceGroup, 
)
from ....models.admin.customer_model import Customer
from ....models.admin.setup_model import Supplier




blp_sale = Blueprint("Sale", __name__,  description="Sales Management")
blp_discount = Blueprint("Discount", __name__,  description="Discount Management")
blp_selling_price_group = Blueprint("Selling Price Group", __name__,  description="Selling Price Group Management")



# -----------------------------DISCOUNT----------------------------------
@blp_discount.route("/discount", methods=["POST", "GET", "PATCH", "DELETE"])
class DiscountResource(MethodView):

    # ------------------------- CREATE DISCOUNT (POST) ------------------------- #
    @token_required
    @crud_write_limiter("discount")
    @blp_discount.arguments(DiscountSchema, location="form")
    @blp_discount.response(201, DiscountSchema)
    @blp_discount.doc(
        summary="Create a new discount",
        description="""
            Create a new discount for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the body to create a discount for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new discount."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user__id"] = auth_user__id
        item_data["admin_id"] = auth_user__id
        if not item_data.get("user_id"):
            item_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "DiscountResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the discount already exists based on business_id and name
        try:
            Log.info(f"{log_tag} checking if discount already exists")
            exists = Discount.check_multiple_item_exists(target_business_id, {"name": item_data.get("name")})
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating discount uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} discount already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Discount already exists",
            )

        Log.info(f"{log_tag} item_data: {item_data}")
        
        # ----------------- FK VALIDATION: customer, supplier, products ----------------- #
        try:
            Log.info(f"{log_tag} validating foreign keys for discount")

            # Validate each product_id in product_ids, if present
            product_ids = item_data.get("product_ids") or []
            invalid_products = []

            for pid in product_ids:
                product = Product.get_by_id(pid, target_business_id)
                if not product:
                    invalid_products.append(pid)

            if invalid_products:
                Log.info(
                    f"{log_tag} invalid product_ids for target_business_id={target_business_id}: "
                    f"{invalid_products}"
                )
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "One or more product_ids are invalid for the specified business.",
                    errors={"invalid_product_ids": invalid_products},
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while validating foreign keys: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while validating sale references.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while validating foreign keys: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while validating sale references.",
                errors=str(e),
            )

        # ----------------- CREATE SALE AFTER FK VALIDATION ----------------- #

        # Create a new discount instance
        item = Discount(**item_data)

        # Try saving the discount to MongoDB and handle any errors
        try:
            Log.info(f"{log_tag} committing discount transaction")
            start_time = time.time()

            discount_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} discount created with id={discount_id} "
                f"in {duration:.2f} seconds"
            )

            if discount_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Discount created successfully.",
                )

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create discount.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the discount.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE DISCOUNT (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("discount")
    @blp_discount.arguments(DiscountIdQuerySchema, location="query")
    @blp_discount.response(200, DiscountSchema)
    @blp_discount.doc(
        summary="Retrieve discount by discount_id (role-aware)",
        description="""
            Retrieve a discount by `discount_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, discount_data):
        discount_id = discount_data.get("discount_id")
        query_business_id = discount_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Initial log_tag (target business refined after role resolution)
        log_tag = make_log_tag(
            "admin_product_resource.py",
            "DiscountResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not discount_id:
            Log.info(f"{log_tag}[discount_id:None] discount_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "discount_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "DiscountResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[discount_id:{discount_id}] "
                    f"super_admin/system_owner requesting discount. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "DiscountResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[discount_id:{discount_id}] "
                    f"non-admin requesting discount in own business"
                )

            start_time = time.time()
            discount = Discount.get_by_id(discount_id, target_business_id)
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[discount_id:{discount_id}] "
                f"retrieving discount completed in {duration:.2f} seconds"
            )

            if not discount:
                Log.info(f"{log_tag}[discount_id:{discount_id}] discount not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Discount not found.",
                )

            Log.info(f"{log_tag}[discount_id:{discount_id}] discount found")
            return prepared_response(
                True,
                "OK",
                "Discount retrieved successfully.",
                data=discount,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[discount_id:{discount_id}] PyMongoError retrieving discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the discount.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag}[discount_id:{discount_id}] unexpected error retrieving discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE DISCOUNT (role-aware PATCH) ---------------------- #
    @token_required
    @crud_write_limiter("discount")
    @blp_discount.arguments(DiscountUpdateSchema, location="form")
    @blp_discount.response(200, DiscountUpdateSchema)
    @blp_discount.doc(
        summary="Update an existing discount (role-aware)",
        description="""
            Update an existing discount by providing `discount_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the body to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing discount."""
        discount_id = item_data.get("discount_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")
        item_data["user__id"] = auth_user__id

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "DiscountResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not discount_id:
            Log.info(f"{log_tag} discount_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "discount_id must be provided.",
            )

        # Check if the discount exists in the target business scope
        try:
            discount = Discount.get_by_id(discount_id, target_business_id)
            Log.info(f"{log_tag} check_discount")
        except Exception as e:
            Log.info(f"{log_tag} error checking discount existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the discount.",
                errors=str(e),
            )

        if not discount:
            Log.info(f"{log_tag} discount not found")
            return prepared_response(False, "NOT_FOUND", "Discount not found")

        # Attempt to update the discount
        try:
            Log.info(f"{log_tag} updating discount (PUT)")
            start_time = time.time()

            # Remove discount_id before patching
            item_data.pop("discount_id", None)

            update_ok = Discount.update(discount_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} discount updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Discount updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to update discount.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError updating discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the discount.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error updating discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE DISCOUNT (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("discount")
    @blp_discount.arguments(DiscountIdQuerySchema, location="query")
    @blp_discount.response(200)
    @blp_discount.doc(
        summary="Delete a discount by discount_id (role-aware)",
        description="""
            Delete a discount using `discount_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, discount_data):
        discount_id = discount_data.get("discount_id")
        query_business_id = discount_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Admins can choose business_id via query, others are bound to their own
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "DiscountResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not discount_id:
            Log.info(f"{log_tag} discount_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "discount_id must be provided.",
            )

        # Retrieve the discount
        try:
            discount = Discount.get_by_id(discount_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the discount.",
                errors=str(e),
            )

        if not discount:
            Log.info(f"{log_tag} discount not found")
            return prepared_response(False, "NOT_FOUND", "Discount not found.")

        # Attempt to delete
        try:
            delete_success = Discount.delete(discount_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "Failed to delete discount.",
                )

            Log.info(f"{log_tag} discount deleted successfully")
            return prepared_response(True, "OK", "Discount deleted successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError deleting discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the discount.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error deleting discount: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


@blp_discount.route("/discounts", methods=["GET"])
class DiscountListResource(MethodView):
    @token_required
    @crud_read_limiter("discount")
    @blp_discount.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_discount.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_discount.doc(
        summary="Retrieve discounts based on role and permissions",
        description="""
            Retrieve discount details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all discounts in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to discounts belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Discount(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "discounts": [
                                    {
                                        "discount_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Holiday Discount",
                                        "product_ids": ["product123", "product456"],
                                        "location": "Store 1",
                                        "discount_type": "Percentage",
                                        "discount_amount": 10.0,
                                        "start_date": "2023-12-01",
                                        "end_date": "2023-12-31",
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10,
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Bad request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Bad request"
                        }
                    }
                }
            },
            404: {
                "description": "Discounts not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Discounts not found"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred while retrieving the discounts.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, discount_data):
        page = discount_data.get("page")
        per_page = discount_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = discount_data.get("business_id")
        query_user_id = discount_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Provisional log_tag before we resolve target_business_id
        log_tag = make_log_tag(
            "admin_product_resource.py",
            "DiscountListResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                # Refresh log_tag now that we know the real target_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "DiscountListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    discounts_result = Discount.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All discounts for that business
                    discounts_result = Discount.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all discounts in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "DiscountListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: discounts in own business")

                discounts_result = Discount.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own discounts in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "DiscountListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own discounts only")

                discounts_result = Discount.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no discounts found
            if not discounts_result or not discounts_result.get("discounts"):
                Log.info(f"{log_tag} Discounts not found")
                return prepared_response(False, "NOT_FOUND", "Discounts not found")

            Log.info(
                f"{log_tag} discount(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": discounts_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving discounts: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the discounts. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving discounts: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )

# -----------------------------DISCOUNT----------------------------------

# -----------------------------SELLING PRICE GROUP----------------------------------

@blp_selling_price_group.route("/selling-price-group", methods=["POST", "GET", "PATCH", "DELETE"])
class SellingPriceGroupResource(MethodView):

    # ------------------------- CREATE SELLING PRICE GROUP (POST) ------------------------- #
    @token_required
    @crud_write_limiter("sellingprice-group")
    @blp_selling_price_group.arguments(SellingPriceGroupSchema, location="form")
    @blp_selling_price_group.response(201, SellingPriceGroupSchema)
    @blp_selling_price_group.doc(
        summary="Create a new selling price group",
        description="""
            Create a new selling price group for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the payload to create a group for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SellingPriceGroupSchema,
                    "example": {
                        "name": "Premium Products",
                        "description": "A premium group of products",
                        "status": "Active"
                    }
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new selling price group."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user__id"] = auth_user__id
        if not item_data.get("user_id"):
            item_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "SellingPriceGroupResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the selling price group already exists based on business_id and name
        try:
            Log.info(f"{log_tag} checking if selling price group already exists")
            exists = SellingPriceGroup.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating selling price group uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} selling price group already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Selling price group already exists",
            )

        Log.info(f"{log_tag} item_data: {item_data}")

        # Create a new selling price group instance
        item = SellingPriceGroup(**item_data)

        # Try saving the selling price group to MongoDB
        try:
            Log.info(f"{log_tag} committing selling price group transaction")
            start_time = time.time()

            selling_price_group_id = item.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag} selling price group created with id={selling_price_group_id} "
                f"in {duration:.2f} seconds"
            )

            if selling_price_group_id:
                return prepared_response(
                    True,
                    "OK",
                    "Selling price group created successfully.",
                )

            Log.info(f"{log_tag} save returned None")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create selling price group.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the selling price group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE SELLING PRICE GROUP (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("sellingprice-group")
    @blp_selling_price_group.arguments(SellingPriceGroupIdQuerySchema, location="query")
    @blp_selling_price_group.response(200, SellingPriceGroupSchema)
    @blp_selling_price_group.doc(
        summary="Retrieve a selling price group by selling_price_group_id (role-aware)",
        description="""
            Retrieve a selling price group by `selling_price_group_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, selling_price_group_data):
        """Handle the GET request to retrieve a selling price group by id."""
        selling_price_group_id = selling_price_group_data.get("selling_price_group_id")
        query_business_id = selling_price_group_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Provisional log_tag
        log_tag = make_log_tag(
            "admin_product_resource.py",
            "SellingPriceGroupResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not selling_price_group_id:
            Log.info(f"{log_tag}[spg_id:None] selling_price_group_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "selling_price_group_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "SellingPriceGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[spg_id:{selling_price_group_id}] "
                    f"super_admin/system_owner requesting selling price group. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "SellingPriceGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[spg_id:{selling_price_group_id}] "
                    f"non-admin requesting selling price group in own business"
                )

            start_time = time.time()
            selling_price_group = SellingPriceGroup.get_by_id(
                selling_price_group_id,
                target_business_id,
            )
            duration = time.time() - start_time

            Log.info(
                f"{log_tag}[spg_id:{selling_price_group_id}] "
                f"retrieving selling price group completed in {duration:.2f} seconds"
            )

            if not selling_price_group:
                Log.info(f"{log_tag}[spg_id:{selling_price_group_id}] selling price group not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Selling price group not found.",
                )

            Log.info(f"{log_tag}[spg_id:{selling_price_group_id}] selling price group found")
            return prepared_response(
                True,
                "OK",
                "Selling price group retrieved successfully.",
                data=selling_price_group,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[spg_id:{selling_price_group_id}] PyMongoError while retrieving selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the selling price group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag}[spg_id:{selling_price_group_id}] unexpected error while retrieving selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE SELLING PRICE GROUP (role-aware PATCH) ---------------------- #
    @token_required
    @crud_write_limiter("sellingprice-group")
    @blp_selling_price_group.arguments(SellingPriceGroupUpdateSchema, location="form")
    @blp_selling_price_group.response(200, SellingPriceGroupSchema)
    @blp_selling_price_group.doc(
        summary="Partially update an existing selling price group (role-aware)",
        description="""
            Partially update an existing selling price group by providing `selling_price_group_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the payload to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SellingPriceGroupUpdateSchema,
                    "example": {
                        "selling_price_group_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Premium Products (Updated)",
                        "description": "Updated description",
                        "status": "Active"
                    }
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing selling price group."""
        selling_price_group_id = item_data.get("selling_price_group_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")
        item_data["user__id"] = auth_user__id

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "SellingPriceGroupResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not selling_price_group_id:
            Log.info(f"{log_tag} selling_price_group_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "selling_price_group_id must be provided.",
            )

        # Check existing SPG in target business scope
        try:
            selling_price_group = SellingPriceGroup.get_by_id(
                selling_price_group_id,
                target_business_id,
            )
            Log.info(f"{log_tag} check_selling_price_group: {selling_price_group}")
        except Exception as e:
            Log.info(f"{log_tag} error checking selling price group existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the selling price group.",
                errors=str(e),
            )

        if not selling_price_group:
            Log.info(f"{log_tag} selling price group not found")
            return prepared_response(False, "NOT_FOUND", "Selling price group not found")

        # Attempt to update the selling price group data
        try:
            Log.info(f"{log_tag} updating selling price group (PATCH)")
            start_time = time.time()

            # Don't try to overwrite id
            item_data.pop("selling_price_group_id", None)

            update_ok = SellingPriceGroup.update(selling_price_group_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} selling price group updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Selling price group updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update selling price group.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the selling price group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE SELLING PRICE GROUP (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("sellingprice-group")
    @blp_selling_price_group.arguments(SellingPriceGroupIdQuerySchema, location="query")
    @blp_selling_price_group.response(200)
    @blp_selling_price_group.doc(
        summary="Delete a selling price group by selling_price_group_id (role-aware)",
        description="""
            Delete a selling price group using `selling_price_group_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, selling_price_group_data):
        selling_price_group_id = selling_price_group_data.get("selling_price_group_id")
        query_business_id = selling_price_group_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Admins may delete from any business using ?business_id=
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "SellingPriceGroupResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not selling_price_group_id:
            Log.info(f"{log_tag} selling_price_group_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "selling_price_group_id must be provided.")

        # Retrieve the selling price group
        try:
            selling_price_group = SellingPriceGroup.get_by_id(
                selling_price_group_id,
                target_business_id,
            )
        except Exception as e:
            Log.info(f"{log_tag} error fetching selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the selling price group.",
                errors=str(e),
            )

        if not selling_price_group:
            Log.info(f"{log_tag} selling price group not found")
            return prepared_response(False, "NOT_FOUND", "Selling price group not found.")

        # Attempt to delete selling price group
        try:
            delete_success = SellingPriceGroup.delete(selling_price_group_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete selling price group.")

            Log.info(f"{log_tag} selling price group deleted successfully")
            return prepared_response(True, "OK", "Selling price group deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the selling price group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting selling price group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


@blp_selling_price_group.route("/selling-price-groups", methods=["GET"])
class SellingPriceGroupResource(MethodView):
    @token_required
    @crud_read_limiter("sellingprice-group")
    @blp_selling_price_group.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_selling_price_group.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_selling_price_group.doc(
        summary="Retrieve selling price groups based on role and permissions",
        description="""
            Retrieve selling price group details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all selling price groups in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to selling price groups belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Selling price group(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "selling_price_groups": [
                                    {
                                        "_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Premium Products",
                                        "description": "A premium group of products",
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10,
                            }
                        }
                    }
                }
            }
        }
    )
    def get(self, selling_price_group_data):
        # Pagination
        page = selling_price_group_data.get("page")
        per_page = selling_price_group_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = selling_price_group_data.get("business_id")
        query_user_id = selling_price_group_data.get("user_id")   # treated as user__id

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Provisional log_tag (refined when target_business_id is known)
        log_tag = make_log_tag(
            "admin_product_resource.py",
            "SellingPriceGroupResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        try:
            # -------------------------
            # ROLE-BASED BUSINESS SCOPE
            # -------------------------
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "SellingPriceGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    spg_result = SellingPriceGroup.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All groups for that business
                    spg_result = SellingPriceGroup.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all groups in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "SellingPriceGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: selling price groups in own business")

                spg_result = SellingPriceGroup.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own groups in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "SellingPriceGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own selling price groups only")

                spg_result = SellingPriceGroup.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # -------------------------
            # NOT FOUND
            # -------------------------
            if (
                not spg_result
                or not spg_result.get("selling_price_groups")
            ):
                Log.info(f"{log_tag} Selling price groups not found")
                return prepared_response(False, "NOT_FOUND", "Selling price groups not found")

            Log.info(
                f"{log_tag} selling_price_group(s) found for "
                f"target_business_id={target_business_id}"
            )

            # -------------------------
            # SUCCESS RESPONSE
            # -------------------------
            return prepared_response(
                True,
                "OK",
                "Selling price groups retrieved successfully.",
                data=spg_result,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving selling price groups: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the selling price groups.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving selling price groups: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
# -----------------------------SELLING PRICE GROUP----------------------------------