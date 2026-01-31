import bcrypt
import jwt
import os
import time
import secrets
from bson.objectid import ObjectId
from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError, DuplicateKeyError
from rq import Queue

#helper functions
from ....utils.file_upload import (
    upload_file, 
    delete_old_image, 
    upload_files
)
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
)
from ....utils.crypt import decrypt_data
#helper functions
from .admin_business_resource import token_required
from ....utils.json_response import prepared_response
from ....utils.helpers import (
    make_log_tag, resolve_target_business_id
)
from ....utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ....utils.logger import Log # import logging
from ....models.admin.customer_model import Customer
from ....constants.service_code import (
   HTTP_STATUS_CODES,SYSTEM_USERS
)

# schemas
from ....schemas.admin.setup_schema import (
    StoreSchema, StoreQuerySchema, BusinessIdAndUserIdQuerySchema, UnitUpdateSchema,
    UnitSchema, UnitQuerySchema, BusinessIdQuerySchema, UnitQueryUnitIdSchema,
    CategorySchema, CategoryIdQuerySchema, CategoryUpdateSchema, SubCategorySchema,
    SubCategoryIdQuerySchema, SubCategoryUpdateSchema, BrandSchema, BrandIdQuerySchema,
    BrandUpdateSchema, StoreUpdateSchema, VariantSchema, VariantIdQuerySchema, VariantUpdateSchema,
    TaxSchema, TaxIdQuerySchema, TaxUpdateSchema, WarrantySchema, SupplierSchema, SupplierIdQuerySchema,
    WarrantyIdQuerySchema, WarrantyUpdateSchema, SupplierUpdateSchema, TagIdQuerySchema, TagSchema,
    TagUpdateSchema, GiftCardSchema, GiftCardUpdateSchema, GiftCardIdQuerySchema, OutletSchema,
    OutletUpdateSchema, OutletIdQuerySchema, BusinessLocationSchema, BusinessLocationUpdateSchema,
    BusinessLocationQuerySchema, CompositeVariantSchema, CompositeVariantIdQuerySchema, CompositeVariantUpdateSchema
)

from ....schemas.admin.product_schema import WarrantyQuerySchema

# models
from ....models.admin.setup_model import (
    Store, Unit, Category, SubCategory, Brand, Variant, Tax, Warranty, Supplier, Tag,
    GiftCard, Outlet, BusinessLocation, CompositeVariant
)


SECRET_KEY = os.getenv("SECRET_KEY") 

REDIS_HOST = os.getenv("REDIS_HOST")
connection = Redis(host=REDIS_HOST, port=6379)
queue = Queue("emails", connection=connection)


blp_store = Blueprint("Store", __name__, description="Store Management")
blp_unit = Blueprint("Unit", __name__,  description="Unit Management")
blp_category = Blueprint("Category", __name__,  description="Cateogry Management")
blp_sub_category = Blueprint("Sub Category", __name__,  description="Sub Cateogry Management")
blp_brand = Blueprint("Brand", __name__,  description="Brand Management")
blp_variant = Blueprint("Variant", __name__,  description="Variant Management")
blp_tax = Blueprint("Tax", __name__,  description="Tax Management")
blp_warranty = Blueprint("Warranty", __name__,  description="Warranty Management")
blp_supplier = Blueprint("Supplier", __name__,  description="Supplier Management")
blp_tag = Blueprint("Product Tag", __name__,  description="Product Tag Management")
blp_gift_card = Blueprint("Gift Card", __name__,  description="Gift Card Management")
blp_outlet = Blueprint("Outlet & Register", __name__,  description="Outlet & Register Management")
blp_business_location = Blueprint("Business Location", __name__,  description="Business Location Management")
blp_composite_variant = Blueprint("Composite Variant", __name__,  description="Composite Variant Management")


