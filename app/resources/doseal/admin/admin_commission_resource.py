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
    upload_file, 
)
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
#helper functions

from .admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....constants.service_code import HTTP_STATUS_CODES

# schemas
from ....schemas.doseal.commission_schema import (
    CommissionSchema, CommissionIdQuerySchema, CommissionUpdateSchema, 
    CommissionIdQuerySchema, CommissionsSchema
)
# models
from app.models.instntmny.commission_model import Commission


blp_commission = Blueprint("Commission Management", __name__,  description="Commission Management")

# -----------------------------COMMISSION-----------------------------------
@blp_commission.route("/commission", methods=["POST", "GET", "PATCH", "DELETE"])
class CommissionResource(MethodView):

    #POST Commission (Commission by user__id)
    @token_required
    @blp_commission.arguments(CommissionSchema, location="json")
    @blp_commission.response(201, CommissionSchema)
    @blp_commission.doc(
        summary="Create a new commission",
        description="This endpoint allows an agent to create a new commission.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": CommissionSchema,
                    "example": {
                        "commission": 5.0
                    }
                }
            }
        },
        responses={
            201: {
                "description": "Commission created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Commission created successfully",
                            "status_code": 201,
                            "success": True
                        }
                    }
                }
            },
            409: {
                "description": "Commission with this value already exists",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Commission with this value already exists.",
                            "status_code": 409,
                            "success": False
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
                            "message": "Invalid commission value"
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
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new notice."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f"[admin_commission_resource][CommissionResource][post][{client_ip}]"

        # Attach business and user IDs from the current user context
        item_data["business_id"] = user_info.get("business_id")
        item_data["user__id"] = user_info.get("_id")
        item_data["user_id"] = user_info.get("user_id")
        item_data["created_by"] = user_info.get("_id")
        
        commission = str(item_data.get("commission"))
        name = item_data.get("name")
        
        # Check for duplicate commission based on the value
        Log.info(f"{log_tag} checking if commission already exists")
        if Commission.check_item_exists_business_id(item_data["business_id"], key="commission", value=commission):
            return prepared_response(False, "CONFLICT", f"Commission with this value already exists.")
        
        # Check for duplicate commission based on the name
        Log.info(f"{log_tag} checking if commission already exists")
        if Commission.check_item_exists_business_id(item_data["business_id"], key="name", value=name):
            return prepared_response(False, "CONFLICT", f"Commission with this name exists.")

        item_data["commission"] = commission
        
        # Create a new commission instance and save it
        commission = Commission(**item_data)

        try:
            Log.info(f"{log_tag}[committing new commission]")
            start_time = time.time()
            commission_id = commission.save()
            end_time = time.time()

            Log.info(f"{log_tag} completed in {end_time - start_time:.2f} sec")

            if commission_id:
                return prepared_response(True, "CREATED", f"Commission created successfully.")

            return prepared_response(False, "BAD_REQUEST", f"Failed to create commission")

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while creating the notice. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

    # GET Commission (Retrieve a commission by commission_id)
    @token_required
    @blp_commission.arguments(CommissionIdQuerySchema, location="query")
    @blp_commission.response(200, CommissionIdQuerySchema)
    @blp_commission.doc(
        summary="Retrieve a commission by commission_id",
        description="""
            This endpoint allows an agent to retrieve a commission based on the `commission_id`
            passed in the query parameters. A valid Bearer token is required.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Commission retrieved successfully",
                "content": {
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "commission_id must be provided."
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
                "description": "Commission not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Commission not found"
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
    def get(self, commission_data):
        commission_id = commission_data.get("commission_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[commission_resource.py][CommissionResource][get][{client_ip}][{business_id}][{commission_id}]"

        Log.info(f"{log_tag} retrieving commission")

        if not commission_id:
            return prepared_response(False, "BAD_REQUEST", "commission_id must be provided.")

        # Validate ObjectId format before querying
        from bson import ObjectId
        if not ObjectId.is_valid(commission_id):
            return prepared_response(False, "BAD_REQUEST", "Invalid commission_id format.")

        try:
            start_time = time.time()
            commission = Commission.get_by_id(
                business_id=business_id,
                commission_id=commission_id
            )
            duration = time.time() - start_time

            Log.info(f"{log_tag} retrieval completed in {duration:.2f} seconds")

            if not commission:
                return prepared_response(False, "NOT_FOUND", "Commission not found")

            Log.info(f"{log_tag} commission found")
            # Return the notice data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": commission
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error: {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error: {str(e)}")


    # PATCH Commission (Update a commission by commission_id)
    @token_required
    @blp_commission.arguments(CommissionUpdateSchema, location="json")
    @blp_commission.arguments(CommissionUpdateSchema)
    @blp_commission.doc(
        summary="Update a commission by commission_id",
        description="""
            This endpoint allows you to update a commission's details by providing the `commission_id`
            as a query parameter and the new commission data in the JSON body.
            Requires a valid Bearer token.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Commission updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Commission updated successfully",
                            "data": {
                                "commission_id": "64b7f9f2c0d8a1e0b3c45678",
                                "commission": 7.5,
                                "created_at": "2025-07-28T12:00:00",
                                "updated_at": "2025-08-10T15:00:00"
                            }
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
                            "message": "commission_id must be provided."
                        }
                    }
                }
            },
            404: {
                "description": "Commission not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Commission not found"
                        }
                    }
                }
            },
            409: {
                "description": "Duplicate commission value",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 409,
                            "message": "Commission with this value already exists."
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
                            "message": "An unexpected error occurred"
                        }
                    }
                }
            }
        }
    )
    def patch(self, query_data, body_data):
        commission_id = query_data.get("commission_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[commission_resource.py][CommissionResource][patch][{client_ip}][{business_id}][{commission_id}]"

        Log.info(f"{log_tag} updating commission")

        try:
            # Check if commission exists
            existing_commission = Commission.get_by_id(business_id, commission_id)
            if not existing_commission:
                return prepared_response(False, "NOT_FOUND", "Commission not found")

            # Check for duplicate commission value
            if "commission" in body_data:
                duplicate = Commission.get_by_id(business_id, body_data["commission"])
                if duplicate and str(duplicate["_id"]) != commission_id:
                    return prepared_response(False, "CONFLICT", "Commission with this value already exists.")

            # Perform update
            update_success = Commission.update(
                business_id=business_id,
                commission_id=commission_id,
                updates=body_data
            )

            if update_success:
                return prepared_response(True, "OK", "Commission updated successfully")
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update commission.")

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error: {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error: {str(e)}")


    # DELETE Commission (Delete an existing commission)
    @token_required
    @blp_commission.arguments(CommissionIdQuerySchema, location="query")
    @blp_commission.response(200)
    @blp_commission.doc(
        summary="Delete a commission by commission_id",
        description="""
            This endpoint allows you to delete a commission by providing `commission_id` in the query parameters.
            - **DELETE**: Delete a commission by providing `commission_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Commission deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Commission deleted successfully"
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
                            "message": "commission_id must be provided."
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
                "description": "Commission not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Commission not found"
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
    def delete(self, commission_data):
        commission_id = commission_data.get("commission_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[commission_resource.py][CommissionResource][delete][{client_ip}][{business_id}][{commission_id}]"

        Log.info(f"{log_tag} deleting commission")

        if not commission_id:
            return prepared_response(False, "BAD_REQUEST", "commission_id must be provided.")

        try:
            # Check if commission exists
            commission = Commission.get_by_id(business_id, commission_id)
            if not commission:
                return prepared_response(False, "NOT_FOUND", "Commission not found")

            # Perform deletion
            delete_success = Commission.delete(commission_id=commission_id, business_id=business_id)
            if delete_success:
                return prepared_response(True, "OK", "Commission deleted successfully")
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to delete commission.")

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error: {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error: {str(e)}")

   
@blp_commission.route("/commissions", methods=["GET"])
class CommissionsResource(MethodView):
    @token_required
    @blp_commission.arguments(CommissionsSchema, location="query")
    @blp_commission.response(200, CommissionsSchema)
    @blp_commission.doc(
        summary="Retrieve commissions by business_id",
        description="""
            This endpoint allows you to retrieve commissions based on the `business_id` in the query parameters.
            - **GET**: Retrieve commissions by providing `business_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],
        responses={
            200: {
                "description": "Commissions retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "commission_id": "66a6b938d4d8c24fa0804d62",
                                    "commission": 5.0,
                                    "created_at": "2025-07-28T12:00:00",
                                    "updated_at": "2025-07-28T12:00:00"
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
    def get(self, item_data):
        """Handle GET request to retrieve commissions by business_id."""
        client_ip = request.remote_addr
        log_tag = f"[commission_resource.py][CommissionsResource][get][{client_ip}]"

        # Get the current user's business_id
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        page = item_data.get("page", None)
        per_page = item_data.get("per_page", None)

        Log.info(f"{log_tag} initiated get commissions")

        try:
            # Retrieve commissions for the given business_id
            commissions = Commission.get_all(business_id=business_id, page=page, per_page=per_page)

            if not commissions:
                return prepared_response(False, "NOT_FOUND", "Commissions not found")

            Log.info(f"{log_tag} commissions data found")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": commissions
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving commissions. {str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")





