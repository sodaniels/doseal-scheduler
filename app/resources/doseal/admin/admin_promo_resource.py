# app/resources/instntmny/admin_promo_resource.py

import os
import time
from functools import wraps
from datetime import datetime, timedelta

import jwt
import bcrypt
from rq import Queue
from redis import Redis
from flask import current_app, g, jsonify, request
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from pymongo.errors import PyMongoError
from marshmallow import ValidationError

# helper functions
from ....utils.file_upload import upload_file
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
from .admin_business_resource import token_required
from ....utils.logger import Log
from ....constants.service_code import HTTP_STATUS_CODES

# schemas (assumed to exist; **not** defined here)
from ....schemas.doseal.admin.promo_schema import (
    PromoSchema,
    PromoIdQuerySchema,
    PromoUpdateSchema,
    PromosQuerySchema,
    ActivePromoByCategorySchema
)

# model
from ....models.instntmny.promo_model import Promo
from ....models.user_model import User


blp_promo = Blueprint("Promo", __name__, description="Promo Management")

# ------------------------------- /promo ---------------------------------------
@blp_promo.route("/promo", methods=["POST", "GET", "PATCH", "DELETE"])
class PromoResource(MethodView):

    # POST Promo (Create)
    @token_required
    @blp_promo.arguments(PromoSchema, location="form")
    @blp_promo.response(201, PromoSchema)
    @blp_promo.doc(
        summary="Create a new promo",
        description="""
            Create a new promo for the authenticated business.
            Requires Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": PromoSchema,
                    "example": {
                        "promo_name": "Welcome Bonus",
                        "promo_amount": 10.0,
                        "promo_category": "Subscriber",
                        "promo_start_date": "2025-12-01T00:00:00",
                        "promo_end_date": "2026-01-31T23:59:59",
                        "promo_limit": 100.0,
                        "promo_threshold": "txn_count>=1",
                        "promo_status": True
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Promo created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Promo created successfully",
                            "status_code": 201,
                            "success": True
                        }
                    }
                }
            },
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            500: {"description": "Internal Server Error"},
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f"[admin_promo_resource][PromoResource][post][{client_ip}]"

        # attach business/user from token context
        business_id = user_info.get("business_id")
        item_data["business_id"] = business_id
        item_data["user__id"] = user_info.get("_id")
        item_data["user_id"] = user_info.get("user_id")
        item_data["created_by"] = user_info.get("_id")

        # Duplicate check on promo name (model/BaseModel should handle enc/hash internally)
        Log.info(f"{log_tag} checking if promo already exists")
        if Promo.check_item_exists_business_id(
            item_data["business_id"],
            key="promo_name",
            value=item_data.get("promo_name"),
        ):
            return prepared_response(False, "CONFLICT", "Promo with this name already exists.")

        Log.info(f"{log_tag} creating promo with payload")

        promo = Promo(**item_data)

        try:
            Log.info(f"{log_tag} committing promo transaction")
            start_time = time.time()
            promo_id = promo.save()
            end_time = time.time()
            Log.info(f"{log_tag}[{promo_id}] completed in {end_time - start_time:.2f} sec")

            if promo_id:
                
                # update corresponding promo_category eg. Subscriber's users collection with promo_id
                try:
                    create_promos = Promo._upsert_promo_for_subscribers(
                        business_id, 
                        promo_id, 
                        item_data["promo_amount"],
                        item_data["promo_limit"],
                    )
                    
                    Log.info(f"{log_tag} create_promos: {create_promos}")
                    
                    
                except Exception as e:
                    Log.info(f"{log_tag}: error retreiving for system user: {e}")
                
                return prepared_response(True, "CREATED", "Promo created successfully.")

            return prepared_response(False, "BAD_REQUEST", "Failed to create promo")

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"DB error while creating promo. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error. {str(e)}")

    # GET Promo (Retrieve by promo_id)
    @token_required
    @blp_promo.arguments(PromoIdQuerySchema, location="query")
    @blp_promo.response(200, PromoIdQuerySchema)
    @blp_promo.doc(
        summary="Retrieve a promo by promo_id",
        description="Retrieve a single promo by its ID. Requires Bearer token.",
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Promo retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "_id": "66f0b938d4d8c24fa0804d62",
                                "promo_name": "Welcome Bonus",
                                "promo_amount": 10.0,
                                "promo_category": "Subscriber",
                                "promo_start_date": "2025-12-01T00:00:00",
                                "promo_end_date": "2026-01-31T23:59:59",
                                "promo_limit": 100.0,
                                "promo_threshold": "txn_count>=1",
                                "promo_status": True
                            }
                        }
                    }
                }
            },
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            404: {"description": "Promo not found"},
            500: {"description": "Internal Server Error"},
        }
    )
    def get(self, query_data):
        promo_id = query_data.get("promo_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[admin_promo_resource][PromoResource][get][{client_ip}][{business_id}][{promo_id}]"

        Log.info(f"{log_tag} retrieving promo")

        if not promo_id:
            return prepared_response(False, "BAD_REQUEST", "promo_id must be provided.")

        try:
            start_time = time.time()
            promo = Promo.get_by_id(business_id=business_id, promo_id=promo_id)
            duration = time.time() - start_time
            Log.info(f"{log_tag} completed in {duration:.2f}s")

            if not promo:
                return prepared_response(False, "NOT_FOUND", "Promo not found")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": promo
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"DB error while retrieving promo. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error. {str(e)}")

    # PATCH Promo (Update)
    @token_required
    @blp_promo.arguments(PromoUpdateSchema, location="form")
    @blp_promo.response(200, PromoUpdateSchema)
    @blp_promo.doc(
        summary="Update an existing promo",
        description="""
            Update an existing promo by providing `promo_id` and fields to update.
            Requires Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": PromoUpdateSchema,
                    "example": {
                        "promo_id": "66f0b938d4d8c24fa0804d62",
                        "promo_name": "Welcome Bonus Extended",
                        "promo_amount": 15.0,
                        "promo_end_date": "2026-02-28T23:59:59",
                        "promo_status": True
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Promo updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Promo updated successfully"
                        }
                    }
                }
            },
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            404: {"description": "Promo not found"},
            500: {"description": "Internal Server Error"},
        },
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        promo_id = item_data.get("promo_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        item_data["business_id"] = business_id  # keep context-consistent

        log_tag = f"[admin_promo_resource][PromoResource][patch][{client_ip}][{business_id}][{promo_id}]"
        Log.info(f"{log_tag} updating promo")

        # Check existence
        promo = Promo.get_by_id(business_id=business_id, promo_id=promo_id)
        if not promo:
            Log.info(f"{log_tag} promo not found")
            return prepared_response(False, "NOT_FOUND", "Promo not found.")

        try:
            start_time = time.time()
            item_data.pop("promo_id", None)  # do not pass id inside update data
            item_data["business_id"] = business_id

            update_ok = Promo.update(promo_id, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag} update ok in {duration:.2f}s")
                return prepared_response(True, "OK", "Promo updated successfully.")
            else:
                Log.info(f"{log_tag} update failed")
                return prepared_response(False, "BAD_REQUEST", "Failed to update promo.")

        except PyMongoError as e:
            Log.info(f"{log_tag} DB error {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"DB error while updating promo. {str(e)}")
        except Exception as e:
            Log.info(f"{log_tag} Unexpected error {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error. {str(e)}")

    # DELETE Promo
    @token_required
    @blp_promo.arguments(PromoIdQuerySchema, location="query")
    @blp_promo.response(200)
    @blp_promo.doc(
        summary="Delete a promo by promo_id",
        description="Delete a promo by ID. Requires Bearer token.",
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Promo deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Promo deleted successfully"
                        }
                    }
                }
            },
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            404: {"description": "Promo not found"},
            500: {"description": "Internal Server Error"},
        }
    )
    def delete(self, query_data):
        promo_id = query_data.get("promo_id")

        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))

        client_ip = request.remote_addr
        log_tag = f"[admin_promo_resource][PromoResource][delete][{business_id}][{client_ip}][{promo_id}]"
        Log.info(f"{log_tag} initiated delete promo")

        if not promo_id:
            return prepared_response(False, "BAD_REQUEST", "promo_id must be provided.")

        promo = Promo.get_by_id(promo_id=promo_id, business_id=business_id)
        if not promo:
            Log.info(f"{log_tag} promo not found")
            return prepared_response(False, "NOT_FOUND", "Promo not found.")

        delete_success = Promo.delete(promo_id, business_id=business_id)

        if delete_success:
            Log.info(f"{log_tag} promo deleted successfully")
            return prepared_response(True, "OK", "Promo deleted successfully.")
        else:
            Log.info(f"{log_tag} failed to delete promo")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to delete promo.")