# BEGINNIG OF STORE
@blp_store.route("/store", methods=["POST", "GET", "PATCH", "DELETE"])
class StoreResource(MethodView):
    
    @token_required
    @crud_write_limiter("store")
    @blp_store.arguments(StoreSchema, location="form")
    @blp_store.response(201, StoreSchema)
    @blp_store.doc(
        summary="Create a new store",
        description="""
            Create a new store for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a store for any business.
                - If omitted, defaults to their own business_id.
            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, store_data):
        """Handle the POST request to create a new store."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # business_id from form (only honoured for system_owner/super_admin)
        form_business_id = store_data.get("business_id")

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        store_data["business_id"] = target_business_id
        store_data["user__id"] = auth_user__id
        # If user_id isn't set by schema or client, default from token context
        if not store_data.get("user_id"):
            store_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][StoreResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # 1️⃣ Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                store_data["image"] = image_path
                store_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} Image upload failed: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        # 2️⃣ Check duplicate store (by email + name) within target business
        try:
            Log.info(f"{log_tag} Checking if store already exists (email + name)")
            exists = Store.check_multiple_item_exists(
                target_business_id,
                {
                    "email": store_data.get("email"),
                    "name": store_data.get("name"),
                },
            )
        except Exception as e:
            # internal error in duplicate check
            Log.info(f"{log_tag} Error while checking duplicates: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating store uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} Store already exists.")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "CONFLICT",
                "Store already exists",
            )

        # 3️⃣ Create and save store
        try:
            store = Store(**store_data)

            Log.info(f"{log_tag} Creating store: {store_data.get('name')}")
            start_time = time.time()

            store_id = store.save()

            duration = time.time() - start_time
            Log.info(f"{log_tag} Store created with id={store_id} in {duration:.2f} seconds")

            return prepared_response(
                True,
                "OK",
                "Store created successfully.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving store: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the store.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while saving store: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


    @token_required
    @blp_store.arguments(StoreQuerySchema, location="query")
    @blp_store.response(200, StoreSchema)
    @crud_read_limiter("store")
    @blp_store.doc(
        summary="Retrieve a single store by store_id (role-aware)",
        description="""
            Retrieve a single store by its `store_id`, enforcing role-based access:
            - system_owner/super_admin:
                • can pass ?business_id=<id> and ?user__id=<id>
                • can access any business data
            - business_owner:
                • restricted to their own business
            - staff:
                • restricted to their own business and own user__id
        """,
        security=[{"Bearer": []}],
    )
    def get(self, store_data):
        store_id = store_data.get("store_id")
        query_business_id = store_data.get("business_id")
        query_user__id = store_data.get("user__id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][SingleStoreResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # -----------------------------
            # ROLE: SYSTEM OWNER / SUPER ADMIN
            # -----------------------------
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):

                # Allow admin to choose business_id dynamically
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner requesting store. "
                    f"target_business_id={target_business_id}, query_user__id={query_user__id}"
                )

            # -----------------------------
            # ROLE: BUSINESS OWNER
            # -----------------------------
            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                target_business_id = auth_business_id

                Log.info(f"{log_tag} business_owner requesting store in own business")

            # -----------------------------
            # ROLE: STAFF / OTHERS
            # -----------------------------
            else:
                target_business_id = auth_business_id

                # Staff must match their own user__id unless overridden by admin role
                if query_user__id and query_user__id != auth_user__id:
                    return prepared_response(
                        False,
                        "FORBIDDEN",
                        "You are not allowed to access other users’ stores."
                    )

                Log.info(f"{log_tag} staff requesting own store only")

            # -----------------------------
            # FETCH STORE
            # -----------------------------
            store = Store.get_by_id(store_id, target_business_id)

            if not store:
                Log.info(f"{log_tag}[{store_id}] Store not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Store not found"
                )

            Log.info(f"{log_tag}[{store_id}] store found")

            return prepared_response(
                True,
                "OK",
                "Store retrieved successfully.",
                data=store
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[{store_id}] PyMongoError: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving the store.",
                errors=str(e)
            )

        except Exception as e:
            Log.info(f"{log_tag}[{store_id}] Unexpected error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e)
            )

    @token_required
    @crud_write_limiter("store")
    @blp_store.arguments(StoreUpdateSchema, location="form")
    @blp_store.response(200, StoreSchema)
    @blp_store.doc(
        summary="Update an existing store",
        description="""
            This endpoint allows you to update an existing store by providing `store_id` in the request body.
            - **PATCH**: Update an existing store by providing details such as store name, phone number, email, logo (optional), etc.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": StoreSchema,
                    "example": {
                        "store_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Doe Enterprises",
                        "phone": "1234567890",
                        "email": "johndoe@example.com",
                        "address1": "123 Main St",
                        "address2": "Suite 100",
                        "logo": "logo.png"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Store updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Store updated successfully"
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            404: {
                "description": "Store not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Store not found"
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
                            "message": "An unexpected error occurred",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def patch(self, store_data):
        """Handle the PATCH request to update an existing store."""
        store_id = store_data.get("store_id")  # store_id passed in the request body

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        user__id = str(user_info.get("_id"))
        store_data["user_id"] = user_info.get("user_id")
        business_id = str(user_info.get("business_id"))
        store_data["business_id"] = business_id
        
        log_tag = f'[admin_setup_resource.py][StoreResource][patch][{client_ip}][{business_id}][{user__id}]'

        # Handle image upload (logo)
        actual_path = None
        if 'logo' in request.files:
            logo = request.files['logo']

            try:
                # Use the upload function to upload the logo
                image_path, actual_path = upload_file(logo, user_info.get("business_id"))
                store_data["logo"] = image_path  # Store the path of the logo
                store_data["logo_path"] = actual_path  # Store the actual path of the logo
            except ValueError as e:
                Log.info(f"{log_tag}[{store_id}] An unexpected error occurred. {str(e)}")

        # Check if the store exists based on store_id
        Log.info(f"{log_tag} Check if the store exists based on store_id")
        store = Store.get_by_id(store_id, business_id)

        if not store:
            # Delete the uploaded logo if it doesn't exist in the database 
            if actual_path:
                os.remove(actual_path)
            Log.info(f"{log_tag}[{store_id}] Store not found")
            return prepared_response(False, "NOT_FOUND", f"Store not found.")

        # Store old logo for deletion after successful update  
        old_logo = store.get("file_path")

        # Attempt to update the store data
        try:
            Log.info(f"{log_tag}[{store_id}] updating store")

            start_time = time.time()

            # Update the store with the new data
            update = Store.update(**store_data)

            # Record the end time
            end_time = time.time()

            # Calculate the duration
            duration = end_time - start_time

            if update:
                Log.info(f"{log_tag}[{store_id}] updating store completed in {duration:.2f} seconds")

                try:
                    # Delete old logo after successful update
                    delete_old_image(old_logo)
                    Log.info(f"{log_tag}[{store_id}] old logo removed successfully")
                except Exception as e:
                    pass

                Log.info(f"{log_tag}[{store_id}] Store updated successfully.")
                return prepared_response(False, "OK", f"Store updated successfully.")
            else:
                # Delete the uploaded logo if store update fails
                if actual_path:
                    os.remove(actual_path)
                Log.info(f"{log_tag}[{store_id}] Failed to update store. {str(e)}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to update store. {str(e)}")

        except PyMongoError as e:
            # Delete image if store update fails after uploading image
            if actual_path:
                os.remove(actual_path)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while updating the store. {str(e)}")

        except Exception as e:
            # Delete image if store update fails after uploading image
            if actual_path:
                os.remove(actual_path)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
    
    @token_required
    @crud_delete_limiter("store")
    @blp_store.arguments(StoreQuerySchema, location="query")
    @blp_store.response(200, StoreQuerySchema)  
    @blp_store.doc(
        summary="Delete a store by store_id",
        description="""
            This endpoint deletes a store using `store_id` from the query parameters.

            • If ?business_id=<id> is submitted, deletion will target that business.  
            • Otherwise, deletion defaults to the authenticated user's business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, store_data):
        store_id = store_data["store_id"]                
        query_business_id = store_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        target_business_id = query_business_id or auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][StoreResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
        )

        # ---- FETCH STORE ----
        try:
            store = Store.get_by_id(store_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} Error fetching store: {e}")
            return prepared_response(
                False, "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the store.",
                errors=str(e),
            )

        if not store:
            Log.info(f"{log_tag} Store not found: {store_id}")
            return prepared_response(False, "NOT_FOUND", "Store not found.")

        # Image path (if any)
        image_path = store.get("file_path") if store.get("image") else None

        # ---- DELETE STORE ----
        try:
            delete_success = Store.delete(store_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} Delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete store.")

            # Try deleting image
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} Image deleted: {image_path}")
                except Exception as e:
                    Log.info(f"{log_tag} Failed to delete image: {e}")

            Log.info(f"{log_tag} Store deleted successfully.")
            return prepared_response(True, "OK", "Store deleted successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError deleting store: {e}")
            return prepared_response(
                False, "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the store.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error deleting store: {e}")
            return prepared_response(
                False, "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

              
@blp_store.route("/stores", methods=["GET"])
class StoreResource(MethodView):
    @token_required
    @crud_write_limiter("store")
    @blp_store.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_store.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_store.doc(
        summary="Retrieve stores based on role and permissions",
        description="""
            - system_owner/super_admin:
                * can pass ?business_id=<id> and optional ?user__id=<id>
                * see any business
            - business_owner:
                * fixed to their own business
                * see all users' stores in that business
            - staff:
                * fixed to own business and own user__id
        """,
        security=[{"Bearer": []}],
    )
    def get(self, item_data):
        page = item_data.get("page")
        per_page = item_data.get("per_page")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Query filters (used differently by role)
        query_business_id = item_data.get("business_id")
        query_user__id = item_data.get("user__id")

        log_tag = (
            f"[admin_setup_resource.py][StoreResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # SYSTEM OWNER / SUPER ADMIN
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} system_owner/super_admin: "
                    f"target_business_id={target_business_id}, query_user__id={query_user__id}"
                )

                if query_user__id:
                    result_data = Store.get_by_user__id_and_business_id(
                        user__id=query_user__id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    result_data = Store.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            # BUSINESS OWNER
            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                Log.info(f"{log_tag} business_owner: all stores in own business")

                # ignore query business_id/user__id: they are confined to their business
                result_data = Store.get_by_business_id(
                    business_id=auth_business_id,
                    page=page,
                    per_page=per_page,
                )

            # STAFF / OTHERS
            else:
                Log.info(f"{log_tag} staff/other: own stores only")

                result_data = Store.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=auth_business_id,
                    page=page,
                    per_page=per_page,
                )

            if not result_data:
                Log.info(f"{log_tag} result_data is None")
                return prepared_response(False, "NOT_FOUND", "Store not found")

            stores_list = result_data.get("stores")
            if not stores_list:
                Log.info(f"{log_tag} stores list empty")
                return prepared_response(False, "NOT_FOUND", "Store not found")

            Log.info(f"{log_tag} store(s) found")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": result_data,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving store(s): {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the store. {str(e)}"
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving store(s): {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# BEGNNING OF UNIT
@blp_unit.route("/unit", methods=["POST", "GET", "PATCH", "DELETE"])
class UnitResource(MethodView):

    # POST unit
    @token_required
    @crud_write_limiter("unit")
    @blp_unit.arguments(UnitSchema, location="form")
    @blp_unit.response(201, UnitSchema)
    @blp_unit.doc(
        summary="Create a new unit",
        description="""
            Create a new unit for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a unit for any business.
                - If omitted, defaults to their own business_id.
            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new unit."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][UnitResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # Check if the unit already exists for this business
        try:
            Log.info(f"{log_tag} checking if the unit already exists")
            exists = Unit.check_multiple_item_exists(
                target_business_id,
                {"unit": item_data.get("unit")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating unit uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} unit already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Unit already exists",
            )

        # Create a new unit instance
        item = Unit(**item_data)

        # Save and handle errors
        try:
            Log.info(f"{log_tag} committing unit: {item_data.get('name')}")
            start_time = time.time()

            unit_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} unit created with id={unit_id} "
                f"in {duration:.2f} seconds"
            )

            return prepared_response(
                True,
                "OK",
                "Unit created successfully.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the unit.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # GET unit by unit_id (role-aware business selection)
    @token_required
    @crud_read_limiter("unit")
    @blp_unit.arguments(UnitQueryUnitIdSchema, location="query")
    @blp_unit.response(200, UnitSchema)
    @blp_unit.doc(
        summary="Retrieve unit by unit_id (role-aware)",
        description="""
            Retrieve a unit by `unit_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, unit_data):
        unit_id = unit_data.get("unit_id")
        query_business_id = unit_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][UnitResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[unit_id:{unit_id}]"
        )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting unit. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting unit in own business")

            unit = Unit.get_by_id(unit_id, target_business_id)

            if not unit:
                Log.info(f"{log_tag} unit not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Unit not found.",
                )

            Log.info(f"{log_tag} unit found")
            return prepared_response(
                True,
                "OK",
                "Unit retrieved successfully.",
                data=unit,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError retrieving unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving the unit.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error retrieving unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # UPDATE unit (role-aware business selection)
    @token_required
    @crud_read_limiter("unit")
    @blp_unit.arguments(UnitUpdateSchema, location="form")
    @blp_unit.response(200, UnitUpdateSchema)
    @blp_unit.doc(
        summary="Update an existing unit",
        description="""
            Update an existing unit by providing `unit_id` and new details.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing unit."""
        unit_id = item_data.get("unit_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][UnitResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[unit_id:{unit_id}]"
        )

        # Check if the unit exists
        try:
            unit = Unit.get_by_id(unit_id, target_business_id)
            Log.info(f"{log_tag} check_unit")
        except Exception as e:
            Log.info(f"{log_tag} error checking unit existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the unit.",
                errors=str(e),
            )

        if not unit:
            Log.info(f"{log_tag} unit not found")
            return prepared_response(False, "NOT_FOUND", "Unit not found")

        # Attempt to update the unit data
        try:
            Log.info(f"{log_tag} updating unit")

            start_time = time.time()

            # Don't try to overwrite _id
            item_data.pop("unit_id", None)

            update = Unit.update(unit_id, **item_data)

            duration = time.time() - start_time

            if update:
                Log.info(f"{log_tag} unit updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Unit updated successfully.")
            else:
                Log.info(f"{log_tag} failed to update unit")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update unit.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError updating unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the unit.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error updating unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # DELETE unit (role-aware business selection)
    @token_required
    @crud_delete_limiter("unit")
    @blp_unit.arguments(UnitQueryUnitIdSchema, location="query")
    @blp_unit.response(200)
    @blp_unit.doc(
        summary="Delete a unit by unit_id",
        description="""
            Delete a unit using `unit_id` from the query parameters.

            • If ?business_id=<id> is submitted, deletion will target that business.  
            • Otherwise, deletion defaults to the authenticated user's business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, unit_data):
        unit_id = unit_data.get("unit_id")
        query_business_id = unit_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For now, same behaviour as Store: admins can choose business_id via query,
        # others are bound to their own business.
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][UnitResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][unit_id:{unit_id}]"
        )

        # Retrieve the unit
        try:
            unit = Unit.get_by_id(unit_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the unit.",
                errors=str(e),
            )

        if not unit:
            Log.info(f"{log_tag} unit not found")
            return prepared_response(False, "NOT_FOUND", "Unit not found.")

        # Attempt to delete the unit
        try:
            delete_success = Unit.delete(unit_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete unit.")

            Log.info(f"{log_tag} unit deleted successfully")
            return prepared_response(True, "OK", "Unit deleted successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError deleting unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the unit.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error deleting unit: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


@blp_unit.route("/units", methods=["GET"])
class UnitListResource(MethodView):
    @token_required
    @crud_read_limiter("unit")
    @blp_unit.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_unit.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_unit.doc(
        summary="Retrieve units based on role and permissions",
        description="""
            Retrieve unit details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all units in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to units belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Unit(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "units": [
                                    {
                                        "unit": "km",
                                        "name": "Kilometer",
                                        "status": "Active",
                                        "business_id": "abcd1234"
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10
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
                "description": "Units not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Units not found"
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
                            "message": "An unexpected error occurred while retrieving the units.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, unit_data):
        page = unit_data.get("page")
        per_page = unit_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = unit_data.get("business_id")
        query_user_id = unit_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][UnitListResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    units_result = Unit.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All units for that business
                    units_result = Unit.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all units in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: units in own business")

                units_result = Unit.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own units in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own units only")

                units_result = Unit.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no units found
            if not units_result or not units_result.get("units"):
                Log.info(f"{log_tag} Units not found")
                return prepared_response(False, "NOT_FOUND", "Units not found")

            Log.info(
                f"{log_tag} unit(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload (keep using jsonify so you can include `data`)
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": units_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving units: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the units. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving units: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# BEGINNIG OF CATEGORY
@blp_category.route("/category", methods=["POST", "GET", "PATCH", "DELETE"])
class CategoryResource(MethodView):

    # ---------- CREATE ----------
    @token_required
    @crud_write_limiter("category")
    @blp_category.arguments(CategorySchema, location="form")
    @blp_category.response(201, CategorySchema)
    @blp_category.doc(
        summary="Create a new category",
        description="""
            Create a new category for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a category for any business.
                - If omitted, defaults to their own business_id.
            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": CategorySchema,
                    "example": {
                        "name": "Electronics",
                        "slug": "electronics",
                        "status": "Active"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new category."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][CategoryResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # 1️⃣ Check if the category already exists (by name) in this business
        try:
            Log.info(f"{log_tag} checking if category already exists")
            exists = Category.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")},
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating category uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} category already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Category already exists",
            )

        # 2️⃣ Create and save category
        try:
            item = Category(**item_data)

            Log.info(f"{log_tag} committing category: {item_data.get('name')}")
            start_time = time.time()

            category_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} category created with id={category_id} "
                f"in {duration:.2f} seconds"
            )

            return prepared_response(
                True,
                "OK",
                "Category created successfully.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the category.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while creating category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE ----------
    @token_required
    @crud_read_limiter("category")
    @blp_category.arguments(CategoryIdQuerySchema, location="query")
    @blp_category.response(200, CategorySchema)
    @blp_category.doc(
        summary="Retrieve category by category_id (role-aware)",
        description="""
            Retrieve a category by `category_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, category_data):
        category_id = category_data.get("category_id")
        query_business_id = category_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][CategoryResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[category_id:{category_id}]"
        )

        try:
            # ---------------------------------------------------
            # ROLE-AWARE BUSINESS RESOLUTION
            # ---------------------------------------------------
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting category. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting category in own business")

            # ---------------------------------------------------
            # FETCH CATEGORY
            # ---------------------------------------------------
            category = Category.get_by_id(category_id, target_business_id)

            if not category:
                Log.info(f"{log_tag} category not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Category not found.",
                )

            Log.info(f"{log_tag} category found")

            return prepared_response(
                True,
                "OK",
                "Category retrieved successfully.",
                data=category,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError retrieving category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving the category.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error retrieving category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
    
    # ---------- PATCH (UPDATE PARTIAL) ----------
    @token_required
    @crud_write_limiter("category")
    @blp_category.arguments(CategoryUpdateSchema, location="form")
    @blp_category.response(200, CategorySchema)
    @blp_category.doc(
        summary="Partially update an existing category",
        description="""
            This endpoint allows you to partially update an existing category by providing `category_id` in the request body.
            - **PATCH**: Update one or more fields such as category name, slug, and status.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": CategoryUpdateSchema,
                    "example": {
                        "category_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Updated Electronics",
                        "status": "Inactive"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to partially update an existing category."""
        category_id = item_data.get("category_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        business_id = str(user_info.get("business_id"))
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = business_id

        log_tag = f"[admin_setup_resource.py][CategoryResource][patch][{client_ip}][{business_id}][{category_id}]"

        Log.info(f"{log_tag} check_category")

        # Check that category exists
        category = Category.get_by_id(category_id, business_id)
        if not category:
            Log.info(f"{log_tag} category not found")
            return prepared_response(False, "NOT_FOUND", "Category not found")

        # Do not allow overriding the id
        item_data.pop("category_id", None)

        try:
            Log.info(f"{log_tag} updating category (PATCH)")
            start_time = time.time()

            update_ok = Category.update(category_id, **item_data)

            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating category completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Category updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update category.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the category.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE ----------
    @token_required
    @crud_delete_limiter("category")
    @blp_category.arguments(CategoryIdQuerySchema, location="query")
    @blp_category.response(200)
    @blp_category.doc(
        summary="Delete a category by category_id (role-aware)",
        description="""
            Delete a category using `category_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.

            Permissions are enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, category_data):
        category_id = category_data["category_id"]
        query_business_id = category_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][CategoryResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[category_id:{category_id}]"
        )

        # -------- Resolve target business_id based on role --------
        try:
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner deleting category. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin deleting category in own business")
        except Exception as e:
            Log.info(f"{log_tag} error resolving target business_id: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while resolving business context.",
                errors=str(e),
            )

        # -------- Fetch category --------
        try:
            category = Category.get_by_id(category_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the category.",
                errors=str(e),
            )

        if not category:
            Log.info(f"{log_tag} category not found")
            return prepared_response(False, "NOT_FOUND", "Category not found")

        image_path = category.get("file_path") if category.get("image") else None

        # -------- Delete category --------
        try:
            Log.info(f"{log_tag} deleting category")
            delete_success = Category.delete(category_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to delete category",
                )

            # Try delete image if present
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} category image {image_path} deleted successfully.")
                except Exception as img_e:
                    Log.info(f"{log_tag} error deleting category image: {img_e}")

            return prepared_response(True, "OK", "Category deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the category.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting category: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_category.route("/categories", methods=["GET"])
class CategoriesResource(MethodView):
    @token_required
    @crud_read_limiter("category")
    @blp_category.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_category.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_category.doc(
        summary="Retrieve categories by user__id or business_id",
        description="""
            This endpoint allows you to retrieve category details either by the user's `user__id` or the `business_id`. 
            You can pass one or both parameters in the query string to filter the results.

            Behaviour:
            - If `user__id` is provided, categories are filtered by that user and business.
            - Otherwise, categories are filtered only by `business_id`.
            - If no `business_id` is provided, it defaults to the authenticated user's `business_id`.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Category(ies) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "categories": [
                                    {
                                        "category_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Electronics",
                                        "slug": "electronics",
                                        "status": "Active",
                                        "business_id": "abcd1234"
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10
                            }
                        }
                    }
                }
            },
            404: {
                "description": "Categories not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Categories not found"
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
                            "message": "An unexpected error occurred while retrieving the categories.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, category_data):
        page = category_data.get("page")
        per_page = category_data.get("per_page")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        # Optional query overrides
        query_business_id = category_data.get("business_id")
        query_user__id = category_data.get("user__id")

        # Effective filters
        target_business_id = query_business_id or auth_business_id
        target_user__id = query_user__id  # may be None

        log_tag = (
            f"[admin_setup_resource.py][CategoriesResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[auth_user__id:{auth_user__id}]"
        )

        try:
            # Decide which helper to use
            if target_user__id:
                Log.info(f"{log_tag} Filtering by user__id + business_id")
                categories_result = Category.get_by_user__id_and_business_id(
                    user__id=target_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )
            else:
                Log.info(f"{log_tag} Filtering by business_id only")
                categories_result = Category.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no categories found
            if not categories_result or not categories_result.get("categories"):
                Log.info(f"{log_tag} Categories not found")
                return prepared_response(False, "NOT_FOUND", "Categories not found")

            Log.info(
                f"{log_tag} category(ies) found "
                f"[target_user__id:{target_user__id}, target_business_id:{target_business_id}]"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": categories_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving categories: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the categories.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving categories: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


# ---------------------- SUBCATEGORY RESOURCES ---------------------- #
@blp_sub_category.route("/sub-category", methods=["POST", "GET", "PATCH", "DELETE"])
class SubCategoryResource(MethodView):

    # ---------- CREATE ----------
    @token_required
    @crud_write_limiter("subcategory")
    @blp_sub_category.arguments(SubCategorySchema, location="form")
    @blp_sub_category.response(201, SubCategorySchema)
    @blp_sub_category.doc(
        summary="Create a new subcategory",
        description="""
            Create a new subcategory for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a subcategory for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubCategorySchema,
                    "example": {
                        "name": "Electronics",
                        "code": "electronics",
                        "category_id": "60a6b938d4d8c24fa0804d62",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                        "image": "file (image.jpg)"
                    }
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new subcategory."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][SubCategoryResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                # keep same pattern as other resources: use auth business_id for path
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} image upload failed: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        # Existence check by name within target business
        try:
            Log.info(f"{log_tag} checking if subcategory already exists")
            exists = SubCategory.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate subcategory: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating subcategory uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} subcategory already exists")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "CONFLICT",
                "Subcategory already exists",
            )

        # Create a new subcategory instance
        item = SubCategory(**item_data)

        try:
            Log.info(f"{log_tag} committing subcategory: {item_data.get('name')}")
            start_time = time.time()

            subcategory_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} subcategory created with id={subcategory_id} "
                f"in {duration:.2f} seconds"
            )

            if subcategory_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Subcategory created successfully.",
                )
            else:
                if actual_path:
                    try:
                        os.remove(actual_path)
                    except Exception:
                        pass
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create subcategory.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating subcategory: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the subcategory.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating subcategory: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("subcategory")
    @blp_sub_category.arguments(SubCategoryIdQuerySchema, location="query")
    @blp_sub_category.response(200, SubCategorySchema)
    @blp_sub_category.doc(
        summary="Retrieve subcategory by subcategory_id (role-aware)",
        description="""
            Retrieve a subcategory by `subcategory_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, subcategory_data):
        subcategory_id = subcategory_data.get("subcategory_id")
        query_business_id = subcategory_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][SubCategoryResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[subcategory_id:{subcategory_id}]"
        )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting subcategory. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting subcategory in own business")

            subcategory = SubCategory.get_by_id(subcategory_id, target_business_id)

            if not subcategory:
                Log.info(f"{log_tag} subcategory not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Subcategory not found.",
                )

            Log.info(f"{log_tag} subcategory found")
            # As with UnitResource, we only send a success message for now.
            return prepared_response(
                True,
                "OK",
                "Subcategory retrieved successfully.",
                 data=subcategory,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError retrieving subcategory: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving the subcategory.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error retrieving subcategory: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (UPDATE PARTIAL, role-aware) ----------
    @token_required
    @crud_write_limiter("subcategory")
    @blp_sub_category.arguments(SubCategoryUpdateSchema, location="form")
    @blp_sub_category.response(200, SubCategoryUpdateSchema)
    @blp_sub_category.doc(
        summary="Partially update an existing subcategory (role-aware)",
        description="""
            Partially update an existing subcategory by providing `subcategory_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubCategoryUpdateSchema,
                    "example": {
                        "subcategory_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Smartphones",
                        "code": "smartphones",
                        "description": "Handheld smart devices",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                        "image": "file (image.jpg)"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing subcategory."""
        subcategory_id = item_data.get("subcategory_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][SubCategoryResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[subcategory_id:{subcategory_id}]"
        )

        # Check if the subcategory exists
        try:
            subcategory = SubCategory.get_by_id(subcategory_id, target_business_id)
            Log.info(f"{log_tag} check_subcategory")
        except Exception as e:
            Log.info(f"{log_tag} error checking subcategory existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the subcategory.",
                errors=str(e),
            )

        if not subcategory:
            Log.info(f"{log_tag} subcategory not found")
            return prepared_response(False, "NOT_FOUND", "Subcategory not found")

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} image upload failed: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        old_image = subcategory.get("file_path")

        try:
            Log.info(f"{log_tag} updating subcategory (PATCH)")
            start_time = time.time()

            # Do not override id field
            item_data.pop("subcategory_id", None)

            update_ok = SubCategory.update(subcategory_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating subcategory completed in {duration:.2f} seconds")
                # Remove old image after successful update, if changed
                if old_image and old_image != actual_path:
                    try:
                        delete_old_image(old_image)
                        Log.info(f"{log_tag} old image removed successfully")
                    except Exception as img_e:
                        Log.info(f"{log_tag} error removing old image: {img_e}")
                return prepared_response(True, "OK", "Subcategory updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                if actual_path:
                    try:
                        os.remove(actual_path)
                    except Exception:
                        pass
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update subcategory.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating subcategory: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the subcategory.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating subcategory: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("subcategory")
    @blp_sub_category.arguments(SubCategoryIdQuerySchema, location="query")
    @blp_sub_category.response(200)
    @blp_sub_category.doc(
        summary="Delete a subcategory by subcategory_id (role-aware)",
        description="""
            Delete a subcategory using `subcategory_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, subcategory_data):
        subcategory_id = subcategory_data.get("subcategory_id")
        query_business_id = subcategory_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][SubCategoryResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][subcategory_id:{subcategory_id}]"
        )

        # Retrieve the subcategory
        try:
            subcategory = SubCategory.get_by_id(subcategory_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching subcategory: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the subcategory.",
                errors=str(e),
            )

        if not subcategory:
            Log.info(f"{log_tag} subcategory not found")
            return prepared_response(False, "NOT_FOUND", "Subcategory not found.")

        image_path = subcategory.get("file_path") if subcategory.get("image") else None

        # Attempt to delete the subcategory
        try:
            delete_success = SubCategory.delete(subcategory_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete subcategory.")

            # Try deleting image if present
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} subcategory image {image_path} deleted successfully.")
                except Exception as img_e:
                    Log.info(f"{log_tag} error deleting subcategory image: {img_e}")

            Log.info(f"{log_tag} subcategory deleted successfully")
            return prepared_response(True, "OK", "Subcategory deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting subcategory: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the subcategory.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting subcategory: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


# ---------- LIST / PAGINATED ----------
@blp_sub_category.route("/sub-categories", methods=["GET"])
class SubCategoriesResource(MethodView):
    @token_required
    @crud_read_limiter("subcategory")
    @blp_sub_category.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_sub_category.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_sub_category.doc(
        summary="Retrieve subcategories (role-aware, with optional business/user filters)",
        description="""
            Retrieve subcategory details with role-aware filtering.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - may submit ?user__id=<id> to filter subcategories by a specific user within that business
                - if business_id is omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id
                - results are filtered by the authenticated user's user__id.

            Pagination:
                - page: optional, default from environment
                - per_page: optional, default from environment
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Subcategory(ies) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "subcategories": [
                                    {
                                        "subcategory_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Smartphones",
                                        "code": "smartphones",
                                        "status": "Active",
                                        "business_id": "abcd1234"
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10
                            }
                        }
                    }
                }
            },
            404: {
                "description": "Subcategories not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Subcategories not found"
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
                            "message": "An unexpected error occurred while retrieving the subcategories.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, subcategory_data):
        # Query values
        page = subcategory_data.get("page")
        per_page = subcategory_data.get("per_page")
        query_business_id = subcategory_data.get("business_id")
        query_user__id = subcategory_data.get("user__id")
        user_id = subcategory_data.get("user_id")  # only used for logging if present

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][SubCategoriesResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            subcategories_result = None

            # -----------------------------
            # ROLE: SYSTEM OWNER / SUPER ADMIN
            # -----------------------------
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner listing subcategories. "
                    f"target_business_id={target_business_id}, query_user__id={query_user__id}"
                )

                if query_user__id:
                    # Admin filtering by specific user within a business
                    subcategories_result = SubCategory.get_all_by_user__id_and_business_id(
                        query_user__id,
                        target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # Admin listing all subcategories for a business
                    subcategories_result = SubCategory.get_by_business_id(
                        target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            # -----------------------------
            # ROLE: OTHER (BUSINESS_OWNER / STAFF / etc.)
            # -----------------------------
            else:
                target_business_id = auth_business_id

                Log.info(
                    f"{log_tag} non-admin listing subcategories in own business "
                    f"(user__id={auth_user__id})"
                )

                # Non-admins are always scoped to their own user__id + business_id
                subcategories_result = SubCategory.get_by_user__id_and_business_id(
                    auth_user__id,
                    target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # -----------------------------
            # CHECK RESULTS
            # -----------------------------
            if not subcategories_result or not subcategories_result.get("subcategories"):
                Log.info(f"{log_tag} Subcategories not found")
                return prepared_response(False, "NOT_FOUND", "Subcategories not found")

            Log.info(
                f"{log_tag} subcategory(ies) found "
                f"[user_id:{user_id}, business_id:{target_business_id}]"
            )

            # Return full payload (subcategories + pagination meta)
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": subcategories_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving subcategories: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the subcategories.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving subcategories: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# ---------------------- SUBCATEGORY MODEL ---------------------- #

# BEGINNING OF BRANDS
# ---------------------- BRAND RESOURCES ---------------------- #

@blp_brand.route("/brand", methods=["POST", "GET", "PATCH", "DELETE"])
class BrandResource(MethodView):

    # ---------- CREATE (role-aware) ----------
    @token_required
    @crud_write_limiter("brand")
    @blp_brand.arguments(BrandSchema, location="form")
    @blp_brand.response(201, BrandSchema)
    @blp_brand.doc(
        summary="Create a new brand",
        description="""
            Create a new brand for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a brand for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": BrandSchema,
                    "example": {
                        "name": "Apple",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new brand."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][BrandResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        Log.info(f"{log_tag} checking if brand already exists")

        # Hash-based existence check
        try:
            exists = Brand.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating brand uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} brand already exists")
            return prepared_response(False, "CONFLICT", "Brand already exists")

        # Create a new Brand instance
        item = Brand(**item_data)

        try:
            Log.info(f"{log_tag} committing brand: {item_data.get('name')}")
            start_time = time.time()
            brand_id = item.save()
            duration = time.time() - start_time
            Log.info(
                f"{log_tag} brand created with id={brand_id} "
                f"in {duration:.2f} seconds"
            )

            if brand_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Brand created successfully.",
                )
            else:
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create brand.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the brand.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("brand")
    @blp_brand.arguments(BrandIdQuerySchema, location="query")
    @blp_brand.response(200, BrandSchema)
    @blp_brand.doc(
        summary="Retrieve brand by brand_id (role-aware)",
        description="""
            Retrieve a brand by `brand_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, brand_data):
        brand_id = brand_data.get("brand_id")
        query_business_id = brand_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][BrandResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[brand_id:{brand_id}]"
        )

        if not brand_id:
            Log.info(f"{log_tag} brand_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "brand_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting brand. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting brand in own business")

            start_time = time.time()
            brand = Brand.get_by_id(brand_id, target_business_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} retrieving brand completed in {duration:.2f} seconds")

            if not brand:
                Log.info(f"{log_tag} brand not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Brand not found.",
                )

            Log.info(f"{log_tag} brand found")
            return prepared_response(
                True,
                "OK",
                "Brand retrieved successfully.",
                data=brand,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the brand.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (PARTIAL UPDATE, role-aware) ----------
    @token_required
    @crud_write_limiter("brand")
    @blp_brand.arguments(BrandUpdateSchema, location="form")
    @blp_brand.response(200, BrandUpdateSchema)
    @blp_brand.doc(
        summary="Partially update an existing brand (role-aware)",
        description="""
            Partially update an existing brand by providing `brand_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": BrandUpdateSchema,
                    "example": {
                        "brand_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Apple",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing brand."""
        brand_id = item_data.get("brand_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][BrandResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[brand_id:{brand_id}]"
        )

        if not brand_id:
            Log.info(f"{log_tag} brand_id not provided")
            return prepared_response(False, "BAD_REQUEST", "brand_id must be provided.")

        # Check existing brand within target business scope
        try:
            brand = Brand.get_by_id(brand_id, target_business_id)
            Log.info(f"{log_tag} check_brand")
        except Exception as e:
            Log.info(f"{log_tag} error checking brand existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the brand.",
                errors=str(e),
            )

        if not brand:
            Log.info(f"{log_tag} brand not found")
            return prepared_response(False, "NOT_FOUND", "Brand not found")

        try:
            Log.info(f"{log_tag} updating brand (PATCH)")
            start_time = time.time()

            # Remove brand_id before updating
            item_data.pop("brand_id", None)

            update_ok = Brand.update(brand_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating brand completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Brand updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update brand.")
        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the brand.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("brand")
    @blp_brand.arguments(BrandIdQuerySchema, location="query")
    @blp_brand.response(200)
    @blp_brand.doc(
        summary="Delete a brand by brand_id (role-aware)",
        description="""
            Delete a brand using `brand_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, brand_data):
        brand_id = brand_data.get("brand_id")
        query_business_id = brand_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][BrandResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][brand_id:{brand_id}]"
        )

        if not brand_id:
            Log.info(f"{log_tag} brand_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "brand_id must be provided.")

        # Retrieve the brand
        try:
            brand = Brand.get_by_id(brand_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the brand.",
                errors=str(e),
            )

        if not brand:
            Log.info(f"{log_tag} brand not found")
            return prepared_response(False, "NOT_FOUND", "Brand not found.")

        # Attempt to delete the brand
        try:
            delete_success = Brand.delete(brand_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete brand.")

            Log.info(f"{log_tag} brand deleted successfully")
            return prepared_response(True, "OK", "Brand deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the brand.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting brand: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# ---------- LIST / PAGINATED ----------

@blp_brand.route("/brands", methods=["GET"])
class BrandsResource(MethodView):
    @token_required
    @crud_read_limiter("brand")
    @blp_brand.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_brand.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_brand.doc(
        summary="Retrieve brands based on role and permissions",
        description="""
            Retrieve brand details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all brands in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to brands belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Brand(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "brands": [
                                    {
                                        "brand_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Nike",
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                        "image": "https://example.com/uploads/nike.jpg",
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
                "description": "Brands not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Brands not found"
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
                            "message": "An unexpected error occurred while retrieving the brands.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, brand_data):
        page = brand_data.get("page")
        per_page = brand_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = brand_data.get("business_id")
        query_user_id = brand_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][BrandsResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    brands_result = Brand.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All brands for that business
                    brands_result = Brand.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all brands in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: brands in own business")

                brands_result = Brand.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own brands in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own brands only")

                brands_result = Brand.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no brands found
            if not brands_result or not brands_result.get("brands"):
                Log.info(f"{log_tag} Brands not found")
                return prepared_response(False, "NOT_FOUND", "Brands not found")

            Log.info(
                f"{log_tag} brand(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": brands_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving brands: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the brands. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving brands: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# BEGINNING OF VARIANT
@blp_variant.route("/variant", methods=["POST", "GET", "PATCH", "DELETE"])
class VariantResource(MethodView):

    # ---------- CREATE (role-aware) ----------
    @token_required
    @crud_write_limiter("variant")
    @blp_variant.arguments(VariantSchema, location="form")
    @blp_variant.response(201, VariantSchema)
    @blp_variant.doc(
        summary="Create a new variant",
        description="""
            Create a new variant for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a variant for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": VariantSchema,
                    "example": {
                        "name": "Size",
                        "values": "Small, Medium, Large",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                        "image": "file (image.jpg)"
                    }
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new variant."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][VariantResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                # Use auth business_id for storage path (same as other resources)
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} image upload failed: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        Log.info(f"{log_tag} checking if variant already exists")

        # Hash-based existence check by name within target business
        try:
            exists = Variant.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate variant: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating variant uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} variant already exists")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(False, "CONFLICT", "Variant already exists")

        # Create a new variant instance
        item = Variant(**item_data)

        try:
            Log.info(f"{log_tag} committing variant: {item_data.get('name')}")
            start_time = time.time()
            variant_id = item.save()
            duration = time.time() - start_time
            Log.info(
                f"{log_tag} variant created with id={variant_id} "
                f"in {duration:.2f} seconds"
            )

            if variant_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Variant created successfully.",
                )
            else:
                if actual_path:
                    try:
                        os.remove(actual_path)
                    except Exception:
                        pass
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create variant.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating variant: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the variant.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating variant: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("variant")
    @blp_variant.arguments(VariantIdQuerySchema, location="query")
    @blp_variant.response(200, VariantSchema)
    @blp_variant.doc(
        summary="Retrieve variant by variant_id (role-aware)",
        description="""
            Retrieve a variant by `variant_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, variant_data):
        variant_id = variant_data.get("variant_id")
        query_business_id = variant_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][VariantResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[variant_id:{variant_id}]"
        )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting variant. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting variant in own business")

            start_time = time.time()
            variant = Variant.get_by_id(variant_id, target_business_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} retrieving variant completed in {duration:.2f} seconds")

            if not variant:
                Log.info(f"{log_tag} variant not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Variant not found.",
                )

            Log.info(f"{log_tag} variant found")
            return prepared_response(
                True,
                "OK",
                "Variant retrieved successfully.",
                data=variant,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the variant.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (PARTIAL UPDATE, role-aware) ----------
    @token_required
    @crud_write_limiter("variant")
    @blp_variant.arguments(VariantUpdateSchema, location="form")
    @blp_variant.response(200, VariantSchema)
    @blp_variant.doc(
        summary="Partially update an existing variant (role-aware)",
        description="""
            Partially update an existing variant by providing `variant_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": VariantUpdateSchema,
                    "example": {
                        "variant_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Size",
                        "values": "S, M, L",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                        "image": "file (image.jpg)"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing variant."""
        variant_id = item_data.get("variant_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][VariantResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[variant_id:{variant_id}]"
        )

        # Check existing variant within target business scope
        try:
            variant = Variant.get_by_id(variant_id, target_business_id)
            Log.info(f"{log_tag} check_variant")
        except Exception as e:
            Log.info(f"{log_tag} error checking variant existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the variant.",
                errors=str(e),
            )

        if not variant:
            Log.info(f"{log_tag} variant not found")
            return prepared_response(False, "NOT_FOUND", "Variant not found")

        # Handle new image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} image upload failed: {e}")
                return prepared_response(False, "BAD_REQUEST", str(e))

        old_image = variant.get("file_path")

        try:
            Log.info(f"{log_tag} updating variant (PATCH)")
            start_time = time.time()

            # Remove variant_id before updating
            item_data.pop("variant_id", None)

            update_ok = Variant.update(variant_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating variant completed in {duration:.2f} seconds")

                # Delete old image after successful update, if changed
                if old_image and old_image != actual_path:
                    try:
                        delete_old_image(old_image)
                        Log.info(f"{log_tag} old image {old_image} removed successfully")
                    except Exception as img_e:
                        Log.info(f"{log_tag} error removing old image: {img_e}")

                return prepared_response(True, "OK", "Variant updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                if actual_path:
                    try:
                        os.remove(actual_path)
                    except Exception:
                        pass
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update variant.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating variant: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the variant.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating variant: {e}")
            if actual_path:
                try:
                    os.remove(actual_path)
                except Exception:
                    pass
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("variant")
    @blp_variant.arguments(VariantIdQuerySchema, location="query")
    @blp_variant.response(200)
    @blp_variant.doc(
        summary="Delete a variant by variant_id (role-aware)",
        description="""
            Delete a variant using `variant_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, variant_data):
        variant_id = variant_data.get("variant_id")
        query_business_id = variant_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][VariantResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][variant_id:{variant_id}]"
        )

        # Retrieve the variant
        try:
            variant = Variant.get_by_id(variant_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the variant.",
                errors=str(e),
            )

        if not variant:
            Log.info(f"{log_tag} variant not found")
            return prepared_response(False, "NOT_FOUND", "Variant not found.")

        image_path = variant.get("file_path") if variant.get("image") else None

        # Attempt to delete the variant
        try:
            delete_success = Variant.delete(variant_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete variant.")

            # Try deleting image if present
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} variant image {image_path} deleted successfully.")
                except Exception as img_e:
                    Log.info(f"{log_tag} error deleting variant image: {img_e}")

            Log.info(f"{log_tag} variant deleted successfully")
            return prepared_response(True, "OK", "Variant deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the variant.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# ---------- LIST / PAGINATED ----------
@blp_variant.route("/variants", methods=["GET"])
class VariantsResource(MethodView):
    @token_required
    @crud_read_limiter("variant")
    @blp_variant.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_variant.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_variant.doc(
        summary="Retrieve variants based on role and permissions",
        description="""
            Retrieve variant details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all variants in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to variants belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Variant(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "variants": [
                                    {
                                        "variant_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Color",
                                        "values": "Red, Blue, Green",
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                        "image": "https://example.com/uploads/variant-red.jpg",
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
                "description": "Variants not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Variants not found"
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
                            "message": "An unexpected error occurred while retrieving the variants.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, variant_data):
        page = variant_data.get("page")
        per_page = variant_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = variant_data.get("business_id")
        query_user_id = variant_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][VariantsResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    variants_result = Variant.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All variants for that business
                    variants_result = Variant.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all variants in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: variants in own business")

                variants_result = Variant.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own variants in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own variants only")

                variants_result = Variant.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no variants found
            if not variants_result or not variants_result.get("variants"):
                Log.info(f"{log_tag} Variants not found")
                return prepared_response(False, "NOT_FOUND", "Variants not found")

            Log.info(
                f"{log_tag} variant(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": variants_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving variants: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the variants. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving variants: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# BEGINNING OF TAX
@blp_tax.route("/tax", methods=["POST", "GET", "PATCH", "DELETE"])
class TaxResource(MethodView):

    # ---------- CREATE (role-aware) ----------
    @token_required
    @crud_write_limiter("tax")
    @blp_tax.arguments(TaxSchema, location="form")
    @blp_tax.response(201, TaxSchema)
    @blp_tax.doc(
        summary="Create a new tax",
        description="""
            Create a new tax for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a tax for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": TaxSchema,
                    "example": {
                        "name": "Sales Tax",
                        "rate": "5",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new tax."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][TaxResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        Log.info(f"{log_tag} checking if tax already exists")

        # Hash-based existence check (same style as Brand/Variant)
        try:
            exists = Tax.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating tax uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} tax already exists")
            return prepared_response(False, "CONFLICT", "Tax already exists")

        # Create a new Tax instance
        item = Tax(**item_data)

        try:
            Log.info(f"{log_tag} committing tax: {item_data.get('name')}")
            start_time = time.time()
            tax_id = item.save()
            duration = time.time() - start_time
            Log.info(
                f"{log_tag} tax created with id={tax_id} "
                f"in {duration:.2f} seconds"
            )

            if tax_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Tax created successfully.",
                )
            else:
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create tax.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the tax.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("tax")
    @blp_tax.arguments(TaxIdQuerySchema, location="query")
    @blp_tax.response(200, TaxSchema)
    @blp_tax.doc(
        summary="Retrieve tax by tax_id (role-aware)",
        description="""
            Retrieve a tax by `tax_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, tax_data):
        tax_id = tax_data.get("tax_id")
        query_business_id = tax_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][TaxResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[tax_id:{tax_id}]"
        )

        if not tax_id:
            Log.info(f"{log_tag} tax_id not provided")
            return prepared_response(False, "BAD_REQUEST", "tax_id must be provided.")

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting tax. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting tax in own business")

            start_time = time.time()
            tax = Tax.get_by_id(tax_id, target_business_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} retrieving tax completed in {duration:.2f} seconds")

            if not tax:
                Log.info(f"{log_tag} tax not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Tax not found.",
                )

            Log.info(f"{log_tag} tax found")
            return prepared_response(
                True,
                "OK",
                "Tax retrieved successfully.",
                data=tax,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the tax.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (PARTIAL UPDATE, role-aware) ----------
    @token_required
    @crud_write_limiter("tax")
    @blp_tax.arguments(TaxUpdateSchema, location="form")
    @blp_tax.response(200, TaxUpdateSchema)
    @blp_tax.doc(
        summary="Partially update an existing tax (role-aware)",
        description="""
            Partially update an existing tax by providing `tax_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": TaxUpdateSchema,
                    "example": {
                        "tax_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Sales Tax",
                        "rate": "7",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing tax."""
        tax_id = item_data.get("tax_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][TaxResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[tax_id:{tax_id}]"
        )

        if not tax_id:
            Log.info(f"{log_tag} tax_id not provided")
            return prepared_response(False, "BAD_REQUEST", "tax_id must be provided.")

        # Check existing tax within target business scope
        try:
            tax = Tax.get_by_id(tax_id, target_business_id)
            Log.info(f"{log_tag} check_tax")
        except Exception as e:
            Log.info(f"{log_tag} error checking tax existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the tax.",
                errors=str(e),
            )

        if not tax:
            Log.info(f"{log_tag} tax not found")
            return prepared_response(False, "NOT_FOUND", "Tax not found")

        try:
            Log.info(f"{log_tag} updating tax (PATCH)")
            start_time = time.time()

            # Remove tax_id before updating
            item_data.pop("tax_id", None)

            update_ok = Tax.update(tax_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating tax completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Tax updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update tax.")
        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the tax.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("tax")
    @blp_tax.arguments(TaxIdQuerySchema, location="query")
    @blp_tax.response(200)
    @blp_tax.doc(
        summary="Delete a tax by tax_id (role-aware)",
        description="""
            Delete a tax using `tax_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, tax_data):
        tax_id = tax_data.get("tax_id")
        query_business_id = tax_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][TaxResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][tax_id:{tax_id}]"
        )

        if not tax_id:
            Log.info(f"{log_tag} tax_id not provided")
            return prepared_response(False, "BAD_REQUEST", "tax_id must be provided.")

        # Retrieve the tax
        try:
            tax = Tax.get_by_id(tax_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the tax.",
                errors=str(e),
            )

        if not tax:
            Log.info(f"{log_tag} tax not found")
            return prepared_response(False, "NOT_FOUND", "Tax not found.")

        # Attempt to delete the tax
        try:
            Log.info(f"{log_tag} deleting tax")
            delete_success = Tax.delete(tax_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete tax.")

            Log.info(f"{log_tag} tax deleted successfully")
            return prepared_response(True, "OK", "Tax deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the tax.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting tax: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# ---------- LIST / PAGINATED ----------

@blp_tax.route("/taxes", methods=["GET"])
class TaxesResource(MethodView):
    @token_required
    @crud_read_limiter("tax")
    @blp_tax.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_tax.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_tax.doc(
        summary="Retrieve taxes based on role and permissions",
        description="""
            Retrieve tax details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all taxes in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to taxes belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
    )
    def get(self, tax_data):
        page = tax_data.get("page")
        per_page = tax_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = tax_data.get("business_id")
        query_user_id = tax_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        try:
            account_type = account_type_enc if account_type_enc else None
        except Exception:
            account_type = None  # fallback to "other staff" behaviour if decryption fails

        log_tag = (
            f"[admin_setup_resource.py][TaxesResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    taxes_result = Tax.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All taxes for that business
                    taxes_result = Tax.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS.get("BUSINESS_OWNER"):
                # Business owners see all taxes in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: taxes in own business")

                taxes_result = Tax.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own taxes in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own taxes only")

                taxes_result = Tax.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no taxes found
            if not taxes_result or not taxes_result.get("taxes"):
                Log.info(f"{log_tag} Taxes not found for target_business_id={target_business_id}")
                return prepared_response(False, "NOT_FOUND", "Taxes not found")

            Log.info(
                f"{log_tag} tax(es) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": taxes_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving taxes: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the taxes. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving taxes: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# BEGINNING OF WARRANTY
@blp_warranty.route("/warranty", methods=["POST", "GET", "PATCH", "DELETE"])
class WarrantyResource(MethodView):

    # ---------- CREATE (role-aware) ----------
    @token_required
    @crud_write_limiter("warranty")
    @blp_warranty.arguments(WarrantySchema, location="form")
    @blp_warranty.response(201, WarrantySchema)
    @blp_warranty.doc(
        summary="Create a new warranty (role-aware)",
        description="""
            Create a new warranty for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a warranty for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": WarrantySchema,
                    "example": {
                        "name": "Product Warranty",
                        "duration": 12,
                        "period": "Month",
                        "status": "Active",
                        "description": "12-month warranty",
                        "business_id": "optional for system_owner/super_admin"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new warranty."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        if not auth_business_id or not user_info.get("user_id"):
            return prepared_response(False, "UNAUTHORIZED", "Authentication token is required")

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][WarrantyResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        Log.info(f"{log_tag} checking if warranty already exists")

        try:
            exists = Warranty.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating warranty uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} warranty already exists")
            return prepared_response(False, "CONFLICT", "Warranty already exists")

        # Create a new warranty instance
        item = Warranty(**item_data)

        try:
            Log.info(f"{log_tag} committing warranty: {item_data.get('name')}")
            start_time = time.time()
            warranty_id = item.save()
            duration = time.time() - start_time
            Log.info(
                f"{log_tag} warranty created with id={warranty_id} "
                f"in {duration:.2f} seconds"
            )

            if warranty_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Warranty created successfully.",
                )
            else:
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create warranty.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the warranty.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("warranty")
    @blp_warranty.arguments(WarrantyIdQuerySchema, location="query")
    @blp_warranty.response(200, WarrantySchema)
    @blp_warranty.doc(
        summary="Retrieve warranty by warranty_id (role-aware)",
        description="""
            Retrieve a warranty by `warranty_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, warranty_data):
        warranty_id = warranty_data.get("warranty_id")
        query_business_id = warranty_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][WarrantyResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[warranty_id:{warranty_id}]"
        )

        if not warranty_id:
            return prepared_response(False, "BAD_REQUEST", "warranty_id must be provided.")

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting warranty. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting warranty in own business")

            start_time = time.time()
            warranty = Warranty.get_by_id(warranty_id, target_business_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} retrieving warranty completed in {duration:.2f} seconds")

            if not warranty:
                Log.info(f"{log_tag} warranty not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Warranty not found.",
                )

            Log.info(f"{log_tag} warranty found")
            return prepared_response(
                True,
                "OK",
                "Warranty retrieved successfully.",
                data=warranty,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the warranty.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (PARTIAL UPDATE, role-aware) ----------
    @token_required
    @crud_write_limiter("warranty")
    @blp_warranty.arguments(WarrantyUpdateSchema, location="form")
    @blp_warranty.response(200, WarrantyUpdateSchema)
    @blp_warranty.doc(
        summary="Partially update an existing warranty (role-aware)",
        description="""
            Partially update an existing warranty by providing `warranty_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": WarrantyUpdateSchema,
                    "example": {
                        "warranty_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Extended Product Warranty",
                        "duration": 24,
                        "period": "Month",
                        "status": "Active",
                        "description": "24-month warranty",
                        "business_id": "optional for system_owner/super_admin"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing warranty."""
        warranty_id = item_data.get("warranty_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        if not warranty_id:
            return prepared_response(False, "BAD_REQUEST", "warranty_id must be provided.")

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][WarrantyResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[warranty_id:{warranty_id}]"
        )

        # Check existing warranty within target business scope
        try:
            warranty = Warranty.get_by_id(warranty_id, target_business_id)
            Log.info(f"{log_tag} check_warranty")
        except Exception as e:
            Log.info(f"{log_tag} error checking warranty existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the warranty.",
                errors=str(e),
            )

        if not warranty:
            Log.info(f"{log_tag} warranty not found")
            return prepared_response(False, "NOT_FOUND", "Warranty not found")

        try:
            Log.info(f"{log_tag} updating warranty (PATCH)")
            start_time = time.time()

            # Remove warranty_id before updating
            item_data.pop("warranty_id", None)

            update_ok = Warranty.update(warranty_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating warranty completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Warranty updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update warranty.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the warranty.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("warranty")
    @blp_warranty.arguments(WarrantyIdQuerySchema, location="query")
    @blp_warranty.response(200)
    @blp_warranty.doc(
        summary="Delete a warranty by warranty_id (role-aware)",
        description="""
            Delete a warranty using `warranty_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, warranty_data):
        warranty_id = warranty_data.get("warranty_id")
        query_business_id = warranty_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        if not warranty_id:
            Log.info(f"[admin_setup_resource.py][WarrantyResource][delete]"
                     f"[{client_ip}][auth_business:{auth_business_id}] warranty_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "warranty_id must be provided.")

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][WarrantyResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][warranty_id:{warranty_id}]"
        )

        # Retrieve the warranty
        try:
            warranty = Warranty.get_by_id(warranty_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the warranty.",
                errors=str(e),
            )

        if not warranty:
            Log.info(f"{log_tag} warranty not found")
            return prepared_response(False, "NOT_FOUND", "Warranty not found.")

        # Attempt to delete the warranty
        try:
            delete_success = Warranty.delete(warranty_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete warranty.")

            Log.info(f"{log_tag} warranty deleted successfully")
            return prepared_response(True, "OK", "Warranty deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the warranty.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting warranty: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


# ------------------------ GET WARRANTIES (LIST, role-aware) ------------------------ #

@blp_warranty.route("/warranties", methods=["GET"])
class WarrantiesResource(MethodView):
    @token_required
    @crud_read_limiter("warranty")
    @blp_warranty.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_warranty.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_warranty.doc(
        summary="Retrieve warranties based on role and permissions",
        description="""
            Retrieve warranty details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all warranties in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to warranties belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
    )
    def get(self, warranty_data):
        page = warranty_data.get("page")
        per_page = warranty_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = warranty_data.get("business_id")
        query_user_id = warranty_data.get("user_id")  # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        try:
            account_type = account_type_enc if account_type_enc else None
        except Exception:
            account_type = None  # fallback to "other staff" behaviour if decryption fails

        log_tag = (
            f"[admin_setup_resource.py][WarrantiesResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    warranties_result = Warranty.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    warranties_result = Warranty.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS.get("BUSINESS_OWNER"):
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: warranties in own business")

                warranties_result = Warranty.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own warranties only")

                warranties_result = Warranty.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no warranties found
            # Expecting model returns {"warranties": [...], "pagination": {...}} (adjust key if yours differs)
            if not warranties_result or not warranties_result.get("warranties"):
                Log.info(f"{log_tag} Warranties not found for target_business_id={target_business_id}")
                return prepared_response(False, "NOT_FOUND", "Warranties not found")

            Log.info(f"{log_tag} warranty(ies) found for target_business_id={target_business_id}")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": warranties_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving warranties: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the warranties. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving warranties: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


# ---------- LIST / PAGINATED ----------


# BEGINNING OF SUPPLIER
@blp_supplier.route("/supplier", methods=["POST", "GET", "PATCH", "DELETE"])
class SupplierResource(MethodView):

    # ------------------------ CREATE SUPPLIER (POST) ------------------------ #
    @token_required
    @crud_read_limiter("supplier")
    @blp_supplier.arguments(SupplierSchema, location="form")
    @blp_supplier.response(201, SupplierSchema)
    @blp_supplier.doc(
        summary="Create a new supplier",
        description="""
            This endpoint allows you to create a new supplier. The request requires
            an `Authorization` header with a Bearer token.

            - **POST**: Create a new supplier by providing details such as
              name, contact, and status.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SupplierSchema,
                    "example": {
                        "name": "ABC Supplies",
                        "contact": "1234567890",
                        "status": "Active",
                        "description": "Supplier of electronic components",
                    },
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """
        Handle the POST request to create a new supplier.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        business_id = str(user_info.get("business_id"))
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = business_id

        log_tag = f"[admin_setup_resource.py][SupplierResource][post][{client_ip}][{business_id}]"

        Log.info(f"{log_tag} checking if supplier already exists")

        # You can switch to check_multiple_item_exists if available in your BaseModel
        if Supplier.check_multiple_item_exists(business_id, {"name": item_data.get("name")}):
            Log.info(f"{log_tag} supplier already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Supplier already exists",
            )

        # Create a new supplier instance
        item = Supplier(**item_data)

        try:
            Log.info(f"{log_tag}[{item_data.get('name')}][committing supplier]")

            start_time = time.time()
            supplier_id = item.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag}[{supplier_id}] committing supplier completed in {duration:.2f} seconds"
            )

            if supplier_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Supplier created successfully.",
                )

            Log.info(f"{log_tag} supplier_id is None after save")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create supplier",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the supplier.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while creating supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------ GET SINGLE SUPPLIER (GET) ------------------------ #
    @token_required
    @blp_supplier.arguments(SupplierIdQuerySchema, location="query")
    @blp_supplier.response(200, SupplierSchema)
    @blp_supplier.doc(
        summary="Retrieve supplier by supplier_id",
        description="""
            This endpoint allows you to retrieve a supplier based on the
            `supplier_id` in the query parameters.

            - **GET**: Retrieve a supplier by providing `supplier_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, supplier_data):
        """
        Handle the GET request to retrieve a single supplier by supplier_id.
        """
        supplier_id = supplier_data.get("supplier_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        business_id = str(user_info.get("business_id"))
        supplier_data["user_id"] = user_info.get("user_id")
        supplier_data["business_id"] = business_id

        log_tag = (
            f"[admin_setup_resource.py][SupplierResource][get]"
            f"[{client_ip}][{business_id}][{supplier_id}]"
        )
        Log.info(f"{log_tag} retrieving supplier by supplier_id")

        try:
            start_time = time.time()
            # NOTE: Supplier.get_by_id currently only takes supplier_id and business_id.
            supplier = Supplier.get_by_id(supplier_id, business_id)
            duration = time.time() - start_time

            Log.info(f"{log_tag} retrieving supplier completed in {duration:.2f} seconds")

            if not supplier:
                Log.info(f"{log_tag} supplier not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Supplier not found",
                )

            Log.info(f"{log_tag} supplier found")

            # Follow Warranty style: include data and set HTTP code explicitly
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": supplier,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the supplier.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------ UPDATE SUPPLIER (PATCH) ------------------------ #
    @token_required
    @blp_supplier.arguments(SupplierUpdateSchema, location="form")
    @blp_supplier.response(200, SupplierUpdateSchema)
    @blp_supplier.doc(
        summary="Partially update an existing supplier",
        description="""
            This endpoint allows you to partially update an existing supplier by providing
            `supplier_id` and one or more fields in the request body.

            - **PATCH**: Partially update an existing supplier; only the provided fields
              will be updated.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SupplierUpdateSchema,
                    "example": {
                        "supplier_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Updated ABC Supplies",
                        "status": "Inactive",
                    },
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """
        Handle the PATCH request to partially update an existing supplier.
        """
        supplier_id = item_data.get("supplier_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        if "business_id" not in user_info or "user_id" not in user_info:
            return prepared_response(
                False,
                "UNAUTHORIZED",
                "Authentication token is required",
            )

        business_id = str(user_info.get("business_id"))
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = business_id

        log_tag = (
            f"[admin_setup_resource.py][SupplierResource][patch]"
            f"[{client_ip}][{business_id}][{supplier_id}]"
        )

        Log.info(f"{log_tag} checking if supplier exists")
        supplier = Supplier.get_by_id(supplier_id, business_id)

        if not supplier:
            Log.info(f"{log_tag} supplier not found")
            return prepared_response(
                False,
                "NOT_FOUND",
                "Supplier not found",
            )

        try:
            Log.info(f"{log_tag} updating supplier (PATCH)")
            start_time = time.time()

            # Don't allow supplier_id to be updated
            item_data.pop("supplier_id", None)

            update_ok = Supplier.update(supplier_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating supplier completed in {duration:.2f} seconds")
                return prepared_response(
                    True,
                    "OK",
                    "Supplier updated successfully.",
                )

            Log.info(f"{log_tag} update returned False")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to update supplier.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the supplier.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------ DELETE SUPPLIER (DELETE) ------------------------ #
    @token_required
    @blp_supplier.arguments(SupplierIdQuerySchema, location="query")
    @blp_supplier.response(200)
    @blp_supplier.doc(
        summary="Delete a supplier by supplier_id",
        description="""
            This endpoint allows you to delete a supplier by providing `supplier_id`
            in the query parameters.

            - **DELETE**: Delete a supplier by providing `supplier_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, supplier_data):
        """
        Handle the DELETE request to remove a supplier by supplier_id.
        """
        supplier_id = supplier_data.get("supplier_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        business_id = str(user_info.get("business_id"))
        supplier_data["user_id"] = user_info.get("user_id")
        supplier_data["business_id"] = business_id

        log_tag = (
            f"[admin_setup_resource.py][SupplierResource][delete]"
            f"[{client_ip}][{business_id}][{supplier_id}]"
        )

        if not supplier_id:
            Log.info(f"{log_tag} supplier_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "supplier_id must be provided.",
            )

        item = Supplier.get_by_id(supplier_id, business_id)

        if not item:
            Log.info(f"{log_tag} supplier not found")
            return prepared_response(
                False,
                "NOT_FOUND",
                "Supplier not found",
            )

        try:
            Log.info(f"{log_tag} deleting supplier")
            delete_success = Supplier.delete(supplier_id, business_id)

            if delete_success:
                return prepared_response(
                    True,
                    "OK",
                    "Supplier deleted successfully",
                )

            Log.info(f"{log_tag} delete returned False")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to delete supplier",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the supplier.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting supplier: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# ------------------------ LIST SUPPLIERS BY BUSINESS (GET) ------------------------ #
@blp_supplier.route("/suppliers", methods=["GET"])
class SupplierListResource(MethodView):

    @token_required
    @blp_supplier.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_supplier.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_supplier.doc(
        summary="Retrieve suppliers based on role and permissions",
        description="""
            Retrieve supplier details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all suppliers in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to suppliers belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Supplier(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "suppliers": [
                                    {
                                        "supplier_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "ABC Supplies",
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                        "email": "contact@abc-supplies.com",
                                        "phone": "+1234567890",
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
            404: {
                "description": "Suppliers not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Suppliers not found"
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
                            "message": "An unexpected error occurred while retrieving the suppliers.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, supplier_data):
        """
        Handle the GET request to retrieve suppliers with role-aware rules.
        """
        page = supplier_data.get("page")
        per_page = supplier_data.get("per_page")

        # Optional filters from query (used mainly by SYSTEM_OWNER / SUPER_ADMIN)
        query_business_id = supplier_data.get("business_id")
        query_user_id = supplier_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][SupplierListResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
        )

        try:
            # Decide which business and which user filter to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                # super_admin/system_owner can see any business; default to own if not provided
                target_business_id = query_business_id or auth_business_id

                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}, query_user_id={query_user_id}"
                )

                if query_user_id:
                    # Filter by a specific user within the chosen business
                    suppliers_result = Supplier.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All suppliers for that business
                    suppliers_result = Supplier.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all suppliers in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: suppliers in own business")

                suppliers_result = Supplier.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own suppliers in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own suppliers only")

                suppliers_result = Supplier.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no suppliers found
            if not suppliers_result or not suppliers_result.get("suppliers"):
                Log.info(f"{log_tag} Suppliers not found")
                return prepared_response(False, "NOT_FOUND", "Suppliers not found")

            Log.info(
                f"{log_tag} supplier(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": suppliers_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving suppliers: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the suppliers. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving suppliers: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )

# END OF WARRANT

# BEGINNING OF TAG
@blp_tag.route("/tag", methods=["POST", "GET", "PATCH", "DELETE"])
class TagResource(MethodView):

    # ---------- CREATE (role-aware) ----------
    @token_required
    @crud_write_limiter("tag")
    @blp_tag.arguments(TagSchema, location="form")
    @blp_tag.response(201, TagSchema)
    @blp_tag.doc(
        summary="Create a new tag",
        description="""
            Create a new tag for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a tag for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": TagSchema,
                    "example": {
                        "name": "Electronics",
                        "status": "Active",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new tag."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
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

        log_tag = (
            f"[admin_setup_resource.py][TagResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        Log.info(f"{log_tag} checking if tag already exists")

        # Hash-based existence check
        try:
            exists = Tag.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating tag uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} tag already exists")
            return prepared_response(False, "CONFLICT", "Tag already exists")

        # Create a new Tag instance
        item = Tag(**item_data)

        try:
            Log.info(f"{log_tag} committing tag: {item_data.get('name')}")
            start_time = time.time()
            tag_id = item.save()
            duration = time.time() - start_time
            Log.info(
                f"{log_tag} tag created with id={tag_id} "
                f"in {duration:.2f} seconds"
            )

            if tag_id is not None:
                return prepared_response(
                    True,
                    "OK",
                    "Tag created successfully.",
                )
            else:
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create tag.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the tag.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- GET SINGLE (role-aware) ----------
    @token_required
    @crud_read_limiter("tag")
    @blp_tag.arguments(TagIdQuerySchema, location="query")
    @blp_tag.response(200, TagSchema)
    @blp_tag.doc(
        summary="Retrieve tag by tag_id (role-aware)",
        description="""
            Retrieve a tag by `tag_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, tag_data):
        tag_id = tag_data.get("tag_id")
        query_business_id = tag_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[admin_setup_resource.py][TagResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[tag_id:{tag_id}]"
        )

        if not tag_id:
            Log.info(f"{log_tag} tag_id not provided")
            return prepared_response(False, "BAD_REQUEST", "tag_id must be provided.")

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting tag. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting tag in own business")

            start_time = time.time()
            tag = Tag.get_by_id(tag_id, target_business_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} retrieving tag completed in {duration:.2f} seconds")

            if not tag:
                Log.info(f"{log_tag} tag not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Tag not found.",
                )

            Log.info(f"{log_tag} tag found")
            return prepared_response(
                True,
                "OK",
                "Tag retrieved successfully.",
                data=tag,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the tag.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- PATCH (PARTIAL UPDATE, role-aware) ----------
    @token_required
    @crud_write_limiter("tag")
    @blp_tag.arguments(TagUpdateSchema, location="form")
    @blp_tag.response(200, TagUpdateSchema)
    @blp_tag.doc(
        summary="Partially update an existing tag (role-aware)",
        description="""
            Partially update an existing tag by providing `tag_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": TagUpdateSchema,
                    "example": {
                        "tag_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Electronics",
                        "status": "Inactive",
                        "business_id": "optional for system_owner/super_admin",
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing tag."""
        tag_id = item_data.get("tag_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner/super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = (
            f"[admin_setup_resource.py][TagResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[tag_id:{tag_id}]"
        )

        if not tag_id:
            Log.info(f"{log_tag} tag_id not provided")
            return prepared_response(False, "BAD_REQUEST", "tag_id must be provided.")

        # Check existing tag within target business scope
        try:
            tag = Tag.get_by_id(tag_id, target_business_id)
            Log.info(f"{log_tag} check_tag")
        except Exception as e:
            Log.info(f"{log_tag} error checking tag existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the tag.",
                errors=str(e),
            )

        if not tag:
            Log.info(f"{log_tag} tag not found")
            return prepared_response(False, "NOT_FOUND", "Tag not found")

        try:
            Log.info(f"{log_tag} updating tag (PATCH)")
            start_time = time.time()

            # Remove tag_id before updating
            item_data.pop("tag_id", None)

            update_ok = Tag.update(tag_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating tag completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Tag updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update tag.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the tag.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while updating tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------- DELETE (role-aware) ----------
    @token_required
    @crud_delete_limiter("tag")
    @blp_tag.arguments(TagIdQuerySchema, location="query")
    @blp_tag.response(200)
    @blp_tag.doc(
        summary="Delete a tag by tag_id (role-aware)",
        description="""
            Delete a tag using `tag_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, tag_data):
        tag_id = tag_data.get("tag_id")
        query_business_id = tag_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # For admin roles, allow targeting another business via query param
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][TagResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][tag_id:{tag_id}]"
        )

        if not tag_id:
            Log.info(f"{log_tag} tag_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "tag_id must be provided.")

        # Retrieve the tag
        try:
            tag = Tag.get_by_id(tag_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the tag.",
                errors=str(e),
            )

        if not tag:
            Log.info(f"{log_tag} tag not found")
            return prepared_response(False, "NOT_FOUND", "Tag not found.")

        # Attempt to delete the tag
        try:
            delete_success = Tag.delete(tag_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete tag.")

            Log.info(f"{log_tag} tag deleted successfully")
            return prepared_response(True, "OK", "Tag deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the tag.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while deleting tag: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the tag.",
                errors=str(e),
            )


@blp_tag.route("/tags", methods=["GET"])
class TagsResource(MethodView):
    @token_required
    @crud_read_limiter("tag")
    @blp_tag.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_tag.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_tag.doc(
        summary="Retrieve tags by user_id or business_id",
        description="""
            This endpoint allows you to retrieve tag details either by the user's `user_id` or the `business_id`. 
            You can pass one or both parameters in the query string to filter the results.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, tag_data):
        # Values coming from the query (for logging)
        user_id = tag_data.get("user_id")
        page = tag_data.get("page")
        per_page = tag_data.get("per_page")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        # Override with authenticated user context (same idea as /taxes, /brands, /variants)
        tag_data["user_id"] = user_info.get("user_id")
        auth_business_id = str(user_info.get("business_id"))
        tag_data["business_id"] = auth_business_id

        log_tag = (
            f"[admin_setup_resource.py][TagsResource][get]"
            f"[{client_ip}][{auth_business_id}]"
        )

        try:
            tags_result = None

            # Admin-style filtering by user__id (if provided in query)
            if tag_data.get("user__id") is not None:
                Log.info(f"{log_tag} Inside user__id")
                tags_result = Tag.get_by_user__id_and_business_id(
                    user__id=tag_data.get("user__id"),
                    business_id=auth_business_id,
                    page=page,
                    per_page=per_page,
                )
            # Otherwise, use business_id (default = authenticated business_id)
            elif tag_data.get("business_id") is not None:
                Log.info(f"{log_tag} Inside business_id")
                tags_result = Tag.get_by_business_id(
                    business_id=tag_data.get("business_id"),
                    page=page,
                    per_page=per_page,
                )

            if not tags_result or not tags_result.get("tags"):
                Log.info(f"{log_tag} Tags not found")
                return prepared_response(False, "NOT_FOUND", "Tags not found")

            Log.info(
                f"[admin_setup_resource.py][TagsResource][get][{client_ip}]"
                f"[user_id: {user_id}, business_id: {auth_business_id}] tag(s) found"
            )

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": tags_result
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving tags: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the tags. {str(e)}"
            )
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving tags: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )

# END OF TAG

# BEGINNIG OF GIFT CARD
@blp_gift_card.route("/giftcard", methods=["POST", "GET", "PATCH", "DELETE"])
class GiftCardResource(MethodView):

    # ------------------------- CREATE GIFTCARD (POST) ------------------------- #
    @token_required
    @crud_write_limiter("giftcard")
    @blp_gift_card.arguments(GiftCardSchema, location="form")
    @blp_gift_card.response(201, GiftCardSchema)
    @blp_gift_card.doc(
        summary="Create a new gift card",
        description="""
            Create a new gift card for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a gift card for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new gift card."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "admin_setup_resource.py",
            "GiftCardResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the gift card already exists based on business_id and name
        try:
            Log.info(f"{log_tag} checking if gift card already exists")
            exists = GiftCard.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating gift card uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} gift card already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Gift card with the same name already exists.",
            )
            
        # ----------------- FK VALIDATION: customer, supplier, products ----------------- #
        try:
            Log.info(f"{log_tag} validating foreign keys for sale")

            # Validate customer_id, if present
            customer_id = item_data.get("customer_id")
            if customer_id:
                customer = Customer.get_by_id(customer_id, target_business_id)
                if not customer:
                    Log.info(f"{log_tag} invalid customer_id={customer_id} for target_business_id={target_business_id}")
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Invalid customer_id: customer does not exist for the specified business.",
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

        # Create a new gift card instance
        gift_card = GiftCard(**item_data)

        # Try saving the gift card to the database
        try:
            Log.info(f"{log_tag} committing gift card: {item_data.get('name')}")
            start_time = time.time()

            gift_card_id = gift_card.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} gift card created with id={gift_card_id} "
                f"in {duration:.2f} seconds"
            )

            if gift_card_id:
                return prepared_response(
                    True,
                    "OK",
                    "Gift card created successfully.",
                )

            Log.info(f"{log_tag} save returned None")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create gift card.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the gift card.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE GIFTCARD (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("giftcard")
    @blp_gift_card.arguments(GiftCardIdQuerySchema, location="query")
    @blp_gift_card.response(200, GiftCardSchema)
    @blp_gift_card.doc(
        summary="Retrieve gift card by gift_card_id (role-aware)",
        description="""
            Retrieve a gift card by `gift_card_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, gift_card_data):
        gift_card_id = gift_card_data.get("gift_card_id")
        query_business_id = gift_card_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag (target_business will be refined after role-based resolution)
        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "GiftCardResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "GiftCardResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[gift_card_id:{gift_card_id}] "
                    f"super_admin/system_owner requesting gift card. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "GiftCardResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[gift_card_id:{gift_card_id}] "
                    f"non-admin requesting gift card in own business"
                )

            start_time = time.time()
            gift_card = GiftCard.get_by_id(gift_card_id, target_business_id)
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[gift_card_id:{gift_card_id}] "
                f"retrieving gift card completed in {duration:.2f} seconds"
            )

            if not gift_card:
                Log.info(f"{log_tag}[gift_card_id:{gift_card_id}] gift card not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Gift card not found.",
                )

            Log.info(f"{log_tag}[gift_card_id:{gift_card_id}] gift card found")
            return prepared_response(
                True,
                "OK",
                "Gift card retrieved successfully.",
                data=gift_card,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[gift_card_id:{gift_card_id}] PyMongoError while retrieving gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the gift card.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag}[gift_card_id:{gift_card_id}] unexpected error while retrieving gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE GIFTCARD (role-aware PUT) ---------------------- #
    @token_required
    @crud_write_limiter("giftcard")
    @blp_gift_card.arguments(GiftCardUpdateSchema, location="form")
    @blp_gift_card.response(200, GiftCardSchema)
    @blp_gift_card.doc(
        summary="Update an existing gift card (role-aware)",
        description="""
            Update an existing gift card by providing `gift_card_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing gift card."""
        gift_card_id = item_data.get("gift_card_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "admin_setup_resource.py",
            "GiftCardResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )
        
        # Check if the gift card exists in target business scope
        try:
            gift_card = GiftCard.get_by_id(gift_card_id, target_business_id)
            Log.info(f"{log_tag} check_gift_card")
        except Exception as e:
            Log.info(f"{log_tag} error checking gift card existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the gift card.",
                errors=str(e),
            )

        if not gift_card:
            Log.info(f"{log_tag} gift card not found")
            return prepared_response(False, "NOT_FOUND", "Gift card not found")

        # Attempt to update the gift card data
        try:
            Log.info(f"{log_tag} updating gift card (PUT)")
            start_time = time.time()

            # Don't try to overwrite id
            item_data.pop("gift_card_id", None)

            update_ok = GiftCard.update(gift_card_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} gift card updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Gift card updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update gift card.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the gift card.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE GIFTCARD (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("giftcard")
    @blp_gift_card.arguments(GiftCardIdQuerySchema, location="query")
    @blp_gift_card.response(200)
    @blp_gift_card.doc(
        summary="Delete a gift card by gift_card_id (role-aware)",
        description="""
            Delete a gift card using `gift_card_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, gift_card_data):
        gift_card_id = gift_card_data.get("gift_card_id")
        query_business_id = gift_card_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Admins may delete from any business using ?business_id=
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "GiftCardResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not gift_card_id:
            Log.info(f"{log_tag} gift_card_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "gift_card_id must be provided.")

        # Retrieve the gift card
        try:
            gift_card = GiftCard.get_by_id(gift_card_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the gift card.",
                errors=str(e),
            )

        if not gift_card:
            Log.info(f"{log_tag} gift card not found")
            return prepared_response(False, "NOT_FOUND", "Gift card not found.")

        # Attempt to delete gift card
        try:
            delete_success = GiftCard.delete(gift_card_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete gift card.")

            Log.info(f"{log_tag} gift card deleted successfully")
            return prepared_response(True, "OK", "Gift card deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the gift card.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting gift card: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_gift_card.route("/giftcards", methods=["GET"])
class GiftCardListResource(MethodView):
    @token_required
    @crud_read_limiter("giftcard")
    @blp_gift_card.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_gift_card.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_gift_card.doc(
        summary="Retrieve gift cards based on role and permissions",
        description="""
            Retrieve gift card details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - if no business_id is provided, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Gift card(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "giftcards": [
                                    {
                                        "_id": "60a6b938d4d8c24fa0804d62",
                                        "business_id": "abcd1234",
                                        "name": "Holiday Gift Card",
                                        "customer_id": "customer123",
                                        "issue_date": "2022-12-01",
                                        "expiry_date": "2023-12-01",
                                        "amount": 100.0,
                                        "reference": "ABC1234567890123",
                                        "status": "Active",
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 10,
                            },
                        }
                    }
                },
            },
            400: {
                "description": "Bad request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Bad request",
                        }
                    }
                },
            },
            404: {
                "description": "Gift cards not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Gift cards not found",
                        }
                    }
                },
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred while retrieving the gift cards.",
                            "error": "Detailed error message here",
                        }
                    }
                },
            },
        },
    )
    def get(self, gift_card_data):
        page = gift_card_data.get("page")
        per_page = gift_card_data.get("per_page")
        query_business_id = gift_card_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "GiftCardListResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        try:
            # Decide which business to use based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner: "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin: gift cards in own business")

            start_time = time.time()

            # Assumes GiftCard.get_by_business_id() behaves like Customer/Sale get_by_business_id
            giftcards_result = GiftCard.get_by_business_id(
                business_id=target_business_id,
                page=page,
                per_page=per_page,
            )

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} retrieving gift cards completed in {duration:.2f} seconds"
            )

            # If no gift cards found
            if not giftcards_result or not giftcards_result.get("giftcards"):
                Log.info(f"{log_tag} Gift cards not found")
                return prepared_response(False, "NOT_FOUND", "Gift cards not found")

            Log.info(
                f"{log_tag} gift card(s) found for "
                f"target_business_id={target_business_id}"
            )

            return prepared_response(
                True,
                "OK",
                "Gift cards retrieved successfully.",
                data=giftcards_result,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving gift cards: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the gift cards. {str(e)}",
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving gift cards: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}",
            )
# END OF GIFT CARD

# BEGINNING OF OUTLET
@blp_outlet.route("/outlet", methods=["POST", "GET", "PATCH", "DELETE"])
class OutletResource(MethodView):

    # ------------------------- CREATE OUTLET (POST) ------------------------- #
    @token_required
    @crud_write_limiter("outlet")
    @blp_outlet.arguments(OutletSchema, location="json")
    @blp_outlet.response(201, OutletSchema)
    @blp_outlet.doc(
        summary="Create a new outlet",
        description="""
            Create a new outlet for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create an outlet for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": OutletSchema,
                    "example": {
                        "name": "Main Branch",
                        "time_zone": "Europe/London",
                        "location": [
                            {
                                "address": "123 Main Street",
                                "longitude": "45.123",
                                "latitude": "-93.123"
                            }
                        ],
                        "registers": [
                            {
                                "name": "Front Till",
                                "status": "Active"
                            }
                        ]
                    }
                }
            }
        },
        responses={
            201: {
                "description": "Outlet created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Outlet created successfully."
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            409: {
                "description": "Outlet already exists",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 409,
                            "message": "Outlet already exists"
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
                            "message": "An unexpected error occurred while creating the outlet.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new outlet."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "admin_setup_resource.py",
            "OutletResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )
        
        # ---- PLAN ENFORCER (scoped to target business) ----
        enforcer = QuotaEnforcer(target_business_id)

        # Check if the outlet already exists based on business_id and name (hashed)
        try:
            Log.info(f"{log_tag} checking if outlet already exists")
            exists = Outlet.check_multiple_item_exists(target_business_id, {"name": item_data.get("name")})
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating outlet uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} outlet already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Outlet already exists",
            )
            
        # ✅ 2) RESERVE QUOTA ONLY WHEN WE ARE ABOUT TO CREATE
        try:
            enforcer.reserve(
                counter_name="outlets",
                limit_key="max_outlets",
                qty=1,
                period="billing",   # monthly plans => month bucket, yearly => year bucket
                reason="outlet:create",
            )
        except PlanLimitError as e:
            Log.info(f"{log_tag} plan limit reached: {e.meta}")
            return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)

        # Create a new outlet instance
        outlet = Outlet(**item_data)

        # Try saving the outlet to MongoDB
        try:
            Log.info(f"{log_tag} committing outlet: {item_data.get('name')}")
            start_time = time.time()

            outlet_id = outlet.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag} outlet created with id={outlet_id} "
                f"in {duration:.2f} seconds"
            )
            
            
            # Release the reserved quota if save failed
            if not outlet_id:
                Log.info(f"{log_tag} Failed to create outlet")
                enforcer.release(counter_name="outlets", qty=1, period="billing")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to create outlet.",
                )


            if outlet_id:
                return prepared_response(
                    True,
                    "OK",
                    "Outlet created successfully.",
                )

        except DuplicateKeyError as e:
            # real race-condition duplicate caught by Mongo's unique index
            enforcer.release(counter_name="outlets", qty=1, period="billing")
            Log.info(f"{log_tag} DuplicateKeyError on outlet insert: {e}")
            return prepared_response(False, "CONFLICT", "Outlet already exists")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the outlet.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE OUTLET (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("outlet")
    @blp_outlet.arguments(OutletIdQuerySchema, location="query")
    @blp_outlet.response(200, OutletSchema)
    @blp_outlet.doc(
        summary="Retrieve outlet by outlet_id (role-aware)",
        description="""
            Retrieve an outlet by `outlet_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, outlet_data):
        """Handle the GET request to retrieve an outlet by outlet_id."""
        outlet_id = outlet_data.get("outlet_id")
        query_business_id = outlet_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Provisional log_tag
        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "OutletResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not outlet_id:
            Log.info(f"{log_tag}[outlet_id:None] outlet_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "outlet_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "OutletResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[outlet_id:{outlet_id}] "
                    f"super_admin/system_owner requesting outlet. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "OutletResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[outlet_id:{outlet_id}] "
                    f"non-admin requesting outlet in own business"
                )

            start_time = time.time()
            outlet = Outlet.get_by_id(outlet_id, target_business_id)
            duration = time.time() - start_time

            Log.info(
                f"{log_tag}[outlet_id:{outlet_id}] "
                f"retrieving outlet completed in {duration:.2f} seconds"
            )

            if not outlet:
                Log.info(f"{log_tag}[outlet_id:{outlet_id}] outlet not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Outlet not found.",
                )

            Log.info(f"{log_tag}[outlet_id:{outlet_id}] outlet found")
            return prepared_response(
                True,
                "OK",
                "Outlet retrieved successfully.",
                data=outlet,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[outlet_id:{outlet_id}] PyMongoError while retrieving outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the outlet.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag}[outlet_id:{outlet_id}] unexpected error while retrieving outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE OUTLET (role-aware PATCH) ---------------------- #
    @token_required
    @crud_write_limiter("outlet")
    @blp_outlet.arguments(OutletUpdateSchema, location="json")
    @blp_outlet.response(200, OutletUpdateSchema)
    @blp_outlet.doc(
        summary="Partially update an existing outlet (role-aware)",
        description="""
            Partially update an existing outlet by providing `outlet_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": OutletUpdateSchema,
                    "example": {
                        "outlet_id": "60a6b938d4d8c24fa0804d62",
                        "name": "Updated Branch",
                        "time_zone": "Europe/London",
                        "location": [
                            {
                                "address": "456 New Street",
                                "longitude": "12.3456",
                                "latitude": "65.4321"
                            }
                        ],
                        "registers": [
                            {"name": "Register 1", "status": "Active"}
                        ],
                        "status": "Active"
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing outlet."""
        outlet_id = item_data.get("outlet_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "admin_setup_resource.py",
            "OutletResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not outlet_id:
            Log.info(f"{log_tag} outlet_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "outlet_id must be provided.",
            )

        # Check existing outlet in target business scope
        try:
            outlet = Outlet.get_by_id(outlet_id, target_business_id)
            Log.info(f"{log_tag} check_outlet")
        except Exception as e:
            Log.info(f"{log_tag} error checking outlet existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the outlet.",
                errors=str(e),
            )

        if not outlet:
            Log.info(f"{log_tag} outlet not found")
            return prepared_response(False, "NOT_FOUND", "Outlet not found")

        # Attempt to update the outlet data
        try:
            Log.info(f"{log_tag} updating outlet (PATCH)")
            start_time = time.time()

            # Don't try to overwrite id
            item_data.pop("outlet_id", None)

            update_ok = Outlet.update(outlet_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} outlet updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Outlet updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update outlet.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the outlet.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE OUTLET (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("outlet")
    @blp_outlet.arguments(OutletIdQuerySchema, location="query")
    @blp_outlet.response(200)
    @blp_outlet.doc(
        summary="Delete an outlet by outlet_id (role-aware)",
        description="""
            Delete an outlet using `outlet_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Outlet deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Outlet deleted successfully"
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "outlet_id must be provided."
                        }
                    }
                }
            },
            404: {
                "description": "Outlet not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Outlet not found"
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
                            "message": "An unexpected error occurred while deleting the outlet.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def delete(self, outlet_data):
        outlet_id = outlet_data.get("outlet_id")
        query_business_id = outlet_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Admins may delete from any business using ?business_id=
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "OutletResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not outlet_id:
            Log.info(f"{log_tag} outlet_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "outlet_id must be provided.")

        # Retrieve the outlet
        try:
            outlet = Outlet.get_by_id(outlet_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the outlet.",
                errors=str(e),
            )

        if not outlet:
            Log.info(f"{log_tag} outlet not found")
            return prepared_response(False, "NOT_FOUND", "Outlet not found.")

        # Attempt to delete outlet
        try:
            delete_success = Outlet.delete(outlet_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete outlet.")

            Log.info(f"{log_tag} outlet deleted successfully")
            return prepared_response(True, "OK", "Outlet deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the outlet.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting outlet: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

# GET Outlet (Retrieve outlets by business_id)
@blp_outlet.route("/outlets", methods=["GET", "POST"])
class OutletResource(MethodView):

    # =======================================
    # GET /outlets  (Role-Aware Retrieval)
    # =======================================
    @token_required
    @crud_read_limiter("outlet")
    @blp_outlet.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_outlet.response(200, BusinessIdAndUserIdQuerySchema(many=True))
    def get(self, params):
        page = params.get("page")
        per_page = params.get("per_page")
        query_business_id = params.get("business_id")

        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_user__id = str(user.get("_id"))
        auth_business_id = str(user.get("business_id"))
        account_type = decrypt_data(user.get("account_type")) if user.get("account_type") else None

        # ====== Create initial log tag ======
        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "OutletResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        try:
            # ==============================
            # ROLE-AWARE BUSINESS SELECTION
            # ==============================
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(f"{log_tag} super_admin/system_owner targeting business_id={target_business_id}")
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/business-owner restricted to own business")

            # ==============================
            # FETCH OUTLETS
            # ==============================
            start = time.time()
            result = Outlet.get_by_business_id(
                business_id=target_business_id,
                page=page,
                per_page=per_page,
            )
            duration = time.time() - start
            Log.info(f"{log_tag} retrieval completed in {duration:.2f}s")

            if not result or not result.get("outlets"):
                Log.info(f"{log_tag} no outlets found")
                return prepared_response(False, "NOT_FOUND", "Outlets not found")

            Log.info(f"{log_tag} outlets found successfully")
            return prepared_response(
                True,
                "OK",
                "Outlets retrieved successfully.",
                data=result,
            )
           

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Database error while retrieving outlets.",
                errors=str(e)
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Unexpected server error.",
                errors=str(e)
            )
# BEGINNING OF OUTLET

# -----------------------BUSINESS LOCATION-----------------------------------------
@blp_business_location.route("/business-location", methods=["POST", "GET", "PATCH", "DELETE"])
class BusinessLocationResource(MethodView):

    # ------------------------- CREATE BUSINESS LOCATION (POST) ------------------------- #
    @token_required
    @crud_write_limiter("businesslocation")
    @blp_business_location.arguments(BusinessLocationSchema, location="form")
    @blp_business_location.response(201, BusinessLocationSchema)
    @blp_business_location.doc(
        summary="Create a new business location",
        description="""
            Create a new business location for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the payload to create a location for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new business location."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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

        name = item_data.get("name")

        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "BusinessLocationResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the business location already exists based on business_id and name
        try:
            Log.info(f"{log_tag} checking if business location already exists")
            exists = BusinessLocation.check_multiple_item_exists(
                target_business_id,
                {"name": name},
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating business location uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} business location already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Business location with the same name already exists.",
            )

        # Create a new business location instance
        item = BusinessLocation(**item_data)

        # Try saving the business location to MongoDB and handle any errors
        try:
            Log.info(f"{log_tag} committing business location: {name}")
            start_time = time.time()

            location_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} business location created with id={location_id} "
                f"in {duration:.2f} seconds"
            )

            if location_id:
                return prepared_response(
                    True,
                    "CREATED",
                    "Business location created successfully.",
                )

            Log.info(f"{log_tag} save returned None")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create business location.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the business location.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE BUSINESS LOCATION (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("businesslocation")
    @blp_business_location.arguments(BusinessLocationQuerySchema, location="query")
    @blp_business_location.response(200, BusinessLocationSchema)
    @blp_business_location.doc(
        summary="Retrieve business location by business_location_id (role-aware)",
        description="""
            Retrieve a business location by `business_location_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, location_data):
        """Handle the GET request to retrieve a business location by business_location_id."""
        business_location_id = location_data.get("business_location_id")
        query_business_id = location_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag (target business will be refined after role-based resolution)
        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "BusinessLocationResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not business_location_id:
            Log.info(f"{log_tag} business_location_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "business_location_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "BusinessLocationResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[business_location_id:{business_location_id}] "
                    f"super_admin/system_owner requesting business location. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "BusinessLocationResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[business_location_id:{business_location_id}] "
                    f"non-admin requesting business location in own business"
                )

            start_time = time.time()
            location = BusinessLocation.get_by_id(
                location_id=business_location_id,
                business_id=target_business_id,
            )
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[business_location_id:{business_location_id}] "
                f"retrieving business location completed in {duration:.2f} seconds"
            )

            if not location:
                Log.info(f"{log_tag}[business_location_id:{business_location_id}] location not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Business Location not found.",
                )

            Log.info(f"{log_tag}[business_location_id:{business_location_id}] location found")
            return prepared_response(
                True,
                "OK",
                "Business location retrieved successfully.",
                data=location,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[business_location_id:{business_location_id}] PyMongoError while retrieving business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the business location.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag}[business_location_id:{business_location_id}] unexpected error while retrieving business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE BUSINESS LOCATION (role-aware PATCH) ---------------------- #
    @token_required
    @crud_write_limiter("businesslocation")
    @blp_business_location.arguments(BusinessLocationUpdateSchema, location="form")
    @blp_business_location.response(200, BusinessLocationUpdateSchema)
    @blp_business_location.doc(
        summary="Update an existing business location (role-aware)",
        description="""
            Update an existing business location by providing `business_location_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the payload to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing business location."""
        business_location_id = item_data.get("business_location_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "admin_setup_resource.py",
            "BusinessLocationResource",
            "put",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not business_location_id:
            Log.info(f"{log_tag} business_location_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "business_location_id must be provided.",
            )

        # Check if the business location exists in target business scope
        try:
            location = BusinessLocation.get_by_id(
                location_id=business_location_id,
                business_id=target_business_id,
            )
            Log.info(f"{log_tag} check_business_location")
        except Exception as e:
            Log.info(f"{log_tag} error checking business location existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the business location.",
                errors=str(e),
            )

        if not location:
            Log.info(f"{log_tag} business location not found")
            return prepared_response(False, "NOT_FOUND", "Business Location not found")

        # Attempt to update the business location data
        try:
            Log.info(f"{log_tag} updating business location (PUT)")
            start_time = time.time()

            # Don't try to overwrite id
            item_data.pop("business_location_id", None)
            item_data.pop("location_id", None)

            update_ok = BusinessLocation.update(business_location_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} business location updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Business Location updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update business location.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the business location.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE BUSINESS LOCATION (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("businesslocation")
    @blp_business_location.arguments(BusinessLocationQuerySchema, location="query")
    @blp_business_location.response(200)
    @blp_business_location.doc(
        summary="Delete a business location by business_location_id (role-aware)",
        description="""
            Delete a business location using `business_location_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, location_data):
        business_location_id = location_data.get("business_location_id")
        query_business_id = location_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Admins may delete from any business using ?business_id=
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "BusinessLocationResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not business_location_id:
            Log.info(f"{log_tag} business_location_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "business_location_id must be provided.")

        try:
            # Ensure the location exists and belongs to this business
            location = BusinessLocation.get_by_id(
                location_id=business_location_id,
                business_id=target_business_id,
            )
        except Exception as e:
            Log.info(f"{log_tag} error fetching business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the business location.",
                errors=str(e),
            )

        if not location:
            Log.info(f"{log_tag} Business Location not found")
            return prepared_response(False, "NOT_FOUND", "Business Location not found.")

        # Attempt to delete business location
        try:
            delete_success = BusinessLocation.delete(
                location_id=business_location_id,
                business_id=target_business_id,
            )

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete business location.")

            Log.info(f"{log_tag} Business Location deleted successfully")
            return prepared_response(True, "OK", "Business Location deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the business location.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting business location: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_business_location.route("/business-locations", methods=["GET"])
class BusinessLocationResource(MethodView):

    @token_required
    @crud_read_limiter("businesslocation")
    @blp_business_location.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_business_location.response(200, BusinessLocationSchema)
    @blp_business_location.doc(
        summary="Retrieve business locations based on role and permissions",
        description="""
            Retrieve business location details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all business locations in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to locations belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
    )
    def get(self, location_data):
        # Pagination
        page = location_data.get("page")
        per_page = location_data.get("per_page")

        # Optional filters
        query_business_id = location_data.get("business_id")
        query_user_id = location_data.get("user_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Provisional log_tag (will update after target_business_id is set)
        log_tag = make_log_tag(
            "admin_setup_resource.py",
            "BusinessLocationResource",
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
                target_business_id = query_business_id or auth_business_id

                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "BusinessLocationResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} system_owner/super_admin request")

                if query_user_id:
                    locations_result = BusinessLocation.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    locations_result = BusinessLocation.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "BusinessLocationResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner request")

                locations_result = BusinessLocation.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # STAFF / NORMAL USERS
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_setup_resource.py",
                    "BusinessLocationResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other request")

                locations_result = BusinessLocation.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # -------------------------
            # NORMALISE RESULT SHAPE
            # -------------------------
            locations_list = []

            if isinstance(locations_result, dict):
                # Try common keys in your patterns (customers, discounts, outlets...)
                if "business_locations" in locations_result:
                    locations_list = locations_result.get("business_locations") or []
                elif "locations" in locations_result:
                    locations_list = locations_result.get("locations") or []
                elif "items" in locations_result:
                    locations_list = locations_result.get("items") or []
                else:
                    # Fallback: single-object dict, treat as one location
                    locations_list = [locations_result]
            elif isinstance(locations_result, list):
                locations_list = locations_result or []
            else:
                locations_list = []

            # -------------------------
            # NOT FOUND
            # -------------------------
            if not locations_list:
                Log.info(f"{log_tag} No business locations found")
                return prepared_response(False, "NOT_FOUND", "Business locations not found")

            Log.info(f"{log_tag} business_locations found (count={len(locations_list)})")

            # If the model returned a dict with metadata (pagination), keep it.
            # If it was a bare list, wrap it in a standard structure.
            if isinstance(locations_result, dict):
                payload = locations_result
            else:
                payload = {
                    "business_locations": locations_list,
                    "total_count": len(locations_list),
                    "total_pages": 1,
                    "current_page": page or 1,
                    "per_page": per_page or len(locations_list),
                }

            # -------------------------
            # SUCCESS RESPONSE
            # -------------------------
            return prepared_response(
                True,
                "OK",
                "Business locations retrieved successfully.",
                data=payload,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving business locations.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
# -----------------------BUSINESS LOCATION-----------------------------------------


# ----------------------- COMPOSITE VARIANT -----------------------------------------
@blp_composite_variant.route("/composit-variant", methods=["POST", "GET", "PATCH", "DELETE"])
class CompositeVariantResource(MethodView):

    # ------------------------- CREATE COMPOSITE VARIANT (POST) ------------------------- #
    @token_required
    @crud_write_limiter("compositvariant")
    @blp_composite_variant.arguments(CompositeVariantSchema, location="form")
    @blp_composite_variant.response(201, CompositeVariantSchema)
    @blp_composite_variant.doc(
        summary="Create a new composite variant",
        description="""
            Create a new composite variant for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a composite variant for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.

            Image upload is optional.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, variant_data):
        """Handle the POST request to create a new composite variant."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = variant_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        variant_data["business_id"] = target_business_id
        variant_data["user__id"] = auth_user__id
        if not variant_data.get("user_id"):
            variant_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "CompositeVariantResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the composite variant already exists based on business_id and values
        try:
            Log.info(f"{log_tag} checking if composite variant already exists")
            # Uses helper that checks hashed values
            exists = CompositeVariant.check_multiple_item_exists(target_business_id, {"values": variant_data.get("values")})
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating composite variant uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} composite variant already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Composite variant already exists",
            )

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]

            try:
                image_path, actual_path = upload_file(image, target_business_id)
                variant_data["image"] = image_path          # Public/relative path
                variant_data["file_path"] = actual_path     # Actual filesystem path
            except ValueError as e:
                Log.info(f"{log_tag} image upload validation error: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        # Create a new composite variant instance
        variant = CompositeVariant(**variant_data)

        # Try saving the composite variant to the database
        try:
            Log.info(f"{log_tag} committing composite variant")
            start_time = time.time()

            variant_id = variant.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} composite variant created with id={variant_id} "
                f"in {duration:.2f} seconds"
            )

            if variant_id:
                return prepared_response(
                    True,
                    "OK",
                    "Composite variant created successfully.",
                )

            # If creating composite variant fails, delete the uploaded image
            if actual_path:
                try:
                    delete_old_image(actual_path)
                except Exception as e:
                    Log.info(f"{log_tag} error deleting uploaded image after failed save: {e}")

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create composite variant.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving composite variant: {e}")
            if actual_path:
                try:
                    delete_old_image(actual_path)
                except Exception as e2:
                    Log.info(f"{log_tag} error deleting uploaded image after PyMongoError: {e2}")

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the composite variant.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving composite variant: {e}")
            if actual_path:
                try:
                    delete_old_image(actual_path)
                except Exception as e2:
                    Log.info(f"{log_tag} error deleting uploaded image after unexpected error: {e2}")

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE COMPOSITE VARIANT (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("compositvariant")
    @blp_composite_variant.arguments(CompositeVariantIdQuerySchema, location="query")
    @blp_composite_variant.response(200, CompositeVariantSchema)
    @blp_composite_variant.doc(
        summary="Retrieve composite variant by variant_id (role-aware)",
        description="""
            Retrieve a composite variant by `variant_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, variant_query):
        variant_id = variant_query.get("composit_variant_id")
        query_business_id = variant_query.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag (target business refined after role resolution)
        log_tag = make_log_tag(
            "admin_product_resource.py",
            "CompositeVariantResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )
        
        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "CompositeVariantResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[variant_id:{variant_id}] "
                    f"super_admin/system_owner requesting composite variant. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_product_resource.py",
                    "CompositeVariantResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[variant_id:{variant_id}] "
                    f"non-admin requesting composite variant in own business"
                )

            start_time = time.time()
            composite_variant = CompositeVariant.get_by_id(variant_id, target_business_id)
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[variant_id:{variant_id}] "
                f"retrieving composite variant completed in {duration:.2f} seconds"
            )

            if not composite_variant:
                Log.info(f"{log_tag}[variant_id:{variant_id}] composite variant not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Composite variant not found.",
                )

            # Hide internal file_path from API response
            composite_variant.pop("file_path", None)

            Log.info(f"{log_tag}[variant_id:{variant_id}] composite variant found")
            return prepared_response(
                True,
                "OK",
                "Composite variant retrieved successfully.",
                data=composite_variant,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[variant_id:{variant_id}] PyMongoError while retrieving composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the composite variant.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag}[variant_id:{variant_id}] unexpected error while retrieving composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- PATCH COMPOSITE VARIANT (role-aware) ---------------------- #
    @token_required
    @crud_write_limiter("compositvariant")
    @blp_composite_variant.arguments(CompositeVariantUpdateSchema, location="form")
    @blp_composite_variant.response(200, CompositeVariantUpdateSchema)
    @blp_composite_variant.doc(
        summary="Partially update an existing composite variant (role-aware)",
        description="""
            Partially update an existing composite variant by providing `variant_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.

            Image upload is optional.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to partially update an existing composite variant."""
        variant_id = item_data.get("composit_variant_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

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
            "CompositeVariantResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                image_path, actual_path = upload_file(image, target_business_id)
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                Log.info(f"{log_tag} image upload validation error: {e}")
                return prepared_response(False, "BAD_REQUEST", str(e))

        # Check existing composite variant in target business scope
        try:
            composite_variant = CompositeVariant.get_by_id(variant_id, target_business_id)
            Log.info(f"{log_tag} check_composite_variant")
        except Exception as e:
            Log.info(f"{log_tag} error checking composite variant existence: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the composite variant.",
                errors=str(e),
            )

        if not composite_variant:
            Log.info(f"{log_tag} composite variant not found")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(False, "NOT_FOUND", "Composite variant not found")

        # Keep old image for removal after successful update
        old_image = composite_variant.get("file_path")

        try:
            Log.info(f"{log_tag} updating composite variant (PATCH)")
            start_time = time.time()

            # Remove variant_id before patching
            item_data.pop("variant_id", None)

            update_ok = CompositeVariant.update(variant_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating composite variant completed in {duration:.2f} seconds")

                # Delete old image if new one was uploaded
                if actual_path and old_image:
                    try:
                        delete_old_image(old_image)
                        Log.info(f"{log_tag} old composite variant image removed successfully")
                    except Exception as e:
                        Log.info(f"{log_tag} error removing old image: {e}")

                return prepared_response(True, "OK", "Composite variant updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                if actual_path:
                    delete_old_image(actual_path)
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update composite variant.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating composite variant: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the composite variant.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating composite variant: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE COMPOSITE VARIANT (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("compositvariant")
    @blp_composite_variant.arguments(CompositeVariantIdQuerySchema, location="query")
    @blp_composite_variant.response(200)
    @blp_composite_variant.doc(
        summary="Delete a composite variant by variant_id (role-aware)",
        description="""
            Delete a composite variant using `variant_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, variant_query):
        
        variant_id = variant_query.get("composit_variant_id")
        query_business_id = variant_query.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Admins may delete from any business using ?business_id=
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_product_resource.py",
            "CompositeVariantResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not variant_id:
            Log.info(f"{log_tag} variant_id must be provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "variant_id must be provided.",
            )

        # Retrieve the composite variant
        try:
            composite_variant = CompositeVariant.get_by_id(variant_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the composite variant.",
                errors=str(e),
            )

        if not composite_variant:
            Log.info(f"{log_tag} composite variant not found")
            return prepared_response(False, "NOT_FOUND", "Composite variant not found.")

        # Extract image path before deletion
        image_path = composite_variant.get("file_path") if composite_variant.get("file_path") else None

        # Attempt to delete composite variant
        try:
            delete_success = CompositeVariant.delete(variant_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete composite variant.")

            # Delete image if exists
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} composite variant image deleted: {image_path}")
                except Exception as e:
                    Log.info(f"{log_tag} error deleting composite variant image: {e}")

            Log.info(f"{log_tag} composite variant deleted successfully")
            return prepared_response(True, "OK", "Composite variant deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the composite variant.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting composite variant: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_composite_variant.route("/composit-variants", methods=["GET"])
class CompositeVariantListResource(MethodView):

    @token_required
    @crud_read_limiter("compositvariant")
    @blp_composite_variant.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_composite_variant.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_composite_variant.doc(
        summary="Retrieve composite variants based on role and permissions",
        description="""
            Retrieve composite variant details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all composite variants in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to composite variants belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Composite variant(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "composite_variants": [
                                    {
                                        "variant_id": "cv-123456",
                                        "values": {"size": "L", "color": "Red"},
                                        "status": "Active",
                                        "business_id": "abcd1234",
                                        "user__id": "60a6b938d4d8c24fa0804d62",
                                        "thumbnail": "uploads/thumbnails/...",
                                        "barcode_symbology": "EAN-13",
                                        "code": "SKU-RED-L",
                                        "quantity": "10",
                                        "quantity_alert": "2",
                                        "tax_type": "inclusive",
                                        "tax": "12.5",
                                        "discount_type": "percentage",
                                        "discount_value": "5",
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
                "description": "Composite variants not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Composite variants not found"
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
                            "message": "An unexpected error occurred while retrieving the composite variants.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, query_data):
        page = query_data.get("page")
        per_page = query_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = query_data.get("business_id")
        query_user_id = query_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Provisional log_tag before we resolve target_business_id
        log_tag = make_log_tag(
            "admin_composite_variant_resource.py",
            "CompositeVariantListResource",
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
                    "admin_composite_variant_resource.py",
                    "CompositeVariantListResource",
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
                    variants_result = CompositeVariant.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All composite variants for that business
                    variants_result = CompositeVariant.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all composite variants in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_composite_variant_resource.py",
                    "CompositeVariantListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: composite variants in own business")

                variants_result = CompositeVariant.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own composite variants in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_composite_variant_resource.py",
                    "CompositeVariantListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own composite variants only")

                variants_result = CompositeVariant.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no composite variants found
            if not variants_result or not variants_result.get("composite_variants"):
                Log.info(f"{log_tag} Composite variants not found")
                return prepared_response(False, "NOT_FOUND", "Composite variants not found")

            Log.info(
                f"{log_tag} composite variant(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": variants_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving composite variants: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the composite variants. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving composite variants: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )


















