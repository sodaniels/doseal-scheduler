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
from ....utils.file_upload import (
    upload_file, upload_file_to_bucket
)
from ....utils.crypt import encrypt_data, decrypt_data, hash_data

from ....utils.helpers import (
    validate_and_format_phone_number, create_token_response_admin, 
    generate_tokens, safe_decrypt
)

from ....utils.rate_limits import (
    login_ip_limiter, 
    login_user_limiter,
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
    logout_rate_limiter
)
from ....utils.helpers import resolve_target_business_id_from_payload

from ....utils.json_response import prepared_response
from ....utils.essentials import Essensial
from ....utils.helpers import make_log_tag
from ....utils.generators import generate_confirm_email_token
from tasks import send_user_registration_email
#helper functions

from .admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....constants.service_code import (
    HTTP_STATUS_CODES, PERMISSION_FIELDS_FOR_ADMINS, 
    PERMISSION_FIELDS_FOR_ADMIN_ROLE,
    PERMISSION_FIELDS_FOR_AGENT_ROLE,
    SYSTEM_USERS, BUSINESS_FIELDS
)

from ....models.business_model import Client, Token
from ....models.device_model import Device
from ....models.subscriber_model import Subscriber

# schemas
from ....schemas.super_superadmin_schema import (
    BusinessIdQuerySchema, RoleSchema, RoleUpdateSchema, RoleIdQuerySchema,
    ExpenseIdQuerySchema, ExpenseSchema, ExpenseUpdateSchema, AgentIdQuerySchema,
    SystemUserSchema, SystemUserUpdateSchema, SystemAdminIdQuerySchema, RolesSchema,
    AgentsQuerySchema, ExpensesSchema, DownloadsSchema, SelectMoreSchema,
    SubscriberQuerySchema, SubscribersSchema, SearchSubscriberQuerySchema
)
from ....schemas.login_schema import LoginSchema
from ....schemas.admin.setup_schema import BusinessIdAndUserIdQuerySchema
# models
from ....models.admin.super_superadmin_model import (
    Role, Expense, Admin
)
from ....models.business_model import Business
from ....models.user_model import User

blp_admin_role = Blueprint("Admin Role", __name__,  description="Admin Role Management")
blp_admin_expense = Blueprint("Admin Expense", __name__,  description="Admin Expense Management")
blp_system_admin_user = Blueprint("Admin User", __name__,  description="Admin Use Management")
blp_expense = Blueprint("Expense", __name__,  description="Expense Management")


# -----------------------------ROLE-----------------------------------

