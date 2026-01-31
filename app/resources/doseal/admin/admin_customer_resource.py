import bcrypt
import jwt
import os
import time
import secrets

from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue

from datetime import datetime, timedelta
#helper functions
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.file_upload import (
    upload_file, 
    delete_old_image, 
    upload_files
)
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter
)

from ....utils.helpers import make_log_tag
#helper functions

from .admin_business_resource import token_required
from ....utils.json_response import prepared_response
from ....utils.logger import Log # import logging
from ....models.business_model import Business
from ....models.user_model import User
from ....constants.service_code import (
    AUTHENTICATION_MESSAGES, 
    HTTP_STATUS_CODES,
    SERVICE_CODE,
    SYSTEM_USERS
)

from app import db
# schemas
from ....schemas.admin.customer_schema import (
    BusinessIdQuerySchema, CustomerIdQuerySchema, CustomerSchema, CustomerUpdateSchema,
    CustomerGroupSchema, CustomerGroupUpdateSchema, CustomerGroupIdQuerySchema, 
    SystemUserSchema, SystemUserUpdateSchema, SystemUserIdQuerySchema
    
)
from ....schemas.admin.setup_schema import BusinessIdAndUserIdQuerySchema

# model
from ....models.admin.customer_model import (
    Customer, CustomerGroup, SystemUser
)


blp_customer = Blueprint("Customer", __name__,  description="Customer Management")
blp_customer_group = Blueprint("Customer Group", __name__,  description="Customer Group Management")