# ------------------------------- /promos --------------------------------------
@blp_promo.route("/promos", methods=["GET"])
class PromosResource(MethodView):
    @token_required
    @blp_promo.arguments(PromosQuerySchema, location="query")
    @blp_promo.response(200, PromosQuerySchema)
    @blp_promo.doc(
        summary="List promos for current business",
        description="""
            List promos for the authenticated business with pagination and optional filters.
            Requires Bearer token.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Promos retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "promos": [
                                    {
                                        "_id": "66f0b938d4d8c24fa0804d62",
                                        "promo_name": "Welcome Bonus",
                                        "promo_amount": 10.0,
                                        "promo_category": "Subscriber",
                                        "promo_start_date": "2025-12-01T00:00:00",
                                        "promo_end_date": "2026-01-31T23:59:59",
                                        "promo_limit": 100.0,
                                        "promo_threshold": "txn_count>=1",
                                        "promo_status": True
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
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            500: {"description": "Internal Server Error"},
        }
    )
    def get(self, query):
        """
        Retrieve paginated promos for the user's business.
        Optional filters:
          - promo_status: bool
          - promo_category: "Subscriber" | "Agent"
        """
        client_ip = request.remote_addr
        log_tag = f"[admin_promo_resource][PromosResource][get][{client_ip}]"

        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))

        page = query.get("page")
        per_page = query.get("per_page")
        promo_status = query.get("promo_status", None)
        promo_category = query.get("promo_category", None)

        Log.info(f"{log_tag} listing promos")

        try:
            promos = Promo.get_all(
                business_id=business_id,
                page=page,
                per_page=per_page,
                promo_status=promo_status,
                promo_category=promo_category,
            )

            if not promos:
                return prepared_response(False, "NOT_FOUND", "Promos not found")

            Log.info(f"{log_tag} promos found")
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": promos
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"DB error while retrieving promos. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error. {str(e)}")

# ------------------------------- /promos --------------------------------------
@blp_promo.route("/active-promo-by-category", methods=["GET"])
class ActivePromoByCategoryResource(MethodView):
    @token_required
    @blp_promo.arguments(ActivePromoByCategorySchema, location="query")
    @blp_promo.response(200, ActivePromoByCategorySchema)
    @blp_promo.doc(
        summary="Retrieve a promo by promo_id",
        description="Retrieve a single promo by its ID. Requires Bearer token.",
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Promo retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "_id": "66f0b938d4d8c24fa0804d62",
                                "promo_name": "Welcome Bonus",
                                "promo_amount": 10.0,
                                "promo_category": "Subscriber",
                                "promo_start_date": "2025-12-01T00:00:00",
                                "promo_end_date": "2026-01-31T23:59:59",
                                "promo_limit": 100.0,
                                "promo_threshold": "txn_count>=1",
                                "promo_status": True
                            }
                        }
                    }
                }
            },
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            404: {"description": "Promo not found"},
            500: {"description": "Internal Server Error"},
        }
    )
    def get(self, query_data):
        promo_category = query_data.get("promo_category")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[admin_promo_resource][ActivePromoByCategoryResource][get][{client_ip}][{business_id}][{promo_category}]"

        Log.info(f"{log_tag} retrieving promo")
        
        try:
            start_time = time.time()
            promo = Promo.get_active_one_by_category(business_id=business_id, promo_category=promo_category)
            duration = time.time() - start_time
            Log.info(f"{log_tag} completed in {duration:.2f}s")

            if not promo:
                return prepared_response(False, "NOT_FOUND", "Promo not found")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": promo
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"DB error while retrieving promo. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error. {str(e)}")