@blp_admin_role.route("/role", methods=["POST", "GET", "PATCH", "DELETE"])
class RoleResource(MethodView):
    # ------------------------- CREATE ROLE (POST) ---------------------------- #
    @token_required
    @crud_write_limiter("role")
    @blp_admin_role.arguments(RoleSchema, location="json")
    @blp_admin_role.response(201, RoleSchema)
    @blp_admin_role.doc(
        summary="Create a new role",
        description="""
            Create a new role for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the payload to create a role for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new role."""
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

        # Role creator/admin
        item_data["admin_id"] = str(user_info.get("_id")) if user_info.get("_id") else None
        item_data["created_by"] = str(user_info.get("_id")) if user_info.get("_id") else None

        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "RoleResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # ----------------- Normalise permissions only for provided fields ----------------- #
        # PERMISSION_FIELDS_FOR_ADMIN_ROLE is assumed to be:
        # { "user": ["view", "add", "edit", "delete"], "role": [...], ... }
        for perm_field, actions in PERMISSION_FIELDS_FOR_ADMIN_ROLE.items():
            if perm_field in item_data and item_data[perm_field]:
                normalised_list = []
                for entry in item_data[perm_field]:
                    norm = {}
                    for action in actions:
                        norm[action] = entry.get(action, "0")
                    normalised_list.append(norm)
                item_data[perm_field] = normalised_list
            # If perm_field not present, we DO NOT create it with zeros here
            # so the model won't store non-explicit permission fields.

        # ----------------- Duplicate check ----------------- #
        name = item_data.get("name")
        email = item_data.get("email")

        Log.info(f"{log_tag} checking if role already exists")
        try:
            exists = Role.check_role_exists(
                admin_id=item_data["admin_id"],
                name_key="name",
                name_value=name,
                email_key="email",
                email_value=email,
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating role uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} role already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Role already exists.",
            )

        Log.info(f"{log_tag} creating role with payload: {item_data}")

        # ----------------- Create and save ----------------- #
        role = Role(**item_data)

        try:
            Log.info(f"{log_tag} committing role transaction")
            start_time = time.time()
            role_id = role.save()
            duration = time.time() - start_time

            Log.info(f"{log_tag} role created with id={role_id} in {duration:.2f} sec")

            if role_id:
                return prepared_response(
                    True,
                    "CREATED",
                    "Role created successfully.",
                )

            Log.info(f"{log_tag} save returned None")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to create role.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while creating role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while creating the role.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while creating role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE ROLE (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("role")
    @blp_admin_role.arguments(RoleIdQuerySchema, location="query")
    @blp_admin_role.response(200, RoleSchema)
    @blp_admin_role.doc(
        summary="Retrieve role by role_id (role-aware)",
        description="""
            Retrieve a role by `role_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, role_data):
        role_id = role_data.get("role_id")
        query_business_id = role_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Initial log_tag
        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "RoleResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        Log.info(f"{log_tag} retrieving role")

        if not role_id:
            Log.info(f"{log_tag} role_id not provided")
            return prepared_response(False, "BAD_REQUEST", "role_id must be provided.")

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                log_tag = make_log_tag(
                    "super_superadmin_resource.py",
                    "RoleResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[role_id:{role_id}] "
                    f"super_admin/system_owner requesting role. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                log_tag = make_log_tag(
                    "super_superadmin_resource.py",
                    "RoleResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )
                Log.info(
                    f"{log_tag}[role_id:{role_id}] "
                    f"non-admin requesting role in own business"
                )

            start_time = time.time()
            role = Role.get_by_id(role_id=role_id, business_id=target_business_id)
            duration = time.time() - start_time

            Log.info(
                f"{log_tag}[role_id:{role_id}] "
                f"retrieving role completed in {duration:.2f} seconds"
            )

            if not role:
                Log.info(f"{log_tag}[role_id:{role_id}] role not found")
                return prepared_response(False, "NOT_FOUND", "Role not found.")

            Log.info(f"{log_tag}[role_id:{role_id}] role found")
            return prepared_response(
                True,
                "OK",
                "Role retrieved successfully.",
                data=role,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag}[role_id:{role_id}] PyMongoError while retrieving role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the role.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag}[role_id:{role_id}] unexpected error while retrieving role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE ROLE (role-aware PATCH) ---------------------- #
    @token_required
    @crud_write_limiter("role")
    @blp_admin_role.arguments(RoleUpdateSchema, location="json")
    @blp_admin_role.response(200, RoleUpdateSchema)
    @blp_admin_role.doc(
        summary="Update an existing role (role-aware)",
        description="""
            Update an existing role by providing `role_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the payload to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing role."""
        role_id = item_data.get("role_id")

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
            "super_superadmin_resource.py",
            "RoleResource",
            "patch",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        Log.info(f"{log_tag}[role_id:{role_id}] updating role")

        if not role_id:
            Log.info(f"{log_tag} role_id not provided")
            return prepared_response(False, "BAD_REQUEST", "role_id must be provided.")

        # Ensure role exists within target business scope
        try:
            role = Role.get_by_id(role_id=role_id, business_id=target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error checking role existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the role.",
                errors=str(e),
            )

        if not role:
            Log.info(f"{log_tag} role not found")
            return prepared_response(False, "NOT_FOUND", "Role not found.")

        # ----------------- Normalise permissions only for provided fields ----------------- #
        for perm_field, actions in PERMISSION_FIELDS_FOR_ADMIN_ROLE.items():
            if perm_field in item_data and item_data[perm_field]:
                normalised_list = []
                for entry in item_data[perm_field]:
                    norm = {}
                    for action in actions:
                        norm[action] = entry.get(action, "0")
                    normalised_list.append(norm)
                item_data[perm_field] = normalised_list

        # Attempt to update the role data
        try:
            Log.info(f"{log_tag} updating role (PATCH)")
            start_time = time.time()

            # Don't try to overwrite id
            item_data.pop("role_id", None)

            update_ok = Role.update(role_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} role updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Role updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update role.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the role.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE ROLE (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("role")
    @blp_admin_role.arguments(RoleIdQuerySchema, location="query")
    @blp_admin_role.response(200)
    @blp_admin_role.doc(
        summary="Delete a role by role_id (role-aware)",
        description="""
            Delete a role using `role_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, role_data):
        role_id = role_data.get("role_id")
        query_business_id = role_data.get("business_id")

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
            "super_superadmin_resource.py",
            "RoleResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        Log.info(f"{log_tag} initiated delete role")

        if not role_id:
            Log.info(f"{log_tag} role_id must be provided")
            return prepared_response(False, "BAD_REQUEST", "role_id must be provided.")

        # Retrieve the role
        try:
            role = Role.get_by_id(role_id=role_id, business_id=target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the role.",
                errors=str(e),
            )

        if not role:
            Log.info(f"{log_tag} role not found")
            return prepared_response(False, "NOT_FOUND", "Role not found.")

        # Attempt to delete role
        try:
            delete_success = Role.delete(role_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete role.")

            Log.info(f"{log_tag} role deleted successfully")
            return prepared_response(True, "OK", "Role deleted successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the role.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

@blp_admin_role.route("/roles", methods=["GET"])
class RoleListResource(MethodView):

    @token_required
    @crud_read_limiter("role")
    @blp_admin_role.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_admin_role.response(200, RolesSchema)
    @blp_admin_role.doc(
        summary="Retrieve roles based on role and permissions",
        description="""
            Retrieve role details with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all roles in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to roles belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Role(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "roles": [
                                    {
                                        "role_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Admin",
                                        "permissions": {
                                            "store": [{"read": "1", "create": "1", "update": "1", "delete": "1"}],
                                            "product": [{"read": "1", "create": "1"}],
                                        },
                                        "status": "Active",
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
                "description": "Roles not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Roles not found"
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
                            "message": "An unexpected error occurred while retrieving the roles.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, query_data):

        # Pagination
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
            "super_superadmin_resource.py",
            "RoleListResource",
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

                # Refresh log_tag now that we know the real target_business_id
                log_tag = make_log_tag(
                    "super_superadmin_resource.py",
                    "RoleListResource",
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
                    roles_result = Role.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All roles for that business
                    roles_result = Role.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all roles in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "super_superadmin_resource.py",
                    "RoleListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} business_owner: roles in own business")

                roles_result = Role.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own roles in their own business
                target_business_id = auth_business_id

                log_tag = make_log_tag(
                    "super_superadmin_resource.py",
                    "RoleListResource",
                    "get",
                    client_ip,
                    auth_user__id,
                    account_type,
                    auth_business_id,
                    target_business_id,
                )

                Log.info(f"{log_tag} staff/other: own roles only")

                roles_result = Role.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            # -------------------------
            # NOT FOUND
            # -------------------------
            if not roles_result or not roles_result.get("roles"):
                Log.info(f"{log_tag} Roles not found")
                return prepared_response(False, "NOT_FOUND", "Roles not found")

            Log.info(
                f"{log_tag} role(s) found for "
                f"target_business_id={target_business_id}"
            )

            # -------------------------
            # SUCCESS RESPONSE
            # -------------------------
            return prepared_response(
                True,
                "OK",
                "Roles retrieved successfully.",
                data=roles_result,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving roles: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the roles. {str(e)}",
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving roles: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}",
            )
# -----------------------------ROLE-----------------------------------

# -----------------------------EXPENSE----------------------------------
@blp_expense.route("/expense", methods=["POST", "GET", "PATCH", "DELETE"])
class ExpenseResource(MethodView):
    # ------------------------------------------------------------------
    # POST expense (role-aware business selection)
    # ------------------------------------------------------------------
    @token_required
    @crud_write_limiter("expense")
    @blp_expense.arguments(ExpenseSchema, location="form")
    @blp_expense.response(201, ExpenseSchema)
    @blp_expense.doc(
        summary="Create a new expense transaction",
        description="""
            Create a new expense transaction for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the payload to create an expense for any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new expense transaction."""
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
            f"[expense_resource.py][ExpenseResource][post]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][user__id:{auth_user__id}]"
        )

        # Check if a similar expense already exists for this business (e.g. by name)
        try:
            Log.info(f"{log_tag} checking if the expense already exists")
            exists = Expense.check_multiple_item_exists(
                target_business_id,
                {"name": item_data.get("name")}
            )
        except Exception as e:
            Log.info(f"{log_tag} error while checking duplicate expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred while validating expense uniqueness.",
                errors=str(e),
            )

        if exists:
            Log.info(f"{log_tag} expense already exists")
            return prepared_response(
                False,
                "CONFLICT",
                "Expense already exists",
            )

        # Create a new expense instance
        item = Expense(**item_data)

        # Save and handle errors
        try:
            Log.info(f"{log_tag} committing expense: {item_data.get('name')}")
            start_time = time.time()

            expense_id = item.save()

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} expense created with id={expense_id} "
                f"in {duration:.2f} seconds"
            )

            return prepared_response(
                True,
                "OK",
                "Expense transaction created successfully.",
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while saving expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while saving the expense.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while saving expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------------------------------------------------
    # GET expense by expense_id (role-aware business selection)
    # ------------------------------------------------------------------
    @token_required
    @crud_read_limiter("expense")
    @blp_expense.arguments(ExpenseIdQuerySchema, location="query")
    @blp_expense.response(200, ExpenseSchema)
    @blp_expense.doc(
        summary="Retrieve expense by expense_id (role-aware)",
        description="""
            Retrieve an expense by `expense_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, expense_data):
        expense_id = expense_data.get("expense_id")
        query_business_id = expense_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[expense_resource.py][ExpenseResource][get]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[auth_user__id:{auth_user__id}][role:{account_type}]"
            f"[expense_id:{expense_id}]"
        )

        try:
            # Business resolution based on role
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
                target_business_id = query_business_id or auth_business_id
                Log.info(
                    f"{log_tag} super_admin/system_owner requesting expense. "
                    f"target_business_id={target_business_id}"
                )
            else:
                target_business_id = auth_business_id
                Log.info(f"{log_tag} non-admin requesting expense in own business")

            expense = Expense.get_by_id(expense_id, target_business_id)

            if not expense:
                Log.info(f"{log_tag} expense not found")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Expense not found.",
                )

            Log.info(f"{log_tag} expense found")
            return prepared_response(
                True,
                "OK",
                "Expense retrieved successfully.",
                data=expense,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError retrieving expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while retrieving the expense.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error retrieving expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------------------------------------------------
    # PATCH expense (role-aware business selection)
    # ------------------------------------------------------------------
    @token_required
    @crud_write_limiter("expense")
    @blp_expense.arguments(ExpenseUpdateSchema, location="form")
    @blp_expense.response(200, ExpenseUpdateSchema)
    @blp_expense.doc(
        summary="Update an existing expense",
        description="""
            Update an existing expense by providing `expense_id` and new details.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the payload to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the PATCH request to update an existing expense."""
        expense_id = item_data.get("expense_id")

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
            f"[expense_resource.py][ExpenseResource][patch]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}]"
            f"[expense_id:{expense_id}]"
        )

        # Check if the expense exists
        try:
            expense = Expense.get_by_id(expense_id, target_business_id)
            Log.info(f"{log_tag} check_expense")
        except Exception as e:
            Log.info(f"{log_tag} error checking expense existence: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while checking the expense.",
                errors=str(e),
            )

        if not expense:
            Log.info(f"{log_tag} expense not found")
            return prepared_response(False, "NOT_FOUND", "Expense not found")

        # Attempt to update the expense data
        try:
            Log.info(f"{log_tag} updating expense")

            start_time = time.time()

            # Don't try to overwrite _id
            item_data.pop("expense_id", None)

            update = Expense.update(expense_id, **item_data)

            duration = time.time() - start_time

            if update:
                Log.info(f"{log_tag} expense updated in {duration:.2f} seconds")
                return prepared_response(True, "OK", "Expense updated successfully.")
            else:
                Log.info(f"{log_tag} failed to update expense")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to update expense.",
                )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError updating expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the expense.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error updating expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ------------------------------------------------------------------
    # DELETE expense (role-aware business selection)
    # ------------------------------------------------------------------
    @token_required
    @crud_delete_limiter("expense")
    @blp_expense.arguments(ExpenseIdQuerySchema, location="query")
    @blp_expense.response(200)
    @blp_expense.doc(
        summary="Delete an expense by expense_id",
        description="""
            Delete an expense using `expense_id` from the query parameters.

            • If ?business_id=<id> is submitted, deletion will target that business.  
            • Otherwise, deletion defaults to the authenticated user's business_id.

            Permissions are fully enforced in BaseModel.delete().
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, expense_data):
        expense_id = expense_data.get("expense_id")
        query_business_id = expense_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Admins can choose business_id via query, others are bound to their own business.
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = (
            f"[expense_resource.py][ExpenseResource][delete]"
            f"[{client_ip}][auth_business:{auth_business_id}]"
            f"[target_business:{target_business_id}][expense_id:{expense_id}]"
        )

        # Retrieve the expense
        try:
            expense = Expense.get_by_id(expense_id, target_business_id)
        except Exception as e:
            Log.info(f"{log_tag} error fetching expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the expense.",
                errors=str(e),
            )

        if not expense:
            Log.info(f"{log_tag} expense not found")
            return prepared_response(False, "NOT_FOUND", "Expense not found.")

        # Attempt to delete the expense
        try:
            delete_success = Expense.delete(expense_id, target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to delete expense.")

            Log.info(f"{log_tag} expense deleted successfully")
            return prepared_response(True, "OK", "Expense deleted successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError deleting expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the expense.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error deleting expense: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )


@blp_expense.route("/expenses", methods=["GET"])
class ExpenseResource(MethodView):
    
    @token_required
    @crud_read_limiter("expense")
    @blp_expense.arguments(BusinessIdAndUserIdQuerySchema, location="query")
    @blp_expense.response(200, BusinessIdAndUserIdQuerySchema)
    @blp_expense.doc(
        summary="Retrieve expenses based on role and permissions",
        description="""
            Retrieve expenses with role-aware access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may pass ?business_id=<id> to target any business
                - may optionally pass ?user_id=<id> to filter by a specific user (agent/admin) within that business
                - if no business_id is provided, defaults to their own business_id

            • BUSINESS_OWNER:
                - can see all expenses in their own business
                - query parameters business_id / user_id are ignored

            • Other staff:
                - restricted to expenses belonging to their own user__id in their own business
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Expense(s) retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "expenses": [
                                    {
                                        "_id": "60a6b938d4d8c24fa0804d62",
                                        "name": "Office Supplies",
                                        "description": "Purchase of office supplies for the month",
                                        "category": "Supplies",
                                        "date": "2023-03-01",
                                        "amount": 200.0,
                                        "status": "Active",
                                        "user_id": "abcd1234",
                                        "admin_id": "efgh5678",
                                        "business_id": "ijkl9012",
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
                "description": "Expenses not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Expenses not found"
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
                            "message": "An unexpected error occurred while retrieving the expenses.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def get(self, expense_data):
        """
        Retrieve expenses with role-aware scoping and optional pagination.
        Uses the same access pattern as UnitListResource.
        """
        page = expense_data.get("page")
        per_page = expense_data.get("per_page")

        # Optional filters from query (used mainly by super_admin/system_owner)
        query_business_id = expense_data.get("business_id")
        query_user_id = expense_data.get("user_id")  # treated as user__id / agent/admin id

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = (
            f"[super_superadmin_resource.py][ExpenseResource][get]"
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
                    # Filter by a specific user (agent/admin) within the chosen business
                    expenses_result = Expense.get_by_user__id_and_business_id(
                        user__id=query_user_id,
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )
                else:
                    # All expenses for that business
                    expenses_result = Expense.get_by_business_id(
                        business_id=target_business_id,
                        page=page,
                        per_page=per_page,
                    )

            elif account_type == SYSTEM_USERS["BUSINESS_OWNER"]:
                # Business owners see all expenses in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} business_owner: expenses in own business")

                expenses_result = Expense.get_by_business_id(
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

            else:
                # Staff / regular users see only their own expenses in their own business
                target_business_id = auth_business_id
                Log.info(f"{log_tag} staff/other: own expenses only")

                expenses_result = Expense.get_by_user__id_and_business_id(
                    user__id=auth_user__id,
                    business_id=target_business_id,
                    page=page,
                    per_page=per_page,
                )

           
            if not expenses_result or not expenses_result.get("expenses"):
                Log.info(f"{log_tag} Expenses not found")
                return prepared_response(False, "NOT_FOUND", "Expenses not found")

            Log.info(
                f"{log_tag} expense(s) found for "
                f"target_business_id={target_business_id}"
            )

            # Optional: normalize ObjectId fields in each expense if needed
            for expense in expenses_result.get("expenses", []):
                if "_id" in expense:
                    expense["_id"] = str(expense["_id"])
                if "user_id" in expense:
                    expense["user_id"] = str(expense["user_id"])
                if "admin_id" in expense:
                    expense["admin_id"] = str(expense["admin_id"])
                if "business_id" in expense:
                    expense["business_id"] = str(expense["business_id"])

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": expenses_result,
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving expenses: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred while retrieving the expenses. {str(e)}"
            )

        except Exception as e:
            Log.info(f"{log_tag} Unexpected error while retrieving expenses: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                f"An unexpected error occurred. {str(e)}"
            )

# -----------------------------EXPENSE----------------------------------

# -----------------------SYSTEM USER-----------------------------------------
@blp_system_admin_user.route("/admin", methods=["POST", "GET", "PUT", "DELETE"])
class AdminResource(MethodView):
    
    # ------------------------- CREATE ADMIN (POST) ------------------------- #
    @token_required
    @crud_write_limiter("admin")
    @blp_system_admin_user.arguments(SystemUserSchema, location="form")
    @blp_system_admin_user.response(201, SystemUserSchema)
    @blp_system_admin_user.doc(
        summary="Create a new system user",
        description="""
            Create a new system user (admin account) for a business.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - May submit business_id in the payload to create an admin in any business.
                - If omitted, defaults to their own business_id.

            • Other roles:
                - business_id is always forced to the authenticated user's business_id.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SystemUserSchema,
                    "example": {
                        "fullname": "John Doe",
                        "phone": "123-456-7890",
                        "email": "johndoe@example.com",
                        "role": "60a6b938d4d8c24fa0804d63",
                        "password": "Secret123!",
                        "image": "file (profile.jpg)"  # Uploaded as part of form-data
                    }
                }
            },
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new system user."""
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
        item_data["created_by"] = str(user_info.get("_id"))
        role_id = item_data.get("role")

        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # ----------------- BUSINESS / TENANT RESOLUTION ----------------- #
        business = Business.get_business_by_id(target_business_id)
        if not business:
            Log.info(f"{log_tag} Could not retrieve business information")
            return prepared_response(False, "BAD_REQUEST", "Could not retrieve business information.")

        tenant_id_encrypted = business.get("tenant_id")
        tenant_id = decrypt_data(tenant_id_encrypted)

        if not tenant_id:
            Log.info(f"{log_tag} Could not retrieve tenant information")
            return prepared_response(False, "BAD_REQUEST", "Could not retrieve tenant information.")

        tenant = Essensial.get_tenant_by_id(tenant_id)
        country_iso_2 = tenant.get("country_iso_2")
        country_name = tenant.get("country_name")

        phone_number = validate_and_format_phone_number(item_data.get("phone"), country_iso_2)
        if not phone_number:
            Log.info(f"{log_tag} Invalid phone number of {country_name}")
            return prepared_response(False, "BAD_REQUEST", f"Invalid phone number of {country_name}")

        item_data["phone"] = phone_number

        # ----------------- ROLE VALIDATION ----------------- #
        try:
            role = Role.get_by_id(role_id=role_id, business_id=target_business_id)
            if role is None:
                Log.info(f"{log_tag} role_id={role_id} not found for business_id={target_business_id}")
                return prepared_response(False, "BAD_REQUEST", "The role_id could not be found.")
        except Exception as e:
            Log.info(f"{log_tag} error retrieving role: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the role.",
                errors=str(e),
            )

        # ----------------- IMAGE UPLOAD (OPTIONAL) ----------------- #
        actual_path = None
        if "image" in request.files:
            image = request.files["image"]
            try:
                image_path, actual_path = upload_file(image, user_info.get("agent_id"))
                item_data["image"] = image_path
                item_data["file_path"] = actual_path
            except ValueError as e:
                return prepared_response(False, "BAD_REQUEST", f"Error uploading image. {str(e)}")

        # ----------------- UNIQUENESS CHECKS (EMAIL, PHONE) ----------------- #
        Log.info(f"{log_tag} [{client_ip}] checking if admin (email) already exists")
        if Admin.check_multiple_item_exists(target_business_id, {"email": item_data.get("email")}):
            if actual_path:
                os.remove(actual_path)
            Log.info(f"{log_tag} [{client_ip}] checking if admin (phone) already exists")    
            return prepared_response(False, "CONFLICT", "Admin account already exists")


        # Hash password before passing into Admin and User
        item_data["password"] = bcrypt.hashpw(
            item_data["password"].encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # ----------------- CREATE ADMIN ----------------- #
        item = Admin(**item_data)

        try:
            Log.info(f"{log_tag} [{client_ip}][{item_data['email']}][committing system user]")

            start_time = time.time()
            system_user_id = item.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag} [{client_ip}][{system_user_id}] committing system user "
                f"completed in {duration:.2f} seconds"
            )

            # Also create corresponding User record (if Admin creation succeeded)
            try:
                if system_user_id:
                    client_id = business.get("client_id")

                    user_data = {
                        "admin_id": str(system_user_id),
                        "fullname": item_data["fullname"],
                        "email": item_data["email"],
                        "phone_number": item_data["phone"],
                        "password": item_data["password"],
                        "role": str(item_data["role"]),
                        "created_by": auth_user__id,
                        "client_id": client_id,
                        "business_id": target_business_id,
                        "status": "Active",
                        "email_verified": "verified",
                        "account_type": "admin",
                    }

                    user = User(**user_data)
                    user_client_id = user.save()
                    Log.info(f"{log_tag} user_client_id: {user_client_id}")
            except Exception as e:
                Log.error(f"{log_tag}[{client_ip}][{system_user_id}] error creating User record: {str(e)}")

            if system_user_id is not None:
                return prepared_response(True, "OK", "Admin created successfully.")
            else:
                if actual_path:
                    os.remove(actual_path)
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to create system user.")

        except PyMongoError as e:
            if actual_path:
                os.remove(actual_path)
            Log.info(f"{log_tag} PyMongoError while creating admin: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
        except Exception as e:
            if actual_path:
                os.remove(actual_path)
            Log.info(f"{log_tag} unexpected error while creating admin: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- GET SINGLE ADMIN (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("admin")
    @blp_system_admin_user.arguments(SystemAdminIdQuerySchema, location="query")
    @blp_system_admin_user.response(200, SystemUserSchema)
    @blp_system_admin_user.doc(
        summary="Retrieve system user by admin_id (role-aware)",
        description="""
            Retrieve a system user by `admin_id`, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to target any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, system_user_data):
        admin_id = system_user_data.get("admin_id")
        query_business_id = system_user_data.get("business_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        Log.info(f"{log_tag} retrieving system user by admin_id={admin_id}")

        if not admin_id:
            return prepared_response(False, "BAD_REQUEST", "admin_id must be provided.")

        # Role-aware business resolution
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        # Rebuild log_tag with resolved target_business_id
        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            start_time = time.time()
            system_user = Admin.get_by_id(target_business_id, admin_id)

            if system_user:
                system_user.pop("file_path", None)

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} retrieving system user completed in {duration:.2f} seconds"
            )

            if not system_user:
                return prepared_response(False, "NOT_FOUND", "System user not found.")

            Log.info(f"{log_tag} system user found")
            return prepared_response(
                True,
                "OK",
                "System user retrieved successfully.",
                data=system_user,
            )

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving system user: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the system user.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while retrieving system user: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- UPDATE ADMIN (role-aware PUT) ---------------------- #
    @token_required
    @crud_write_limiter("admin")
    @blp_system_admin_user.arguments(SystemUserUpdateSchema, location="form")
    @blp_system_admin_user.response(200, SystemUserUpdateSchema)
    @blp_system_admin_user.doc(
        summary="Update an existing system user (role-aware)",
        description="""
            Update an existing system user by providing `admin_id` and fields to change.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit business_id in the payload to select target business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def put(self, item_data):
        """Handle the PUT request to update an existing system user."""
        admin_id = item_data.get("admin_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for system_owner / super_admin
        form_business_id = item_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        item_data["business_id"] = target_business_id
        item_data["user_id"] = user_info.get("user_id")

        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "put",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        Log.info(f"{log_tag} updating system user admin_id={admin_id}")

        if not admin_id:
            return prepared_response(False, "BAD_REQUEST", "admin_id must be provided.")

        # Check if the system user exists
        user = Admin.get_by_id(business_id=target_business_id, system_user_id=admin_id)
        if not user:
            Log.info(f"{log_tag} Admin user not found")
            return prepared_response(False, "NOT_FOUND", "Admin user not found.")

        try:
            Log.info(f"{log_tag} updating system user")
            start_time = time.time()

            update = Admin.update(admin_id, **item_data)

            duration = time.time() - start_time
            if update:
                Log.info(
                    f"{log_tag} updating Admin completed in {duration:.2f} seconds"
                )
                return prepared_response(True, "OK", "Admin updated successfully.")
            else:
                Log.info(f"{log_tag} update returned False")
                return prepared_response(False, "BAD_REQUEST", "Failed to update system user.")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while updating system user: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while updating the system user.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while updating system user: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )

    # ---------------------- DELETE ADMIN (role-aware) ---------------------- #
    @token_required
    @crud_delete_limiter("admin")
    @blp_system_admin_user.arguments(SystemAdminIdQuerySchema, location="query")
    @blp_system_admin_user.response(200)
    @blp_system_admin_user.doc(
        summary="Delete a system user by admin_id (role-aware)",
        description="""
            Delete a system user using `admin_id` from the query parameters.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to delete from any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - deletion always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
    )
    def delete(self, item_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        admin_id = item_data.get("admin_id")
        query_business_id = item_data.get("business_id")

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Role-aware business resolution
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "delete",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not admin_id:
            Log.info(f"{log_tag} admin_id must be provided")
            return prepared_response(False, "BAD_REQUEST", "admin_id must be provided.")

        # Retrieve the system user
        user = Admin.get_by_id(business_id=target_business_id, system_user_id=admin_id)
        if not user:
            Log.info(f"{log_tag} Admin account not found")
            return prepared_response(False, "NOT_FOUND", "Admin account not found.")

        try:
            delete_success = Admin.delete(system_user_id=admin_id, business_id=target_business_id)

            if not delete_success:
                Log.info(f"{log_tag} delete returned False")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to delete admin account.",
                )

            Log.info(f"{log_tag} Admin account deleted successfully")
            return prepared_response(True, "OK", "Admin account deleted successfully")

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while deleting admin account: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while deleting the admin account.",
                errors=str(e),
            )
        except Exception as e:
            Log.info(f"{log_tag} unexpected error while deleting admin account: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
            
@blp_system_admin_user.route("/admins", methods=["GET"])
class AdminResource(MethodView):
    
    # ---------------------- LIST SYSTEM USERS (role-aware) ---------------------- #
    @token_required
    @crud_read_limiter("admin")
    @blp_system_admin_user.arguments(AgentsQuerySchema, location="query")
    @blp_system_admin_user.response(200, SystemUserSchema)
    @blp_system_admin_user.doc(
        summary="Retrieve system users (role-aware)",
        description="""
            Retrieve system users for a business, enforcing role-based access:

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit ?business_id=<id> to list admins for any business
                - if omitted, defaults to their own business_id

            • Other roles:
                - always restricted to their own business_id.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "System users retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "user_id": "60a6b938d4d8c24fa0804d62",
                                    "business_id": "60a6b938d4d8c24fa0804d60",
                                    "agent_id": "60a6b938d4d8c24fa0804d64",
                                    "fullname": "John Doe",
                                    "email": "john_doe@example.com",
                                    "phone": "+441234567890",
                                    "status": "Active",
                                    "role": {
                                        "role_id": "60a6b938d4d8c24fa0804d63",
                                        "name": "Admin",
                                        "status": "Active",
                                        "permissions": {
                                            "product": [{"view": "1", "add": "1", "edit": "1", "delete": "1"}],
                                            "sale": [{"view": "1", "add": "1"}]
                                        }
                                    }
                                }
                            ]
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
                "description": "Admin users not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Admin users not found"
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
    )
    def get(self, item_data):
        """Handle the GET request to retrieve system users (admins) for a business."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        query_business_id = item_data.get("business_id")

        # Initial log_tag before resolving target_business_id
        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            query_business_id or auth_business_id,
        )

        Log.info(f"{log_tag} initiated get system users")

        # Role-aware business resolution
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and query_business_id:
            target_business_id = query_business_id
        else:
            target_business_id = auth_business_id

        # Rebuild log_tag with resolved target_business_id
        log_tag = make_log_tag(
            "super_superadmin_resource.py",
            "AdminResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            start_time = time.time()

            admins = Admin.get_system_users_by_business(target_business_id)

            duration = time.time() - start_time
            Log.info(
                f"{log_tag} retrieving system users for business_id={target_business_id} "
                f"completed in {duration:.2f} seconds"
            )

            if not admins:
                Log.info(f"{log_tag} Admin users not found")
                return prepared_response(False, "NOT_FOUND", "Admin users not found")

            # Clean up transient fields if present
            for user in admins:
                user.pop("file_path", None)

            Log.info(f"{log_tag} admin users found")
            return jsonify(
                {
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "data": admins,
                }
            ), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} PyMongoError while retrieving admins: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while retrieving the admins.",
                errors=str(e),
            )

        except Exception as e:
            Log.info(f"{log_tag} unexpected error while retrieving admins: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred.",
                errors=str(e),
            )
            
@blp_admin_role.route("/available-roles", methods=["GET"])
class AvailableRoleResource(MethodView):
    
    @token_required
    @crud_read_limiter("availableroles")
    @blp_admin_role.doc(
        summary="Retrieve roles by agent_id",
        description="""
            This endpoint allows you to retrieve roles based on the `agent_id` in the query parameters.
            - **GET**: Retrieve role(s) by providing `agent_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Roles retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "role_id": "60a6b938d4d8c24fa0804d62",
                                    "name": "Admin",
                                    "permissions": {
                                        "admin": [
                                            "read",
                                            "create",
                                            "edit",
                                            "export",
                                            "delete"
                                        ],
                                        "agents": [
                                            "read",
                                            "create",
                                            "edit",
                                            "export",
                                            "edit",
                                            "whitelist",
                                            "update_balance",
                                            "upate_commission",
                                            "approve_balance"
                                        ],
                                        "agents_onboarding": [
                                            "approve",
                                            "reject",
                                            "assign",
                                            "export"
                                        ],
                                        "business": [
                                            "read",
                                            "create",
                                            "edit"
                                        ],
                                        "complaints": [
                                            "read",
                                            "resolve",
                                            "export",
                                            "reply"
                                        ],
                                        "dashboard": [
                                            "read"
                                        ],
                                        "download": [
                                            "read",
                                            "export"
                                        ],
                                        "feebacks": [
                                            "read",
                                            "export"
                                        ],
                                        "messaging": [
                                            "read",
                                            "send",
                                            "export"
                                        ],
                                        "onboarding": [
                                            "read",
                                            "approve",
                                            "reject",
                                            "export"
                                        ],
                                        "referrals": [
                                            "read",
                                            "create",
                                            "edit",
                                            "export"
                                        ],
                                        "transactions": [
                                            "read",
                                            "export"
                                        ],
                                        "view_balance_history": [
                                            "read",
                                            "export"
                                        ]
                                    },
                                    "agent_id": "abcd1234",
                                    "status": "Active"
                                }
                            ]
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
        }
    )
    def get(self):

        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {})
        agent_id = user_info.get("agent_id")
        
        allowed_permissions = {}
        
        acount_type = user_info.get("account_type")
        
        

        # Assign user_id and business_id from the current user
        business_id = str(user_info.get("business_id"))
        
        log_tag = f"[super_superadmin_resource.py][AvailableRoleResource][get][{client_ip}][{business_id}]"

        Log.info(f"{log_tag} initiated get roles {user_info}")
        
        Log.info(f"user_info: {acount_type}")
        try:
            
            if acount_type == 'super_admin':
                allowed_permissions = PERMISSION_FIELDS_FOR_ADMIN_ROLE
                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "permissions": allowed_permissions
                }), HTTP_STATUS_CODES["OK"]
                
            elif agent_id is not None:
                allowed_permissions = PERMISSION_FIELDS_FOR_AGENT_ROLE
                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "permissions": allowed_permissions
                }), HTTP_STATUS_CODES["OK"]
            else:
                # Return the role data as a response
                return prepared_response(False, "BAD_REQUEST", f"You need to be an Admin or Agent")
            
        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the roles.{str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred.{str(e)}")


@blp_system_admin_user.route("/auth/login", methods=["POST"])
class LoginBusinessResource(MethodView):
    # decorators = [
    #     login_ip_limiter(),
    #     login_user_limiter(),
    # ]
    
    @blp_system_admin_user.arguments(LoginSchema, location="form")
    @blp_system_admin_user.response(200, LoginSchema)
    @blp_system_admin_user.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": LoginSchema,  # Assuming you have a LoginSchema to validate the input data
                    "example": {
                        "email": "johndoe@example.com",
                        "password": "SecurePass123"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Login successful, returns an access token",
                "content": {
                    "application/json": {
                        "example": {
                            "access_token": "your_access_token_here",
                            "token_type": "Bearer",
                            "expires_in": 86400  # The token expiration time in seconds (1 day)
                        }
                    }
                }
            },
            400: {
                "description": "Invalid login data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid email or password"
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
                            "message": "Invalid authentication credentials"
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
        }
    )
    def post(self, user_data):
        client_ip = request.remote_addr
        log_tag = '[super_superadmin_resource.py][LoginBusinessResource][post]'
        Log.info(f"{log_tag} [{client_ip}][{user_data['email']}] initiating loging request")
        
        client_ip = request.remote_addr
    
        # Check if x-app-ky header is present and valid
        app_key = request.headers.get('x-app-key')
        server_app_key = os.getenv("X_APP_KEY")
        
        if app_key != server_app_key:
            Log.info(f"[internal_controller.py][get_countries][{client_ip}] invalid x-app-ky header")
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Unauthorized request."
            }
            return jsonify(response), HTTP_STATUS_CODES["UNAUTHORIZED"]
    
        # Check if the user exists based on email
        user = User.get_user_by_email(user_data["email"])
        if user is None:
           Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: login email does not exist")
           return prepared_response(
                False,
                "UNAUTHORIZED",
                "Invalid email or password",
            )
           
        
        fullname = decrypt_data(user["fullname"])
        
        # Check if the user's email is not verified
        if User.email_verification_needed(user_data["email"]):
            Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: email needs verification")
            try:
                base_url = os.getenv("BACK_END_BASE_URL")
                token = secrets.token_urlsafe(32) # Generates a 32-byte URL-safe token 
                reset_url = generate_confirm_email_token(base_url, token)
                
                update_code = User.update_auth_code(user_data["email"], token)
    
                if update_code:
                    Log.info(f"{log_tag} [post]\t reset_url: {reset_url}")
                    send_user_registration_email(user_data["email"], fullname, reset_url)
            except Exception as e:
                Log.info(f"{log_tag} \t An error occurred sending emails: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Email needs verification.",
                "hint": "Verification email has been sent to user"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]


        # Check if the user's credentials are not correct
        if not User.verify_password(user_data["email"], user_data["password"]):
            Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: email and password combination failed")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Invalid email or password",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            
        Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: login info matched")
        
        client_id = decrypt_data(user["client_id"])
        
        business = Business.get_business_by_client_id(client_id)
        if not business: 
            abort(401, message="Your access has been revoked. Contact your administrator")
            
        # Log.info(f"business: {business}")
        
        account_type = business.get("account_type")
        
        decrypted_data = decrypt_data(account_type)

        # when user was not found
        if user is None:
            Log.info(f"{log_tag}[{client_ip}] user not found.") 
            return prepared_response(False, "NOT_FOUND", f"User not found.")
        
        # proceed to create token when user payload was created
        return create_token_response_admin(
            user=user,
            account_type=decrypted_data,
            client_ip=client_ip, 
            log_tag=log_tag, 
        )
        