# -----------------------CUSTOMER -----------------------------------------
@blp_customer.route("/customer", methods=["POST", "GET", "PATCH", "DELETE"])
class CustomerResource(MethodView):
    
    # POST customer
    @token_required
    @crud_write_limiter("customer")
    @blp_customer.arguments(CustomerSchema, location="form")
    @blp_customer.response(201, CustomerSchema)
    @blp_customer.doc(
        summary="Create a new customer",
        description="""
            Create a new customer for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a customer for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.

            Image upload is optional.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, customer_data):
        """Handle the POST request to create a new customer."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        # Log.info(f"user_info: {user_info}")
        # return 

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = customer_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        customer_data["business_id"] = target_business_id
        customer_data["user__id"] = auth_user__id
        if not customer_data.get("user_id"):
            customer_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the customer already exists based on business_id and phone
        try:
            Log.info(f"{log_tag} checking if customer already exists")
            exists = Customer.check_multiple_item_exists(target_business_id, {"phone": customer_data.get("phone")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating customer uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} customer already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Customer already exists",
            )

        # Handle image upload (optional)
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]

            try:
                image_path, actual_path = upload_file(image, target_business_id)
                customer_data["image"] = image_path          # Public/relative path
                customer_data["file_path"] = actual_path     # Actual filesystem path
            except ValueError as e:
                Log.info(f"{log_tag} image upload validation error: {e}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    str(e),
                )

        # Create a new customer instance
        customer = Customer(**customer_data)

        # Try saving the customer to the database
        try:
            Log.info(f"{log_tag} committing customer: {customer_data.get('first_name')} {customer_data.get('last_name')}")
            start_time = time.time()

            customer_id = customer.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} customer created with id={customer_id} "
                f"in {duration:.2f} seconds"
            )

            if customer_id:
                return prepared_response(
                    True,
                    "OK",
                    "Customer created successfully.",
                )

            # If creating customer fails, delete the uploaded image
            if actual_path:
                try:
                    delete_old_image(actual_path)
                except Exception as e:
                    Log.info(f"{log_tag} error deleting uploaded image after failed save: {e}")

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create customer.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving customer: {e}")
            if actual_path:
                try:
                    delete_old_image(actual_path)
                except Exception as e2:
                    Log.info(f"{log_tag} error deleting uploaded image after PyMongoError: {e2}")

            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the customer.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving customer: {e}")
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

    # GET customer by customer_id (role-aware business selection)
    @token_required
    @crud_read_limiter("customer")
    @blp_customer.arguments(CustomerIdQuerySchema, location="query")
    @blp_customer.response(200, CustomerSchema)
    @blp_customer.doc(
        summary="Retrieve customer by customer_id (role-aware)",
        description="""
            Retrieve a customer by `customer_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, customer_data):
        customer_id = customer_data.get("customer_id")
        query_business_id = customer_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag (target_business will be refined after role-based resolution)
        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not customer_id:
            Log.info(f"{log_tag}[customer_id:None] customer_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "customer_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[customer_id:{customer_id}] "
                    f"super_admin/system_owner requesting customer. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[customer_id:{customer_id}] "
                    f"non-admin requesting customer in own business"
                )

            start_time = time.time()
            # Assuming Customer.get_by_id now accepts business scoping like Tax.get_by_id
            customer = Customer.get_by_id(customer_id, target_business_id)
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[customer_id:{customer_id}] "
                f"retrieving customer completed in {duration:.2f} seconds"
            )

            if not customer:
                Log.info(f"{log_tag}[customer_id:{customer_id}] customer not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Customer not found.",
                )

            Log.info(f"{log_tag}[customer_id:{customer_id}] customer found")
            return prepared_response(
                True,
                "OK",
                "Customer retrieved successfully.",
                data=customer,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[customer_id:{customer_id}] PyMongoError while retrieving customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the customer.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag}[customer_id:{customer_id}] unexpected error while retrieving customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
    
    # PATCH customer (role-aware business selection)
    @token_required
    @crud_write_limiter("customer")
    @blp_customer.arguments(CustomerUpdateSchema, location="form")
    @blp_customer.response(200, CustomerUpdateSchema)
    @blp_customer.doc(
        summary="Partially update an existing customer (role-aware)",
        description="""
            Partially update an existing customer by providing `customer_id` and fields to change.

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
        """Handle the PATCH request to partially update an existing customer."""
        customer_id = item_data.get("customer_id")
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

        # Final log tag
        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not customer_id:
            Log.info(f"{log_tag} customer_id not provided")
            return prepared_response(False, "BAD_REQUEST", "customer_id must be provided.")

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

        # Check existing customer in target business scope
        try:
            customer = Customer.get_by_id(customer_id, target_business_id)
            Log.info(f"{log_tag} check_customer")
        except Exception as e:
            Log.info(f"{log_tag} error checking customer existence: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the customer.",
                errors=str(e),
            )

        if not customer:
            Log.info(f"{log_tag} customer not found")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(False, "NOT_FOUND", "Customer not found")

        # Keep old image for removal after successful update
        old_image = customer.get("file_path")

        try:
            Log.info(f"{log_tag} updating customer (PATCH)")
            start_time = time.time()

            # Remove customer_id before patching
            item_data.pop("customer_id", None)

            update_ok = Customer.update(customer_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating customer completed in {duration:.2f} seconds")

                # Delete old image if new one was uploaded
                if actual_path and old_image:
                    try:
                        delete_old_image(old_image)
                        Log.info(f"{log_tag} old image removed successfully")
                    except Exception as e:
                        Log.info(f"{log_tag} error removing old image: {e}")

                return prepared_response(True, "OK", "Customer updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                if actual_path:
                    delete_old_image(actual_path)
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update customer.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating customer: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the customer.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating customer: {e}")
            if actual_path:
                delete_old_image(actual_path)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
    
    # DELETE customer (role-aware business selection)
    @token_required
    @crud_delete_limiter("customer")
    @blp_customer.arguments(CustomerIdQuerySchema, location="query")
    @blp_customer.response(200)
    @blp_customer.doc(
        summary="Delete a customer by customer_id (role-aware)",
        description="""
            Delete a customer using `customer_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, customer_data):
        customer_id = customer_data.get("customer_id")
        query_business_id = customer_data.get("business_id")

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
            "admin_customer_resource.py",
            "CustomerResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )


        # Retrieve the customer
        try:
            customer = Customer.get_by_id(customer_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the customer.",
                errors=str(e),
            )

        if not customer:
            Log.info(f"{log_tag} customer not found")
            return prepared_response(False, "NOT_FOUND", "Customer not found.")

        # Extract image path before deletion
        image_path = customer.get("file_path") if customer.get("file_path") else None

        # Attempt to delete customer
        try:
            delete_success = Customer.delete(customer_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete customer.")

            # Delete image if exists
            if image_path:
                try:
                    delete_old_image(image_path)
                    Log.info(f"{log_tag} customer image deleted: {image_path}")
                except Exception as e:
                    Log.info(f"{log_tag} error deleting customer image: {e}")

            Log.info(f"{log_tag} customer deleted successfully")
            return prepared_response(True, "OK", "Customer deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the customer.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting customer: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_customer.route("/customers", methods=["GET"])
class CustomerResource(MethodView):
    
    @token_required
    @crud_read_limiter("customer")
    @blp_customer.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_customer.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_customer.doc(
        summary="Retrieve customers based on role and permissions",
        description="""
            Retrieve customer details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all customers in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to customers belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Customer(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "customers": [
                                    {
                                        "customer_id": "60a6b938d4d8c24fa0804d62",
                                        "first_name": "John",
                                        "last_name": "Doe",
                                        "email": "johndoe@example.com",
                                        "phone": "0244139938",
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
                "description": "Customers not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Customers not found"
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
                            "message": "An unexpected error occurred while retrieving the customers.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, customer_data):
        page = customer_data.get("page")
        per_page = customer_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = customer_data.get("business_id")
        query_user_id = customer_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Provisional log_tag before we resolve target_business_id
        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerResource",
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
                    "admin_customer_resource.py",
                    "CustomerResource",
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
                    customers_result = Customer.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All customers for that business
                    customers_result = Customer.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all customers in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: customers in own business")

                customers_result = Customer.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own customers in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own customers only")

                customers_result = Customer.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no customers found
            if not customers_result or not customers_result.get("customers"):
                Log.info(f"{log_tag} Customers not found")
                return prepared_response(False, "NOT_FOUND", "Customers not found")

            Log.info(
                f"{log_tag} customer(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": customers_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving customers: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the customers. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving customers: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )

# -----------------------CUSTOMER -----------------------------------------

# -----------------------CUSTOMER GROUP-----------------------------------------
@blp_customer_group.route("/customer-group", methods=["POST", "GET", "PATCH", "DELETE"])
class CustomerGroupResource(MethodView):
    # POST Customer Group (Create a new Customer Group)
    @token_required
    @crud_write_limiter("customergroup")
    @blp_customer_group.arguments(CustomerGroupSchema, location="form")
    @blp_customer_group.response(201, CustomerGroupSchema)
    @blp_customer_group.doc(
        summary="Create a new customer group",
        description="""
            Create a new customer group for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the form to create a group for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, customer_group_data):
        """Handle the POST request to create a new customer group."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = customer_group_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        customer_group_data["business_id"] = target_business_id
        customer_group_data["user__id"] = auth_user__id
        if not customer_group_data.get("user_id"):
            customer_group_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerGroupResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Check if the group already exists (by hashed name within business)
        try:
            Log.info(f"{log_tag} checking if customer group already exists")
            exists = CustomerGroup.check_multiple_item_exists(target_business_id, {"name": customer_group_data.get("name")})
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating customer group uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} customer group already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Customer group already exists",
            )

        # Create a new customer group instance
        customer_group = CustomerGroup(**customer_group_data)

        # Try saving the customer group to the database
        try:
            Log.info(
                f"{log_tag} committing customer group: "
                f"{customer_group_data.get('name')}"
            )
            start_time = time.time()

            customer_group_id = customer_group.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag} customer group created with id={customer_group_id} "
                f"in {duration:.2f} seconds"
            )

            if customer_group_id:
                return prepared_response(
                    True,
                    "OK",
                    "Customer group created successfully.",
                )

            Log.info(f"{log_tag} save returned None")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to create customer group.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the customer group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # GET Customer Group by customer_group_id (role-aware business selection)
    @token_required
    @crud_read_limiter("customergroup")
    @blp_customer_group.arguments(CustomerGroupIdQuerySchema, location="query")
    @blp_customer_group.response(200, CustomerGroupSchema)
    @blp_customer_group.doc(
        summary="Retrieve customer group by customer_group_id (role-aware)",
        description="""
            Retrieve a customer group by `customer_group_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, customer_group_data):
        """Handle the GET request to retrieve a customer group by customer_group_id."""
        customer_group_id = customer_group_data.get("customer_group_id")
        query_business_id = customer_group_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag (target_business will be refined after role-based resolution)
        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerGroupResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        if not customer_group_id:
            Log.info(f"{log_tag}[customer_group_id:None] customer_group_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "customer_group_id must be provided.",
            )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[customer_group_id:{customer_group_id}] "
                    f"super_admin/system_owner requesting customer group. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[customer_group_id:{customer_group_id}] "
                    f"non-admin requesting customer group in own business"
                )

            start_time = time.time()
            customer_group = CustomerGroup.get_by_id(customer_group_id, target_business_id)
            duration = time.time() - start_time
            Log.info(
                f"{log_tag}[customer_group_id:{customer_group_id}] "
                f"retrieving customer group completed in {duration:.2f} seconds"
            )

            if not customer_group:
                Log.info(f"{log_tag}[customer_group_id:{customer_group_id}] customer group not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Customer group not found.",
                )

            Log.info(f"{log_tag}[customer_group_id:{customer_group_id}] customer group found")
            return prepared_response(
                True,
                "OK",
                "Customer group retrieved successfully.",
                data=customer_group,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[customer_group_id:{customer_group_id}] PyMongoError while retrieving customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the customer group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag}[customer_group_id:{customer_group_id}] unexpected error while retrieving customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # PATCH Customer Group (role-aware business selection)
    @token_required
    @crud_write_limiter("customergroup")
    @blp_customer_group.arguments(CustomerGroupUpdateSchema, location="form")
    @blp_customer_group.response(200, CustomerGroupUpdateSchema)
    @blp_customer_group.doc(
        summary="Partially update an existing customer group (role-aware)",
        description="""
            Partially update an existing customer group by providing `customer_group_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the form to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing customer group."""
        customer_group_id = item_data.get("customer_group_id")
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
            "admin_customer_resource.py",
            "CustomerGroupResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not customer_group_id:
            Log.info(f"{log_tag} customer_group_id not provided")
            return prepared_response(False, "BAD_REQUEST", "customer_group_id must be provided.")

        # Check existing customer group in target business scope
        try:
            customer_group = CustomerGroup.get_by_id(customer_group_id, target_business_id)
            Log.info(f"{log_tag} check_customer_group")
        except Exception as e:
            Log.info(f"{log_tag} error checking customer group existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the customer group.",
                errors=str(e),
            )

        if not customer_group:
            Log.info(f"{log_tag} customer group not found")
            return prepared_response(False, "NOT_FOUND", "Customer group not found")

        try:
            Log.info(f"{log_tag} updating customer group (PATCH)")
            start_time = time.time()

            # Remove id before patching
            item_data.pop("customer_group_id", None)

            update_ok = CustomerGroup.update(customer_group_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} updating customer group completed in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Customer group updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update customer group.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the customer group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # DELETE Customer Group (role-aware business selection)
    @token_required
    @crud_delete_limiter("customergroup")
    @blp_customer_group.arguments(CustomerGroupIdQuerySchema, location="query")
    @blp_customer_group.response(200)
    @blp_customer_group.doc(
        summary="Delete a customer group by customer_group_id (role-aware)",
        description="""
            Delete a customer group using `customer_group_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, customer_group_data):
        customer_group_id = customer_group_data.get("customer_group_id")
        query_business_id = customer_group_data.get("business_id")

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
            "admin_customer_resource.py",
            "CustomerGroupResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not customer_group_id:
            Log.info(f"{log_tag} customer_group_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", "customer_group_id must be provided.")

        # Retrieve the customer group
        try:
            customer_group = CustomerGroup.get_by_id(customer_group_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the customer group.",
                errors=str(e),
            )

        if not customer_group:
            Log.info(f"{log_tag} customer group not found")
            return prepared_response(False, "NOT_FOUND", "Customer group not found.")

        # Attempt to delete customer group
        try:
            delete_success = CustomerGroup.delete(customer_group_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete customer group.")

            Log.info(f"{log_tag} customer group deleted successfully")
            return prepared_response(True, "OK", "Customer group deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the customer group.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting customer group: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
            
@blp_customer_group.route("/customer-groups", methods=["GET"])
class CustomerGroupResource(MethodView):
     
    @token_required
    @crud_read_limiter("customergroup")
    @blp_customer_group.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_customer_group.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_customer_group.doc(
        summary="Retrieve customer groups based on role and permissions",
        description="""
            Retrieve customer group details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all customer groups in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to customer groups belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Customer group(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "customer_groups": [
                                    {
                                        "customer_group_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Premium Customers",
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
                "description": "Customer groups not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Customer groups not found"
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
                            "message": "An unexpected error occurred while retrieving the customer groups.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, customer_group_data):
        page = customer_group_data.get("page")
        per_page = customer_group_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = customer_group_data.get("business_id")
        query_user_id = customer_group_data.get("user_id")   # treated as user__id for filtering

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Provisional log_tag before we resolve target_business_id
        log_tag = make_log_tag(
            "admin_customer_resource.py",
            "CustomerGroupResource",
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
                    "admin_customer_resource.py",
                    "CustomerGroupResource",
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
                    customer_groups_result = CustomerGroup.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All customer groups for that business
                    customer_groups_result = CustomerGroup.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all customer groups in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: customer groups in own business")

                customer_groups_result = CustomerGroup.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own customer groups in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "admin_customer_resource.py",
                    "CustomerGroupResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own customer groups only")

                customer_groups_result = CustomerGroup.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # If no customer groups found
            if not customer_groups_result or not customer_groups_result.get("customer_groups"):
                Log.info(f"{log_tag} Customer groups not found")
                return prepared_response(False, "NOT_FOUND", "Customer groups not found")

            Log.info(
                f"{log_tag} customer group(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Success with payload
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": customer_groups_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving customer groups: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the customer groups. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving customer groups: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )
# -----------------------CUSTOMER GROUP-----------------------------------------