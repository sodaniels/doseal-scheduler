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
from ....utils.json_response import prepared_response
from ....utils.helpers import validate_and_format_phone_number
from rq import Queue

from datetime import datetime, timedelta
#helper functions
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.file_upload import (
    upload_file, 
    delete_old_image, 
    upload_files
)
from ....utils.generic import delete_model
from ....utils.validation import validate_payment_details
#helper functions

from ..admin.admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....constants.service_code import (
    HTTP_STATUS_CODES,
)

from app.extensions.db import db
# schemas

# model
from ....models.beneficiary_model import (
    Beneficiary
)
from ....models.sender_model import (
    Sender
)
from ....utils.essentials import Essensial

from ....schemas.doseal.subscriber.subscriber_beneficiary_schema import (
     SubscriberBeneficiarySchema, BeneficiaryUpdateSchema, BeneficiaryIdQuerySchema, 
     BeneficiariesSchema, SenderIdQuerySchema, BeneficiarySearchSchema
)

blp_subscriber_beneficiary = Blueprint("Subscriber Beneficiary", __name__, description="Subscriber Beneficiary Management")


# -----------------------BENEFICIARY-----------------------------------------
@blp_subscriber_beneficiary.route("/beneficiary", methods=["POST", "GET", "PATCH", "DELETE"])
class SubscribersSubscribersBeneficiaryResource(MethodView):

    # POST Beneficiary (Create a new Beneficiary)
    @token_required
    @blp_subscriber_beneficiary.arguments(SubscriberBeneficiarySchema, location="form")
    @blp_subscriber_beneficiary.response(201, SubscriberBeneficiarySchema)
    @blp_subscriber_beneficiary.doc(
        summary="Create a new beneficiary",
        description="""
            This endpoint allows you to create a new beneficiary. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new beneficiary by providing details such as payment mode, country, recipient name, phone number, and optional image file.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberBeneficiarySchema,
                    "example": {
                        "payment_mode": "Bank",
                        "country": "USA",
                        "currency_code": "USD",
                        "recipient_name": "John Doe",
                        "recipient_phone_number": "987-654-3210",
                        "recipient_country_iso2": "US",
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Beneficiary created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Beneficiary created successfully",
                            "status_code": 200,
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
        
        validate_payment_details(item_data)

        """Handle the POST request to create a new beneficiary."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[subscriber_benefiary_resource.py][SubscribersSubscribersBeneficiaryResource][post]'
        beneficiary_id = None
        corridor = {}
        subscriber_id = str(user_info.get("_id"))
        item_data["sender_id"] = subscriber_id

        # Assign user_id and business_id from current user
        user_id = user_info.get("_id")
        item_data["user_id"] = user_id
        business_id = user_info.get("business_id")
        item_data["business_id"] = business_id
        item_data["agent_id"] = user_info.get("agent_id")
        
        payment_mode = item_data.get("payment_mode", "").lower()
        
        # format the phone number for consistency
        country_iso2 = str.upper(item_data.get("recipient_country_iso2"))
        recipient_phone_number = validate_and_format_phone_number(item_data.get("recipient_phone_number"), country_iso2)
        item_data["recipient_phone_number"] = recipient_phone_number
    
       
        if payment_mode  == 'wallet':
            # Check if the beneficiary already exists based on business_id and phone number
            Log.info(f"{log_tag}[{client_ip}]checking if wallet beneficiary already exists")
            if Beneficiary.check_multiple_item_for_user_id_exists(item_data["business_id"], subscriber_id, {"recipient_phone_number": recipient_phone_number, "mno": item_data.get("mno")}):
                return prepared_response(False, "CONFLICT", f"Beneficiary with this wallet number already exists.")
            
        if payment_mode  == 'bank':
            # Check if the beneficiary already exists based on business_id and phone number
            Log.info(f"{log_tag}[{client_ip}]checking if bank beneficiary already exists")
            if Beneficiary.check_multiple_item_for_user_id_exists(item_data["business_id"], subscriber_id, {"account_number": item_data.get("account_number")}):
                return prepared_response(False, "CONFLICT", f"Beneficiary with this account number already exists.")
            
        
        
        
        # Handle image upload (optional)
        image_path = None
        if 'image' in request.files:
            image = request.files['image']

            try:
                # Use the upload function to upload the image
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path  # Store the path of the image
                item_data["file_path"] = actual_path  # Store the actual path of the image
            except ValueError as e:
                return prepared_response(False, "BAD_REQUEST", f"An error occurred. {str(e)}")
                
        try:
            corridor = Essensial.corridor(item_data.get("recipient_country_iso2"))
            if corridor:
                corridor = corridor.get("data")
                currency_code = corridor["currencies"][0]["code"]
                item_data["currency_code"] = currency_code
                item_data["flag"] = corridor.get("flag")
        except Exception as e:
            Log.info(f"{log_tag} error getting corridor information: error {str(e)}")

        # Create a new beneficiary instance
        beneficiary = Beneficiary(**item_data)

        # Try saving the beneficiary to the database
        try:
            Log.info(f"{log_tag}[{client_ip}] committing beneficiary")
            start_time = time.time()
            
            Log.info(f"beneficiary_data: {item_data}")

            try:
                beneficiary_id = beneficiary.save()
            except Exception as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
                

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}] committing beneficiary completed in {duration:.2f} seconds")

            if beneficiary_id is not None:
                Log.info(f"{log_tag}[{client_ip}]committed beneficiary")
                return prepared_response(False, "OK", f"Beneficiary created successfully.")
            else:
                # If creating beneficiary fails, delete the uploaded image
                if image_path:
                    os.remove(image_path)
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to create beneficiary.")
        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] error committing beneficiary: {e}")
            # If creating beneficiary fails, delete the uploaded image
            if image_path:
                os.remove(image_path)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] error committing beneficiary: {e}")
            # If creating beneficiary fails, delete the uploaded image
            if image_path:
                os.remove(image_path)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

    # GET Beneficiary (Retrieve by user_id)
    @token_required
    @blp_subscriber_beneficiary.arguments(BeneficiaryIdQuerySchema, location="query")
    @blp_subscriber_beneficiary.response(200, SubscriberBeneficiarySchema)
    @blp_subscriber_beneficiary.doc(
        summary="Retrieve beneficiary by user_id",
        description="""
            This endpoint allows you to retrieve a beneficiary based on the `user_id` in the query parameters.
            - **GET**: Retrieve a beneficiary by providing `user_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Define that Bearer token authentication is required
    )
    def get(self, beneficiary_data):
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        log_tag = '[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][get]'
        beneficiary_id = beneficiary_data.get("beneficiary_id")  # user_id passed in the query parameters

        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] retrieving benefiary.")
            start_time = time.time()

            beneficiary = Beneficiary.get_by_id(beneficiary_id=beneficiary_id, business_id=business_id)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] retrieving beneficiary completed in {duration:.2f} seconds")

            if not beneficiary:
                Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] retrieved benefiary.")
                return prepared_response(False, "NOT_FOUND", f"Beneficiary not found.")

            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] beneficiary data fetched.")
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": beneficiary
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] error retrieving benefiary. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the beneficiary. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] error retrieving benefiary. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

    # PUT Beneficiary (Update an existing beneficiary)
    @token_required
    @blp_subscriber_beneficiary.arguments(BeneficiaryUpdateSchema, location="form")
    @blp_subscriber_beneficiary.response(200, SubscriberBeneficiarySchema)
    @blp_subscriber_beneficiary.doc(
        summary="Update an existing beneficiary",
        description="""
            This endpoint allows you to update an existing beneficiary by providing `beneficiary_id` in the request body.
            - **PATCH**: Update an existing beneficiary by providing details such as payment mode, country, recipient name, phone number, and an optional image file.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberBeneficiarySchema,
                    "example": {
                        "beneficiary_id": "60a6b938d4d8c24fa0804d62",
                        "payment_mode": "Cash",
                        "country": "USA",
                        "recipient_name": "John Updated",
                        "recipient_phone_number": "987-654-9870"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Beneficiary updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Beneficiary updated successfully"
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
                "description": "Beneficiary not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Beneficiary not found"
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
        log_tag = '[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][patch]'
        """Handle the PATCH request to update an existing beneficiary."""
        beneficiary_id = item_data.get("beneficiary_id")  # beneficiary_id passed in the request body

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        item_data["user_id"] = str(user_info.get("_id"))
        business_id = str(user_info.get("business_id"))

        Log.info(f"{log_tag}[{client_ip}] updating beneficiary.")
     
        # Check if the beneficiary exists based on beneficiary_id and business_id
        beneficiary = Beneficiary.get_by_id(beneficiary_id=beneficiary_id, business_id=business_id)

        if not beneficiary:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] beneficiary not found.")
            return prepared_response(False, "NOT_FOUND", f"Beneficiary not found.")
        
        payment_mode = beneficiary.get("payment_mode", "").lower()
        recipient_phone_number = beneficiary.get("recipient_phone_number", "")
        account_number = item_data.get("account_number")
        mno = item_data.get("mno")
        
        if payment_mode  == 'wallet':
            # Check if the beneficiary already exists based on business_id and phone number
            Log.info(f"{log_tag}[{client_ip}]checking if wallet beneficiary already exists")
            if Beneficiary.check_multiple_item_exists(business_id, {"recipient_phone_number": recipient_phone_number, "mno": mno}):
                return prepared_response(False, "CONFLICT", f"Beneficiary with this wallet number already exists.")
            
        if payment_mode  == 'bank':
            # Check if the beneficiary already exists based on business_id and phone number
            Log.info(f"{log_tag}[{client_ip}]checking if bank beneficiary already exists")
            if Beneficiary.check_multiple_item_exists(business_id, {"account_number": account_number}):
                return prepared_response(False, "CONFLICT", f"Beneficiary with this account number already exists.")
            


        try:
            item_data.pop("beneficiary_id", None)
            
            start_time = time.time()

            # Update the beneficiary with the new data
            update = Beneficiary.update(beneficiary_id, business_id, **item_data)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] updating beneficiary completed in {duration:.2f} seconds")


            if update:
                Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] beneficiary updated successfully.")
                return prepared_response(True, "OK", f"Beneficiary updated successfully.")
            else:
                Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] beneficiary could not be updated.")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to update beneficiary.")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{beneficiary_id}] error updating beneficiary")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

    # DELETE Beneficiary (Delete an existing beneficiary)
    @token_required
    @blp_subscriber_beneficiary.arguments(BeneficiaryIdQuerySchema, location="query")
    @blp_subscriber_beneficiary.response(200)
    @blp_subscriber_beneficiary.doc(
        summary="Delete a beneficiary by beneficiary_id",
        description="""
            This endpoint allows you to delete a beneficiary by providing `beneficiary_id` in the query parameters.
            - **DELETE**: Delete a beneficiary by providing `beneficiary_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def delete(self, beneficiary_data):
        beneficiary_id = beneficiary_data.get("beneficiary_id")  # beneficiary_id passed in the query parameters
        image_path = None
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        log_tag = '[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][delete]'

        if not beneficiary_id:
            return prepared_response(False, "BAD_REQUEST", f"beneficiary_id must be provided.")

        beneficiary = Beneficiary.get_by_id(beneficiary_id=beneficiary_id, business_id=business_id)

        if not beneficiary:
            Log.info(f"{log_tag} [{beneficiary_id}] beneficiary not found.")
            return prepared_response(False, "NOT_FOUND", f"Beneficiary not found.")

        if beneficiary.get("image"):
            image_path = beneficiary.get("file_path")

        try:
            delete_success = Beneficiary.delete(beneficiary_id, business_id)

            if delete_success:
                if image_path:
                    delete_old_image(image_path)

                return prepared_response(True, "OK", f"Beneficiary deleted successfully.")
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to delete beneficiary.")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred.")

@blp_subscriber_beneficiary.route("/beneficiaries", methods=["GET"])
class SubscribersBeneficiaryResource(MethodView):
    @token_required
    @blp_subscriber_beneficiary.arguments(BeneficiariesSchema, location="query")
    @blp_subscriber_beneficiary.response(200, SubscriberBeneficiarySchema)
    @blp_subscriber_beneficiary.doc(
        summary="Retrieve beneficiaries using Bearer token with pagination",
        description="""
            This endpoint allows you to retrieve beneficiaries associated with the Bearer token's business.
            - **GET**: Retrieve beneficiary/beneficiaries using the Bearer token to identify the business.
            - The request requires an `Authorization` header with a Bearer token.
            - Pagination parameters:
            - `page`: The page number to retrieve (default is 1).
            - `per_page`: The number of beneficiaries to retrieve per page (default is 10).
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Beneficiaries retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "beneficiaries": [
                                    {
                                        "beneficiary_id": "60a6b938d4d8c24fa0804d62",
                                        "recipient_name": "John Doe",
                                        "recipient_phone_number": "987-654-3210",
                                        "country": "USA",
                                        "status": "Active",
                                        "business_id": "abcd1234"  # Retrieved using Bearer token
                                    }
                                ],
                                "total_count": 50,
                                "total_pages": 5,
                                "current_page": 1,
                                "per_page": 10
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
                            "message": "Invalid or missing Bearer token"
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

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        user_id = user_info.get("_id") 
        page = item_data.get("page") if item_data.get("page") else None
        per_page = item_data.get("per_page") if item_data.get("per_page") else None
        
        business_id = str(user_info.get("business_id"))
        
        Log.info(f"[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][get][{client_ip}][{user_id}] initiated get beneficiaries")

        # If business_id is not provided, return a 400 Bad Request
        if not user_id:
            return prepared_response(False, "BAD_REQUEST", f"user_id must be provided.")

        try:
            # Attempt to retrieve beneficiaries by user_id using the Beneficiary class's method
            response = Beneficiary.get_beneficiaries_by_user_id(user_id, page, per_page)

            # If no beneficiaries are found for the given business_id
            if not response:
                return prepared_response(False, "NOT_FOUND", f"Beneficiaries not found.")

            # Log the retrieval request
            Log.info(f"[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][get][{client_ip}][{user_id}] beneficiaries found")

            # Convert ObjectId to string for each beneficiary's _id field
            for beneficiary in response.get("beneficiaries"):
                beneficiary["_id"] = str(beneficiary["_id"])
                beneficiary["business_id"] = str(beneficiary["business_id"]) 

            beneficiaryData = {
                "beneficiaries": response.get("beneficiaries") if response.get("beneficiaries") else [],
                "total_count": response.get("total_count") if response.get("total_count") else None,
                "total_pages": response.get("total_pages") if response.get("total_pages") else None,
                "current_page": response.get("page") if response.get("page") else None,
                "per_page": response.get("per_page") if response.get("per_page") else None
            }
            
            # Return the beneficiary data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": beneficiaryData
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the beneficiaries. {str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")


@blp_subscriber_beneficiary.route("/beneficiary/search", methods=["GET"])
class BeneficiarySearchResource(MethodView):
    @token_required
    @blp_subscriber_beneficiary.arguments(BeneficiarySearchSchema, location="query")
    @blp_subscriber_beneficiary.response(200, BeneficiarySearchSchema)
    @blp_subscriber_beneficiary.doc(
        summary="Retrieve beneficiaries using Bearer token with pagination",
        description="""
            This endpoint allows you to retrieve beneficiaries associated with the Bearer token's business.
            - **GET**: Retrieve beneficiary/beneficiaries using the Bearer token to identify the business.
            - The request requires an `Authorization` header with a Bearer token.
            - Pagination parameters:
            - `page`: The page number to retrieve (default is 1).
            - `per_page`: The number of beneficiaries to retrieve per page (default is 10).
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Beneficiaries retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "beneficiaries": [
                                    {
                                        "beneficiary_id": "60a6b938d4d8c24fa0804d62",
                                        "recipient_name": "John Doe",
                                        "recipient_phone_number": "987-654-3210",
                                        "country": "USA",
                                        "status": "Active",
                                        "business_id": "abcd1234"  # Retrieved using Bearer token
                                    }
                                ],
                                "total_count": 50,
                                "total_pages": 5,
                                "current_page": 1,
                                "per_page": 10
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
                            "message": "Invalid or missing Bearer token"
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

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id") 
        page = item_data.get("page") if item_data.get("page") else None
        per_page = item_data.get("per_page") if item_data.get("per_page") else None
        
        account_number = item_data.get("account_number")
        recipient_phone_number = item_data.get("recipient_phone_number")
        
        if recipient_phone_number is not None:
            # require recipient_country_iso2 for wallet search
            if item_data.get("recipient_country_iso2") is None:
                return prepared_response(False, "BAD_REQUEST", f"recipient_country_iso2 is required for wallet search")
            
            country_iso2 = str.upper(item_data.get("recipient_country_iso2"))
            recipient_phone_number = validate_and_format_phone_number(item_data.get("recipient_phone_number"), country_iso2)
            
            
        Log.info(f"[subscriber_benefiary_resource.py][BeneficiarySearchResource][get][{client_ip}][{business_id}] initiated get beneficiaries")

        # If business_id is not provided, return a 400 Bad Request
        if not business_id:
            return prepared_response(False, "BAD_REQUEST", f"Business_id must be provided.")

        try:
            # Attempt to retrieve beneficiaries by user_id using the Beneficiary class's method
            response = Beneficiary.get_beneficiaries_search(
                business_id=business_id,
                page=page,
                per_page=per_page,
                account_number=account_number,
                recipient_phone_number=recipient_phone_number,
            )

            # If no beneficiaries are found for the given business_id
            if not response:
                Log.info(f"response data: {response}")
                return prepared_response(False, "NOT_FOUND", f"Beneficiaries not found for this search term.")

            # Log the retrieval request
            Log.info(f"[subscriber_benefiary_resource.py][SubscribersBeneficiaryResource][get][{client_ip}][{business_id}] beneficiaries found")

            # Convert ObjectId to string for each beneficiary's _id field
            for beneficiary in response.get("beneficiaries"):
                beneficiary["_id"] = str(beneficiary["_id"])
                beneficiary["business_id"] = str(beneficiary["business_id"]) 

            beneficiaryData = {
                "beneficiaries": response.get("beneficiaries") if response.get("beneficiaries") else [],
                "total_count": response.get("total_count") if response.get("total_count") else None,
                "total_pages": response.get("total_pages") if response.get("total_pages") else None,
                "current_page": response.get("page") if response.get("page") else None,
                "per_page": response.get("per_page") if response.get("per_page") else None
            }
            
            # Return the beneficiary data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": beneficiaryData
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the beneficiaries. {str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
