import bcrypt
import jwt
import os
import time
import secrets

from functools import wraps
from redis import Redis
from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue

from datetime import datetime, timedelta, timezone
#helper functions
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
#helper functions

from ....services.reminder_inspect import list_jobs_window
from .admin_business_resource import token_required
from ....utils.logger import Log 
from ....constants.service_code import HTTP_STATUS_CODES
from ....services.reminder_queue import schedule_reminder_jobs

# schemas
from ....schemas.doseal.payable_schema import (
    PayableSchema, PayableWindowSchema, PayableIDQuerySchema, 
    PayableNextJobsSchema, PayableUpdateSchema
)

# models
from ....models.instntmny.payable_model import Payable


from ....services.reminder_inspect import (
    list_next_due, list_jobs_window, list_jobs_for_payable, 
    list_jobs_from_mongo_mirror, hydrate_jobs_with_payables
)

blp_payable = Blueprint("Payable Management", __name__,  description="Payable Management")

# --- small shared parser ---
def _parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        # allow trailing Z; normalize to aware UTC
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


# -----------------------------PAYABLE-----------------------------------
# POST Payable (Create a new Payable)
@blp_payable.route("/payable", methods=["POST", "GET", "PATCH", "DELETE"])
class PayableResource(MethodView):
    #POST payable
    @token_required
    @blp_payable.arguments(PayableSchema, location="form")
    @blp_payable.response(201, PayableSchema)
    @blp_payable.doc(
        summary="Create a new payable",
        description="""
            This endpoint allows you to create a new payable. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a scheduled payable by providing details such as name, reference, currency, amount, due date,
            and reminder offsets (days before due date).
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": PayableSchema,
                    "example": {
                        "name": "September Rent",
                        "reference": "INV-2025-0091",
                        "currency": "GHS",
                        "amount": 12500.00,
                        "due_at": "2025-09-25T12:00:00Z",
                        "reminder_offsets_days": [7, 2],
                        "status": "pending"
                    }
                }
            }
        },
        responses={
            201: {
                "description": "Payable created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Payable created successfully",
                            "status_code": 201,
                            "success": True
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
                "description": "Duplicate payable for this business",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 409,
                            "message": "A payable with this reference already exists."
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
    def post(self, item_data):
        """Handle the POST request to create a new payable."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[payable_resource.py][PayableResource][post]'
        payable_id = None

        Log.info(f"user_info: {user_info}")

        # Attach context
        user_id = user_info.get("_id")
        business_id = user_info.get("business_id")
        item_data["created_by"] = user_id
        item_data["business_id"] = business_id

        name = item_data.get("name")
        reference = item_data.get("reference")

        # --------- Duplicate checks (per business) ----------
        Log.info(f"{log_tag}[{client_ip}] checking if payable (reference) already exists")
        if Payable.check_item_exists_business_id(business_id, key="reference", value=reference):
            return prepared_response(False, "CONFLICT", "A payable with this reference already exists.")

        Log.info(f"{log_tag}[{client_ip}] checking if payable (name) already exists")
        if Payable.check_item_exists_business_id(business_id, key="name", value=name):
            return prepared_response(False, "CONFLICT", "A payable with this name already exists.")

        # --------- Parse/normalize incoming form fields if necessary ----------
        # Marshmallow with location="form" should coerce types,
        # but if your stack doesn't, ensure due_at is datetime and offsets are ints.
        try:
            due_at_val = item_data.get("due_at")  # already a datetime if schema parsed it
            if isinstance(due_at_val, str):
                # Robust ISO8601 handling (supports trailing 'Z')
                due_at_val = datetime.fromisoformat(due_at_val.replace("Z", "+00:00"))
            item_data["due_at"] = due_at_val

            offs = item_data.get("reminder_offsets_days") or []
            if isinstance(offs, str):
                # Support comma-separated form input like "7,2,1"
                offs = [int(x.strip()) for x in offs.split(",") if x.strip() != ""]
            item_data["reminder_offsets_days"] = list({int(x) for x in offs})

            # amount normalization
            if isinstance(item_data.get("amount"), str):
                item_data["amount"] = float(item_data["amount"])

            # default status
            if not item_data.get("status"):
                item_data["status"] = "pending"

        except Exception as e:
            return prepared_response(False, "BAD_REQUEST", f"Invalid input data: {str(e)}")

        # --------- Create and persist ----------
        try:
            Log.info(f"{log_tag}[{client_ip}] committing payable")
            start_time = time.time()
            

            payable = Payable(**item_data)

            try:
                payable_id = payable.save()
            except Exception as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

            end_time = time.time()
            duration = end_time - start_time
            Log.info(f"{log_tag}[{client_ip}] committing payable completed in {duration:.2f} seconds")

            if payable_id is not None:
                Log.info(f"{log_tag}[{client_ip}] committed payable")
                
                schedule_reminder_jobs(str(payable_id), payable.due_at, payable.reminder_offsets_days) 
                
                return prepared_response(True, "CREATED", "Payable created successfully.")
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to create payable.")

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{payable_id}] error committing payable: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{payable_id}] error committing payable: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

    #PUT payable
    @token_required
    @blp_payable.arguments(PayableUpdateSchema, location="form")
    @blp_payable.response(200, PayableUpdateSchema)
    @blp_payable.doc(
        summary="Create a new payable",
        description="""
            This endpoint allows you to create a new payable. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a scheduled payable by providing details such as name, reference, currency, amount, due date,
            and reminder offsets (days before due date).
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": PayableSchema,
                    "example": {
                        "name": "September Rent",
                        "reference": "INV-2025-0091",
                        "currency": "GHS",
                        "amount": 12500.00,
                        "due_at": "2025-09-25T12:00:00Z",
                        "reminder_offsets_days": [7, 2],
                        "status": "pending"
                    }
                }
            }
        },
        responses={
            201: {
                "description": "Payable created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Payable created successfully",
                            "status_code": 201,
                            "success": True
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
                "description": "Duplicate payable for this business",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 409,
                            "message": "A payable with this reference already exists."
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
    def patch(self, item_data):
        """Handle the PATCH request to create a new payable."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[payable_resource.py][PayableResource][post]'
        payable_id = None

        # Attach context
        user_id = user_info.get("_id")
        business_id = user_info.get("business_id")
        item_data["created_by"] = user_id

        # --------- Parse/normalize incoming form fields if necessary ----------
        # Marshmallow with location="form" should coerce types,
        # but if your stack doesn't, ensure due_at is datetime and offsets are ints.
        try:
            due_at_val = item_data.get("due_at")  # already a datetime if schema parsed it
            if isinstance(due_at_val, str):
                # Robust ISO8601 handling (supports trailing 'Z')
                due_at_val = datetime.fromisoformat(due_at_val.replace("Z", "+00:00"))
            item_data["due_at"] = due_at_val

            offs = item_data.get("reminder_offsets_days") or []
            if isinstance(offs, str):
                # Support comma-separated form input like "7,2,1"
                offs = [int(x.strip()) for x in offs.split(",") if x.strip() != ""]
            item_data["reminder_offsets_days"] = list({int(x) for x in offs})

            # amount normalization
            if isinstance(item_data.get("amount"), str):
                item_data["amount"] = float(item_data["amount"])

            # default status
            if not item_data.get("status"):
                item_data["status"] = "pending"

        except Exception as e:
            return prepared_response(False, "BAD_REQUEST", f"Invalid input data: {str(e)}")

        # --------- Create and persist ----------
        try:
            Log.info(f"{log_tag}[{client_ip}] updating payable")
            start_time = time.time()
            
            item_data.pop("payable_id", {})

            try:
                payable = Payable.update(payable_id=payable_id, business_id=business_id, **item_data)
                
                Log.info(f"payable: {payable}")
                 
                end_time = time.time()
                
                duration = end_time - start_time
                Log.info(f"{log_tag}[{client_ip}] updating payable in {duration:.2f} seconds")

                
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] An unexpected error occurred. {str(e)}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")


        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{payable_id}] error committing payable: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{payable_id}] error committing payable: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
    
    # PATCH Notice (Update an existing Notice)
    @token_required
    @blp_payable.arguments(PayableUpdateSchema, location="form")
    @blp_payable.response(200, PayableUpdateSchema)
    @blp_payable.doc(
        summary="Update an existing notice",
        description="""
            This endpoint allows you to update an existing notice by providing `notice_id` in the request body.
            - **PATCH**: Update an existing notice by providing details such as title, excerpt, and message.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": PayableUpdateSchema,
                    "example": {
                        "notice_id": "60a6b938d4d8c24fa0804d62",
                        "title": "Updated Announcement",
                        "excerpt": "This is an updated announcement for our users.",
                        "message": "Here is the full updated message of the announcement."
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Notice updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Notice updated successfully"
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
                "description": "Notice not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Notice not found"
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
    def patch(self, item_data):
        """Handle the PATCH request to update an existing notice."""
        payable_id = item_data.get("payable_id") 

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        item_data["user_id"] = user_info.get("user_id")
        business_id = user_info.get("business_id")

        log_tag = f"[admin_payable_resource.py][PayableResource][put][{client_ip}][{business_id}][{payable_id}]"

        Log.info(f"[{log_tag}] updating notice")

        # Check if the Payable exists based on payable_id
        payable = Payable.get_by_id_and_business_id(payable_id=payable_id, business_id=business_id)

        if not payable:
            Log.info(f"[{log_tag}][{payable_id}] Payable not found.")
            return prepared_response(False, "NOT_FOUND", f"Payable not found.")

        # Attempt to update the payable data
        try:
            start_time = time.time()

            item_data.pop("payable_id", None)  # Remove the notice_id from the update data

            # Update the notice with the new data
            update = Payable.update(payable_id, business_id, **item_data)

            end_time = time.time()
            duration = end_time - start_time

            if update:
                Log.info(f"{log_tag} update: {update}")
                Log.info(f"[{log_tag}][{payable_id}] updating payble completed in {duration:.2f} seconds")
                
                return prepared_response(True, "OK", f"Payable updated successfully.")
            else:
                Log.info(f"[{log_tag}][{payable_id}] Failed to update payble.")
                return prepared_response(False, "BAD_REQUEST", f"Failed to update payble.")
        except PyMongoError as e:
            Log.info(f"[{log_tag}][{payable_id}] An unexpected error occurred while updating the payble. {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while updating the payble. {str(e)}")
        except Exception as e:
            Log.info(f"[{log_tag}][{payable_id}] An unexpected error occurred. {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")


    #DELETE payable
    @token_required
    @blp_payable.arguments(PayableIDQuerySchema, location="query")
    @blp_payable.response(200, PayableIDQuerySchema)
    @blp_payable.doc(
        summary="Delete a notice by notice_id",
        description="""
            This endpoint allows you to delete a notice by providing `notice_id` in the query parameters.
            - **DELETE**: Delete a notice by providing `notice_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Notice deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Notice deleted successfully"
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
                "description": "Notice not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Notice not found"
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
    def delete(self, item_data):
        payable_id = item_data.get("payable_id")

        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        client_ip = request.remote_addr
        log_tag = f"[admin_payable_resource.py][PayableDeleteResource][delete][{business_id}][{client_ip}][{payable_id}]"

        Log.info(f"[{log_tag}] initiated delete notice")

        # Retrieve the payable using its payable_id
        payable = Payable.get_by_id_and_business_id(payable_id=payable_id, business_id=business_id)

        if not payable:
            Log.info(f"{log_tag} notice not found")
            return prepared_response(False, "NOT_FOUND", f"Payable not found.")

        # Call the delete method from the NoticeBoard model
        delete_success = Payable.delete(payable_id=payable_id, business_id=business_id)

        if delete_success:
            Log.info(f"{log_tag} Payable deleted successfully")
            return prepared_response(True, "OK", f"Payable deleted successfully.")
        else:
            Log.info(f"{log_tag} failed to delete Payable")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to delete Payable.")


@blp_payable.route("/payables-jobs-next", methods=["GET"])
class PayableJobsWindowResource(MethodView):
    
    @blp_payable.arguments(PayableNextJobsSchema, location="query")
    @blp_payable.response(200, PayableNextJobsSchema)
    @token_required
    @blp_payable.doc(
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
        """
        GET /api/payables-jobs-next?limit=100
        Returns the next N jobs by ETA from Redis.
        """
        
        try:
            limit = int(item_data.get("limit", 100))
        except ValueError:
            return jsonify({"success": False, "status_code": 400, "message": "limit must be an integer"}), 400

        # optional: small grace to ignore tiny clock skews
        grace_sec = int(request.args.get("grace_sec", 0))
        only_future = (request.args.get("only_future", "true").lower() in ("1", "true", "yes"))
        jobs = None
        
            
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        
        log_tag = f"[admin_payable_resource.py][PayableJobsNextResource][get][{business_id}]" 

        Log.info(f"{log_tag} retrieving next N jobs")
        
        try:
            limit = int(request.args.get("limit", 100))
        except ValueError:
            return jsonify({"message": "limit must be an integer"}), 400
        
        
        include_payable = (request.args.get("include_payable", "true").lower() in ("1", "true", "yes"))
        only_future = (request.args.get("only_future", "true").lower() in ("1", "true", "yes"))
        
        
        if only_future:
            now = datetime.now(timezone.utc)
            # subtract grace if provided
            start_dt = now - timedelta(seconds=grace_sec)
            jobs = list_jobs_window(start_dt, None, limit=limit)
        else:
            jobs = list_next_due(limit=limit)               
            
        Log.info(f"jobs: {jobs}")
        
        if include_payable and jobs:
            jobs = hydrate_jobs_with_payables(jobs)
            
        return jsonify({
            "success": True,
            "satus_code": 200,
            "count": len(jobs), 
            "jobs": jobs
        })




@blp_payable.route("/payables-jobs-window", methods=["GET"])
class ListJobsWindowResource(MethodView):
    @token_required
    @blp_payable.doc(
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
    @blp_payable.arguments(PayableWindowSchema, location="query")
    @blp_payable.response(201, PayableWindowSchema)
    def get(self, item_data):
        """
        GET /api/payables-jobs-window?start_date=2025-09-01T00:00:00Z&end_date=2025-09-07T23:59:59Z&limit=500
        Either 'start_date' or 'end_date' (or both) must be provided (ISO 8601).
        """
        start_dt = _parse_iso(item_data.get("start_date"))
        end_dt = _parse_iso(item_data.get("end_date"))

        if start_dt is None and end_dt is None:
            return jsonify({"message": "Provide at least 'start_date' or 'end_date' (ISO 8601)."}), 400
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        
        log_tag = f"[admin_payable_resource.py][ListJobsWindowResource][get][{business_id}]" 

        Log.info(f"{log_tag} retrieving payable jobs using query params")
        try:
            limit = int(request.args.get("limit", 500))
        except ValueError:
            return jsonify({"message": "limit must be an integer"}), 400

        jobs = list_jobs_window(start_dt, end_dt, limit=limit)
        
        include_payable = (request.args.get("include_payable", "true").lower() in ("1", "true", "yes"))

        
        if include_payable and jobs:
            jobs = hydrate_jobs_with_payables(jobs)
        
        return jsonify({
            "success": True,
            "satus_code": 200,
            "count": len(jobs), 
            "jobs": jobs
        })


@blp_payable.route("/payable-job", methods=["GET"])
class ListJobByPayableIDResource(MethodView):
    @token_required
    @blp_payable.doc(
        summary="Retrieve scheduled reminder jobs for a specific payable",
        description="""
            Returns all queued reminder jobs for the given `payable_id` (from Redis).
            Optional query params:
              - include_payable=(true|false)  default: true  (attach payable fields from Mongo)
        """,
        security=[{"Bearer": []}],
        responses={
            200: {"description": "Jobs retrieved successfully"},
            400: {"description": "Invalid request data"},
            401: {"description": "Unauthorized request"},
            500: {"description": "Internal Server Error"},
        },
    )
    @blp_payable.arguments(PayableIDQuerySchema, location="query")
    @blp_payable.response(200)
    def get(self, item_data):
        """
        GET /api/payable-job?payable_id=<PAYABLE_ID>&include_payable=true
        """
        # ✅ get the payable_id as a string (DO NOT parse as datetime)
        payable_id = item_data.get("payable_id")
        if not payable_id:
            return jsonify({"success": False, "status_code": 400, "message": "payable_id is required"}), 400

        include_payable = (request.args.get("include_payable", "true").lower() in ("1", "true", "yes"))

        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[admin_payable_resource.py][ListJobByPayableIDResource][get][{business_id}][{payable_id}]"
        Log.info(f"{log_tag} retrieving payable jobs")

        try:
            # pulls from Redis set 'sched:jobs_by_payable:{payable_id}' and joins ETA from ZSET
            jobs = list_jobs_for_payable(payable_id)
        except Exception as e:
            Log.info(f"{log_tag} error retrieving jobs: {e}")
            return jsonify({"success": False, "status_code": 500, "message": "Failed to retrieve jobs"}), 500

        include_payable = (request.args.get("include_payable", "true").lower() in ("1", "true", "yes"))
        
        
        if include_payable and jobs:
            jobs = hydrate_jobs_with_payables(jobs)

        return jsonify({
            "success": True,
            "status_code": 200,
            "count": len(jobs),
            "jobs": jobs
        })


@blp_payable.route("/payables", methods=["GET"])
class ListJobByPayableIDResource(MethodView):
    @token_required
    @blp_payable.doc(
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
    def get(self):
        """
        GET /api/payables/jobs/mongo?business_id=<optional>
        Returns mirrored 'scheduled_jobs' from Mongo for diagnostics/UI.
        Redis is still the source of truth for execution.
        """
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        
        log_tag = f"[admin_payable_resource.py][ListJobByPayableIDResource][get][{business_id}]" 

        Log.info(f"{log_tag} retrieving payable jobs using query params")
        try:
            jobs = list_jobs_from_mongo_mirror(business_id=business_id)
        except Exception as e:
            Log.info(f"{log_tag} retrieving payable failed")
            
        include_payable = (request.args.get("include_payable", "true").lower() in ("1", "true", "yes"))
        
        if include_payable and jobs:
            jobs = hydrate_jobs_with_payables(jobs)

        return jsonify({
            "success": True,
            "satus_code": 200,
            "count": len(jobs), 
            "jobs": jobs
        })














      