@blp_system_admin_user.route("/auth/me", methods=["GET"])
class CurrentUserResource(MethodView):
    
    @token_required
    @blp_system_admin_user.response(200)
    @blp_system_admin_user.doc(
        summary="Get current authenticated user",
        description="This endpoint returns the profile information of the currently authenticated user based on their JWT token.",
        responses={
            200: {
                "description": "Successfully retrieved user profile",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "id": "user_id_here",
                                "email": "johndoe@example.com",
                                "fullname": "John Doe",
                                "client_id": "client_id_here",
                                "account_type": "admin",
                                "email_verified": True
                            }
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized - Invalid or missing token",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Missing or invalid authentication token"
                        }
                    }
                }
            },
            404: {
                "description": "User not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "User not found"
                        }
                    }
                }
            }
        }
    )
    def get(self):
        client_ip = request.remote_addr
        log_tag = '[super_superadmin_resource.py][CurrentUserResource][get]'
        
        body = request.get_json(silent=True) or {}
        
        user = g.get("current_user", {}) or {}
        target_business_id = resolve_target_business_id_from_payload(body)

        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")
        
        Log.info(f"{log_tag} [{client_ip}] fetching user profile for user_id: {auth_user__id}")
        
        # Get user from database
        user = User.get_by_id(auth_user__id, target_business_id)
        
        if user is None:
            Log.info(f"{log_tag} [{client_ip}] user not found")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "User not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]
        
        # Decrypt sensitive fields
        client_id = decrypt_data(user["client_id"])
        
        # Get business info
        business = Business.get_business_by_client_id(client_id)
        
        decrypte_full_name = decrypt_data(user.get("fullname"))
        
        business_info = dict()
    
        business_info = {key: safe_decrypt(business.get(key)) for key in BUSINESS_FIELDS}
        
        # Token is for 24 hours
        response = {
            "fullname": decrypte_full_name,
            "admin_id": str(user.get("_id")),
            "business_id": target_business_id,
            "profile": business_info
        }
        
        try:
            role_id = user.get("role") if user.get("role") else None
            
            role = None
            
            if role_id is not None:
                role =  Role.get_by_id(role_id=role_id, business_id=target_business_id, is_logging_in=True)
                
            
            if role is not None:
                # retreive the permissions for the user
                permissions = role.get("permissions")

        except Exception as e:
            Log.info(f"{log_tag} [helpers.py][{client_ip}]: error retreiving permissions for user: {e}")
        
        
        response["account_type"] = account_type

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]) :
            response["permissions"] = {}
        else:
            response["permissions"] = permissions
            
        return jsonify(response), HTTP_STATUS_CODES["OK"]
        
        
