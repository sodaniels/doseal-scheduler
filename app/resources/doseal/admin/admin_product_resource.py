# resources/product_resource.py
import os
import time
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from bson import ObjectId
from datetime import datetime, timedelta
from pymongo.errors import PyMongoError, DuplicateKeyError
from ....utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError

from .admin_business_resource import token_required
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
)

from ....utils.generators import generate_sku
from ....utils.helpers import (
    make_log_tag, resolve_target_business_id
)
from ....utils.plan.enforce_component import enforce_component
from ....utils.plan.release_component import release_component

from ....models.product_model import Product
from ....schemas.admin.product_schema import (
    ProductSchema,
    ProductUpdateSchema,
    ProductIdQuerySchema,
    BusinessIdAndUserIdQuerySchema,
    POSProductsQuerySchema
)
from ....utils.json_response import prepared_response
from ....constants.service_code import (
    HTTP_STATUS_CODES,
    SYSTEM_USERS
)
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.logger import Log
from ....utils.file_upload import upload_file, delete_old_image


blp_product = Blueprint("Products",__name__, description="Product management operations")


@blp_product.route("/product")
class ProductResource(MethodView):
    """Single product CRUD operations."""

    # ---------- CREATE (role-aware business selection) ----------
    @token_required
    @crud_write_limiter(entity_name="product")
    @blp_product.arguments(ProductSchema, location="form")
    @blp_product.response(HTTP_STATUS_CODES["CREATED"], ProductSchema)
    @blp_product.doc(
        summary="Create a new product",
        description="""
            Create a new product for a business. Supports multiple images.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a product for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new product."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        account_type_enc = user_info.get("account_type")
        
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        manufactured_date = str(item_data.get("manufactured_date"))
        expiry_on = str(item_data.get("expiry_on"))

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user__id"] = auth_user__id
        item_data["user_id"] = user_id
        item_data["admin_id"] = auth_user__id
        
        item_data["manufactured_date"] = manufactured_date
        item_data["expiry_on"] = expiry_on

        log_tag = make_log_tag(
            "product_resource.py",
            "ProductResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        # Check if the product already exists for this business
        try:
            Log.info(f"{log_tag} Checking if product already exists")
            exists = Product.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")},
            )
        except Exception as e:
            Log.error(f"{log_tag} Error while checking duplicate product: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An error occurred while validating product uniqueness.",
                errors=[str(e)]
            )

        if exists:
            Log.info(f"{log_tag} Product already exists")
            return prepared_response(
                status=False,
                status_code="CONFLICT",
                message="Product already exists"
            )
            
        # ---- PLAN ENFORCER (scoped to target business) ----
        enforcer = QuotaEnforcer(target_business_id)
            
            
        # ensure product units exist before allowing commit

        # Handle multiple image uploads
        file_paths = []   # actual filesystem paths
        image_paths = []  # stored URLs / paths
        if "images" in request.files:
            images = request.files.getlist("images")
            for image in images:
                try:
                    image_path, actual_path = upload_file(image, target_business_id)
                    image_paths.append(image_path)
                    file_paths.append(actual_path)
                except ValueError as e:
                    Log.error(f"{log_tag} Image upload failed: {e}")
                    # Cleanup any uploaded files
                    for fp in file_paths:
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=str(e)
                    )

        Log.info(f"{log_tag} Uploaded {len(image_paths)} images")
        item_data["images"] = image_paths
        item_data["file_paths"] = file_paths
        
        # Check if the product sku exists
        if item_data.get("sku"):
            try:
                Log.info(f"{log_tag} Check if the product sku exists.")
                sku_exists = Product.check_multiple_item_exists(
                    target_business_id,
                    {"sku": item_data.get("sku")},
                )
                if sku_exists:
                    Log.info(f"{log_tag} Product with this SKU already exists")
                    return prepared_response(
                        status=False,
                        status_code="CONFLICT",
                        message="Product with this SKU already exists"
                    )
            except Exception as e:
                Log.error(f"{log_tag} Error while checking if the product sku exists. {e}")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="An error checking if the product sku exists.",
                    errors=[str(e)]
                )
                
         # --------- 1) Decide final plain SKU (auto-generate if missing) ---------
        if not item_data.get("sku"):
            plain_sku = generate_sku(
                business_id=target_business_id,
                prefix="P",
                width=10,
                sequence_name="product",
            )
            item_data["sku"] = plain_sku
            Log.info(f"{log_tag} Auto-generated SKU: {plain_sku}")
        

        # Create a new product instance
        item = Product(**item_data)
        
        # ✅ 2) RESERVE QUOTA ONLY WHEN WE ARE ABOUT TO CREATE
        try:
            enforcer.reserve(
                counter_name="products",
                limit_key="max_products",
                qty=1,
                period="billing",   # monthly plans => month bucket, yearly => year bucket
                reason="products:create",
            )
        except PlanLimitError as e:
            Log.info(f"{log_tag} plan limit reached: {e.meta}")
            return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)

        try:
            Log.info(f"{log_tag} Saving product: {item_data.get('name')}")
            start_time = time.time()

            product_id = item.save()

            duration = time.time() - start_time
            Log.info(f"{log_tag} Product created with id={product_id} in {duration:.2f}s")

            if product_id is not None:
                return prepared_response(
                    status=True,
                    status_code="CREATED",
                    message="Product created successfully.",
                    data={"product_id": str(product_id)}
                )

            Log.error(f"{log_tag} product_id is None after save")
            # Cleanup uploaded files when save fails
            for fp in file_paths:
                try:
                    os.remove(fp)
                except Exception:
                    pass

            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to create product."
            )
        
        except DuplicateKeyError as e:
            # real race-condition duplicate caught by Mongo's unique index
            enforcer.release(counter_name="products", qty=1, period="billing")
            Log.info(f"{log_tag} DuplicateKeyError on products insert: {e}")
            return prepared_response(False, "CONFLICT", "Product already exists")

        except PyMongoError as e:
            Log.error(f"{log_tag} PyMongoError while saving product: {e}")
            for fp in file_paths:
                try:
                    os.remove(fp)
                except Exception:
                    pass
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while saving the product.",
                errors=[str(e)]
            )

        except Exception as e:
            Log.error(f"{log_tag} Unexpected error while saving product: {e}")
            for fp in file_paths:
                try:
                    os.remove(fp)
                except Exception:
                    pass
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )

    # ---------- GET (role-aware business selection) ----------
    @token_required
    @crud_read_limiter(entity_name="product")
    @blp_product.arguments(ProductIdQuerySchema, location="query")
    @blp_product.response(HTTP_STATUS_CODES["OK"], ProductSchema)
    @blp_product.doc(
        summary="Retrieve product by product_id (role-aware)",
        description="""
            Retrieve a product by `product_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, product_data):
        """Handle the GET request to retrieve a product by product_id."""
        product_id = product_data.get("product_id")
        query_business_id = product_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        log_tag = make_log_tag(
            "product_resource.py",
            "ProductResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not product_id:
            Log.error(f"{log_tag} product_id must be provided")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="product_id must be provided."
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(f"{log_tag} Admin requesting product, target_business_id={target_business_id}")
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} Non-admin requesting product in own business")

            product = Product.get_by_id(product_id, target_business_id)

            if not product:
                Log.error(f"{log_tag} Product not found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Product not found."
                )

            Log.info(f"{log_tag} Product retrieved successfully")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Product retrieved successfully.",
                data={"product": product}
            )

        except Exception as e:
            Log.error(f"{log_tag} Error retrieving product: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )

    # ---------- PATCH (role-aware business selection) ----------
    @token_required
    @crud_write_limiter(entity_name="product")
    @blp_product.arguments(ProductUpdateSchema, location="form")
    @blp_product.response(HTTP_STATUS_CODES["OK"], ProductUpdateSchema)
    @blp_product.doc(
        summary="Partially update an existing product",
        description="""
            Partially update an existing product by providing `product_id` and new details.
            Supports optional image replacement.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing product."""
        product_id = item_data.get("product_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "product_resource.py",
            "ProductResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not product_id:
            Log.error(f"{log_tag} product_id must be provided")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="product_id must be provided."
            )

        # Check if the product exists
        try:
            Log.info(f"{log_tag} Checking if product exists")
            product = Product.get_by_id(product_id, target_business_id)
        except Exception as e:
            Log.error(f"{log_tag} Error checking product existence: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while checking the product.",
                errors=[str(e)]
            )

        if not product:
            Log.error(f"{log_tag} Product not found")
            return prepared_response(
                status=False,
                status_code="NOT_FOUND",
                message="Product not found"
            )

        # Handle multiple image uploads (replaces all images)
        new_file_paths = []
        new_image_paths = []
        old_file_paths = product.get("file_paths", []) or []
        
        if "images" in request.files:
            images = request.files.getlist("images")
            for image in images:
                try:
                    image_path, actual_path = upload_file(image, target_business_id)
                    new_image_paths.append(image_path)
                    new_file_paths.append(actual_path)
                except ValueError as e:
                    Log.error(f"{log_tag} Image upload failed: {e}")
                    # Cleanup any uploaded files
                    for fp in new_file_paths:
                        try:
                            os.remove(fp)
                        except Exception:
                            pass
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=str(e)
                    )
            
            item_data["images"] = new_image_paths
            item_data["file_paths"] = new_file_paths

        # Attempt to update the product data
        try:
            Log.info(f"{log_tag} Updating product")
            start_time = time.time()

            # Don't try to overwrite _id
            item_data.pop("product_id", None)
            item_data.pop("business_id", None)  # Don't change business_id on update

            update_ok = Product.update(product_id, **item_data)

            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} Product updated in {duration:.2f}s")

                # Delete old images after successful update
                if new_file_paths:  # Only if we uploaded new images
                    for old_path in old_file_paths:
                        try:
                            delete_old_image(old_path)
                            Log.info(f"{log_tag} Old image {old_path} removed successfully")
                        except Exception as e:
                            Log.error(f"{log_tag} Error removing old image {old_path}: {e}")

                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="Product updated successfully."
                )

            Log.error(f"{log_tag} Failed to update product")
            # Cleanup new files if update failed
            for fp in new_file_paths:
                try:
                    os.remove(fp)
                except Exception:
                    pass

            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to update product."
            )

        except Exception as e:
            Log.error(f"{log_tag} Error updating product: {e}")
            for fp in new_file_paths:
                try:
                    os.remove(fp)
                except Exception:
                    pass
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )

    # ---------- DELETE (role-aware business selection) ----------
    @token_required
    @crud_delete_limiter(entity_name="product")
    @blp_product.arguments(ProductIdQuerySchema, location="query")
    @blp_product.response(HTTP_STATUS_CODES["OK"])
    @blp_product.doc(
        summary="Delete a product by product_id",
        description="""
            Delete a product using `product_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion defaults to the authenticated user's business_id.

            Associated images (if any) are deleted after successful product deletion.
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, product_data):
        """Handle the DELETE request to remove a product by product_id."""
        product_id = product_data.get("product_id")
        query_business_id = product_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Role-aware business selection
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "product_resource.py",
            "ProductResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not product_id:
            Log.error(f"{log_tag} product_id must be provided")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="product_id must be provided."
            )

        # Retrieve the product
        try:
            product = Product.get_by_id(product_id, target_business_id)
        except Exception as e:
            Log.error(f"{log_tag} Error fetching product: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while retrieving the product.",
                errors=[str(e)]
            )

        if not product:
            Log.error(f"{log_tag} Product not found")
            return prepared_response(
                status=False,
                status_code="NOT_FOUND",
                message="Product not found."
            )

        # Collect all image file paths
        image_file_paths = product.get("file_paths", []) or []

        # Attempt to delete the product
        try:
            delete_success = Product.delete(product_id, target_business_id)

            if not delete_success:
                Log.error(f"{log_tag} Delete returned False")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Failed to delete product."
                )

            # Delete associated images
            for fp in image_file_paths:
                try:
                    delete_old_image(fp)
                    Log.info(f"{log_tag} Product image {fp} deleted successfully")
                except Exception as e:
                    Log.error(f"{log_tag} Error deleting product image {fp}: {e}")
                    
            
            # Release component quota
            try:
                release_component("products", qty=1, business_id=target_business_id)
                Log.info(f"{log_tag} Released product component quota")
            except Exception as e:
                Log.error(f"{log_tag} Error releasing product component quota: {e}")
                

            Log.info(f"{log_tag} Product deleted successfully")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Product deleted successfully."
            )

        except Exception as e:
            Log.error(f"{log_tag} Error deleting product: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )


@blp_product.route("/products")
class ProductsListResource(MethodView):
    """Product listing with pagination."""

    @token_required
    @crud_read_limiter(entity_name="products_list")
    @blp_product.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_product.response(HTTP_STATUS_CODES["OK"])
    @blp_product.doc(
        summary="List products (role-aware pagination)",
        description="""
            List products with role-based filtering:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - Can pass business_id to view any business's products
                - Can optionally pass user_id to filter by creator

            • BUSINESS_OWNER:
                - Views all products in their business
                - business_id forced to their own

            • Other roles:
                - View only products they created
                - business_id and user__id forced to their own
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle the GET request to list products."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        query_business_id = query_args.get("business_id")
        query_user_id = query_args.get("user_id")
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)

        log_tag = make_log_tag(
            "product_resource.py",
            "ProductsListResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id
        )

        try:
            # Role-based filtering
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                
                if query_user_id:
                    # Admin filtering by specific user
                    result = Product.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page
                    )
                else:
                    # All products in business
                    result = Product.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page
                    )
                    
            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owner sees all products in their business
                result = Product.get_by_business_id(
                    business_id=auth_business_id,
                    page=page,
                    per_page=per_page
                )
            else:
                # Staff see only their own products
                result = Product.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=auth_business_id,
                    page=page,
                    per_page=per_page
                )

            Log.info(f"{log_tag} Retrieved {len(result.get('products', []))} products")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Products retrieved successfully.",
                data=result
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )


@blp_product.route("/products/pos")
class POSProductsResource(MethodView):
    """POS-specific product listing."""

    @token_required
    @crud_read_limiter(entity_name="pos_products")
    @blp_product.arguments(POSProductsQuerySchema, location="query")
    @blp_product.response(HTTP_STATUS_CODES["OK"])
    @blp_product.doc(
        summary="Get POS-enabled products",
        description="""
            Get products suitable for POS display.
            Only returns products with sell_on_point_of_sale=1 and status=Active.
            
            Supports filtering by category and search term.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle the GET request for POS products."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")
        category_id = query_args.get("category_id")
        search_term = query_args.get("search_term")
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)

        # Role-aware business selection
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "product_resource.py",
            "POSProductsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        try:
            result = Product.get_pos_products(
                business_id=target_business_id,
                outlet_id=outlet_id,
                category_id=category_id,
                search_term=search_term,
                page=page,
                per_page=per_page
            )

            Log.info(f"{log_tag} Retrieved {len(result.get('products', []))} POS products")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="POS products retrieved successfully.",
                data=result
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred.",
                errors=[str(e)]
            )

