@blp_system_admin_user.route("/auth/logout", methods=["POST"])
class LogoutResource(MethodView):
    @token_required
    @logout_rate_limiter("logout")
    @blp_system_admin_user.doc(
        summary="Logout from account",
        description="This endpoint allows a user to logout by invalidating their access token. A valid access token must be provided in the Authorization header.",
        security=[{"BearerAuth": []}],
        responses={
            200: {
                "description": "Logout successful",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Successfully logged out."
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized - Invalid or missing token",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid or expired token."
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
                            "message": "An unexpected error occurred."
                        }
                    }
                }
            }
        }
    )
    def post(self):
        client_ip = request.remote_addr
        auth_header = request.headers.get('Authorization')
        log_tag = '[super_superadmin_resource.py][LogoutResource][post]'

        if not auth_header or not auth_header.startswith('Bearer '):
            return prepared_response(False, "UNAUTHORIZED", f"Authorization token is missing or invalid.")
        
        access_token = auth_header.split(' ')[1]
        
        try:
            # Delete or invalidate the token from database
            token_deleted = Token.delete_token(access_token)

            if token_deleted:
                Log.info(f"{log_tag} [{client_ip}]: token invalidated successfully.")
                return prepared_response(False, "OK", f"Successfully logged out.")
                
            else:
                Log.info(f"{log_tag}[{client_ip}]: token invalidation failed.")
                return prepared_response(False, "UNAUTHORIZED", f"Invalid or expired token.")
                
        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}]: logout error: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
         





