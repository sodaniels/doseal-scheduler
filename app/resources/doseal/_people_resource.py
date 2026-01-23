import bcrypt
import jwt
import os
import time
import secrets
import ast
from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g, redirect
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue



from datetime import datetime
from ...utils.essentials import Essensial
from ...utils.helpers import validate_and_format_phone_number
from ...utils.helpers import generate_tokens
#helper functions
from ...utils.generators import (
    generate_temporary_password,
    generate_otp,
    generate_registration_verification_token,
    generate_return_url_with_payload
)
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.file_upload import (
    upload_file
)
from ...utils.json_response import prepared_response
from ...services.shop_api_service import ShopApiService
from tasks import send_user_registration_email
#helper functions

from .admin.admin_business_resource import token_required
from ...utils.logger import Log # import logging
from ...utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)

# model
from ...models.people_model import (
    SystemUser, Agent
)
from ...models.business_model import Business
from ...models.user_model import User
from ...models.superadmin_model import Role
from ...utils.essentials import Essensial
from ...models.business_model import Client, Token
from app.models.superadmin_model import (
    Role, SystemUser
)

from ...constants.service_code import (
    HTTP_STATUS_CODES, AUTOMATED_TEST_USERNAMES
)


# schema
from ...schemas.people_schema import (
    BusinessIdQuerySchema, SystemUserSchema, SystemUserUpdateSchema, SystemUserIdQuerySchema,
    AgentSchema, AgentUpdateSchema, AgentIdQuerySchema, AgentRegistrationInitSchema, 
    AgentRegistrationVerifyOTPSchema, AgentRegistrationChoosePinSchema, AgentRegistrationBasicKYCSchema,
    AgentRegistrationBusinessEmailSchema, AgentRegistrationVerifyEmailSchema, AgentRegistrationDirectorSchema,
    AgentRegistrationUpdateEddQuestionnaireSchema, AgentLoginInitSchema, AgentLoginExecuteSchema, 
    AgentRegistrationBusinessKYCSchema
)


blp_system_user = Blueprint("System User", __name__,  description="System Use Management")

blp_agent = Blueprint("Agent", __name__, description="Agent Management")

blp_agent_registration = Blueprint("Agent Registration", __name__, description="Agent Registration Management")

blp_agent_login = Blueprint("Agent Login", __name__, description="Agent Login Management")


# -----------------------SYSTEM USER-----------------------------------------
@blp_system_user.route("/system-user", methods=["POST", "GET", "PUT", "DELETE"])
class SystemUserResource(MethodView):
    
    # POST SystemUser (Create a new SystemUser)
    @token_required
    @blp_system_user.arguments(SystemUserSchema, location="form")
    @blp_system_user.response(201, SystemUserSchema)
    @blp_system_user.doc(
        summary="Create a new system user",
        description="""
            This endpoint allows you to create a new system user. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new system user by providing details such as username, display name, phone, role, and an image file (optional).
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SystemUserSchema,
                    "example": {
                        "username": "johndoe",
                        "display_name": "John Doe",
                        "phone": "123-456-7890",
                        "email": "johndoe@example.com",
                        "outlet": "Store 1",
                        "role": "Manager",
                        "image": "file (profile.jpg)"  # This will be uploaded as part of the form-data
                    }
                }
            },
        },
        responses={
            201: {
                "description": "System user created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "System user created successfully",
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
        """Handle the POST request to create a new system user."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = user_info.get("business_id")
        item_data["agent_id"] = user_info.get("agent_id")

        # Handle image upload (optional)
        actual_path = None
        if 'image' in request.files:
            image = request.files['image']

            try:
                # Use the upload function to upload the image
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path  # Store the path of the image
                item_data["file_path"] = actual_path  # Store the actual path of the image
            except ValueError as e:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": str(e)  # Return the error message from the exception
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Check if the system user already exists based on username
        Log.info(f"[people_resource.py][SystemUserResource][post][{client_ip}] checking if system user already exists")
        if SystemUser.check_item_exists(item_data["business_id"], key="username", value=item_data["username"]):
            # If system user exists, delete the uploaded image before returning conflict response
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                "message": "System user already exists"
            }), HTTP_STATUS_CODES["CONFLICT"]

        item_data["password"] = bcrypt.hashpw(
            item_data["password"].encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")
        
        # Create a new system user instance
        item = SystemUser(**item_data)

        # Try saving the system user to MongoDB and handle any errors
        try:
            Log.info(f"[people_resource.py][SystemUserResource][post][{client_ip}][{item_data['username']}][committing system user]")

            # Record start time for performance monitoring
            start_time = time.time()

            system_user_id = item.save()

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"[people_resource.py][SystemUserResource][post][{client_ip}][{system_user_id}] committing system user completed in {duration:.2f} seconds")
            
            try:
                if system_user_id:
                    
                    business = Business.get_business_by_id(user_info.get("business_id"))
                    client_id = business["client_id"]
                    
                    user_data = {}
                    user_data["agent_id"] = user_info.get("agent_id") if user_info.get("agent_id") else None
                    user_data["user_id"] = str(system_user_id)
                    user_data["fullname"] = item_data["username"]
                    user_data["email"] = item_data["email"]
                    user_data["phone_number"] = item_data["phone"]
                    user_data["password"] = item_data["password"]
                    user_data["role"] = str(item_data["role"])
                    user_data["admin_id"] = item_data["user_id"]
                    user_data["client_id"] = client_id
                    user_data["business_id"] = user_info.get("business_id")
                    user_data["status"] = "Active"
                    user_data["email_verified"] = "verified"
                    
                    user = User(**user_data)
                    user_client_id = user.save()
                    
                    Log.info(f"user_client_id: {user_client_id}")
                    Log.info(f"client_id: {client_id}")
                    
            except Exception as e:
                Log.error(f"[people_resource.py][SystemUserResource][post][{client_ip}][{system_user_id}] error occurred: {str(e)}")
            

            if system_user_id is not None:
                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "message": "System user created successfully."
                }), HTTP_STATUS_CODES["OK"]
            else:
                # If creating system user fails, delete the uploaded image
                if actual_path:
                    os.remove(actual_path)
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to create system user"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except PyMongoError as e:
            # If creating system user fails, delete the uploaded image
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            # If creating system user fails, delete the uploaded image
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # GET SystemUser (List all SystemUsers)
    @token_required
    @blp_system_user.arguments(SystemUserIdQuerySchema, location="query")
    @blp_system_user.response(200, SystemUserSchema)
    @blp_system_user.doc(
        summary="Retrieve system user by user_id",
        description="""
            This endpoint allows you to retrieve a system user based on the `user_id` in the query parameters.
            - **GET**: Retrieve a system user by providing `user_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "System user retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "user_id": "60a6b938d4d8c24fa0804d62",
                                    "username": "johndoe",
                                    "display_name": "John Doe",
                                    "phone": "123-456-7890",
                                    "email": "johndoe@example.com",
                                    "outlet": "Store 1",
                                    "role": "Manager",
                                    "status": "Active",
                                    "image": "http://localhost:9090/uploads/user-image.jpg"
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
    def get(self, system_user_data):
        system_user_id = system_user_data.get("system_user_id")  # user_id passed in the query parameters

        client_ip = request.remote_addr

        Log.info(f"[people_resource.py][SystemUserResource][get][{client_ip}][{system_user_id}] retrieving system user by user_id")

        # If user_id is not provided, return a 400 Bad Request
        if not system_user_id:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "user_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            # Record start time for performance monitoring
            start_time = time.time()

            # Attempt to retrieve system user by user_id
            system_user = SystemUser.get_by_id(system_user_id)

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"[people_resource.py][SystemUserResource][get][{client_ip}][{system_user_id}] retrieving system user completed in {duration:.2f} seconds")

            # If no system user is found for the given user_id
            if not system_user:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "System user not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            # Log the retrieval request
            Log.info(f"[people_resource.py][SystemUserResource][get][{client_ip}][{system_user_id}] system user found")

            # Return the system user data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": system_user
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while retrieving the system user.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # PUT SystemUser (Update an existing system user)
    @token_required
    @blp_system_user.arguments(SystemUserUpdateSchema, location="form")
    @blp_system_user.response(200, SystemUserSchema)
    @blp_system_user.doc(
        summary="Update an existing system user",
        description="""
            This endpoint allows you to update an existing system user by providing `user_id` in the request body.
            - **PUT**: Update an existing system user by providing details such as username, display name, role, and status.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SystemUserSchema,
                    "example": {
                        "user_id": "60a6b938d4d8c24fa0804d62",
                        "username": "john_doe",
                        "display_name": "John Doe",
                        "role": "Manager",
                        "password": "newpassword123"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "System user updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "System user updated successfully"
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
                "description": "System user not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "System user not found"
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
    def put(self, item_data):
        """Handle the PUT request to update an existing system user."""
        user_id = item_data.get("system_user_id")  # user_id passed in the request body

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = user_info.get("business_id")

        # Check if the system user exists based on user_id
        Log.info(f"[people_resource.py][SystemUserResource][put][{client_ip}] checking if system user exists")
        user = SystemUser.get_by_id(user_id)

        if not user:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "System user not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Attempt to update the system user data
        try:
            Log.info(f"[people_resource.py][SystemUserResource][put][{client_ip}] updating system user")

            start_time = time.time()

            item_data.pop("system_user_id", None)

            # Update the system user with the new data
            update = SystemUser.update(user_id, **item_data)

            # Record the end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            if update:
                Log.info(f"[people_resource.py][SystemUserResource][put][{client_ip}] updating system user completed in {duration:.2f} seconds")

                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "message": "System user updated successfully."
                }), HTTP_STATUS_CODES["OK"]
            else:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to update system user"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while updating the system user.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # DELETE System User
    @token_required
    @blp_system_user.arguments(SystemUserIdQuerySchema, location="query")
    @blp_system_user.response(200)
    @blp_system_user.doc(
        summary="Delete a system user by user_id",
        description="""
            This endpoint allows you to delete a system user by providing `user_id` in the query parameters.
            - **DELETE**: Delete a system user by providing `user_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "System user deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "System user deleted successfully"
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
                "description": "System user not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "System user not found"
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
    def delete(self, system_user_data):
        user_id = system_user_data.get("system_user_id")  # user_id passed in the query parameters

        # Check if user_id is provided
        if not user_id:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "user_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Retrieve the system user using its user_id
        user = SystemUser.get_by_id(user_id)

        if not user:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "System user not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Call the delete method from the SystemUser model
        delete_success = SystemUser.delete(user_id)

        if delete_success:
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": "System user deleted successfully"
            }), HTTP_STATUS_CODES["OK"]
        else:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Failed to delete system user"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

@blp_system_user.route("/system-users", methods=["GET"])
class SystemUserResource(MethodView):
    # GET System User
    @token_required
    @blp_system_user.arguments(BusinessIdQuerySchema, location="query")
    @blp_system_user.response(200, SystemUserSchema)
    @blp_system_user.doc(
        summary="Retrieve system users by business_id",
        description="""
            This endpoint allows you to retrieve system users based on the `business_id` in the query parameters.
            - **GET**: Retrieve system user(s) by providing `business_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
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
                                    "username": "john_doe",
                                    "display_name": "John Doe",
                                    "role": "Manager",
                                    "status": "Active",
                                    "business_id": "abcd1234"
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
    def get(self, system_user_data):
        business_id = system_user_data.get("business_id")  # business_id passed in the query parameters

        client_ip = request.remote_addr

        Log.info(f"[people_resource.py][SystemUserResource][get][{client_ip}][{business_id}] initiated get system users")

        # If business_id is not provided, return a 400 Bad Request
        if not business_id:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "business_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            # Attempt to retrieve system users by business_id using the SystemUser class's method
            system_users = SystemUser.get_system_users_by_business_id(business_id)

            Log.info(f"system_users: {system_users}")
            Log.info(f"business_id: {business_id}")

            # If no system users are found for the given business_id
            if not system_users:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "System users not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            # Log the retrieval request
            Log.info(f"[people_resource.py][SystemUserResource][get][{client_ip}][{business_id}] system users found")

            # Convert ObjectId to string for each system user's _id field
            for user in system_users:
                user["_id"] = str(user["_id"])  # Ensure _id is a string for JSON serialization
                user["business_id"] = str(user["business_id"])  # Ensure business_id is a string for JSON serialization

            # Return the system user data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": system_users
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while retrieving the system users.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -----------------------SYSTEM USER-----------------------------------------

# -----------------------AGENT-----------------------------------------
@blp_agent.route("/agent", methods=["POST", "GET", "PUT", "DELETE"])
class AgentResource(MethodView):

    # POST Agent (Create a new Agent)
    @token_required
    @blp_agent.arguments(AgentSchema, location="form")
    @blp_agent.response(201, AgentSchema)
    @blp_agent.doc(
        summary="Create a new agent",
        description="""
            This endpoint allows you to create a new agent. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new agent by providing details such as username, display name, phone, role, and an image file (optional).
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentSchema,
                    "example": {
                        "username": "janedoe",
                        "display_name": "Jane Doe",
                        "phone": "987-654-3210",
                        "email": "janedoe@example.com",
                        "outlet": "Store 2",
                        "role": "Agent",
                        "image": "file (profile.jpg)"  # This will be uploaded as part of the form-data
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Agent created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Agent created successfully",
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
        log_tag = '[people_resource.py][AgentResource][post]'
        """Handle the POST request to create a new agent."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business = {}
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        
        try:
            business = Business.get_business_by_id(user_info.get("business_id"))
            print(f"business: {business}")
        except ValueError as e:
            pass
        
        # user object
        
        user_data = {}
        phone = item_data['username']
        
        user_data["fullname"] = f"{item_data['first_name']} {item_data['last_name']}"
        user_data["email"] = f'{phone}@instntmny.com'
        user_data["phone_number"] = item_data['username']
        password = generate_temporary_password()
        user_data["password"] = bcrypt.hashpw(password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")
        user_data["account_type"] = "super_admin"
        user_data["type"] = "Agent"
        

        # Handle image upload (optional)
        actual_path = None
        if 'image' in request.files:
            image = request.files['image']

            try:
                # Use the upload function to upload the image
                image_path, actual_path = upload_file(image, user_info.get("business_id"))
                item_data["image"] = image_path  # Store the path of the image
                item_data["file_path"] = actual_path  # Store the actual path of the image
            except ValueError as e:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": str(e)  # Return the error message from the exception
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Check if the agent already exists based on username
        Log.info(f"{log_tag}[{client_ip}] checking if agent already exists")
        if Agent.check_item_exists(item_data["business_id"], key="username", value=item_data["username"]):
            # If agent exists, delete the uploaded image before returning conflict response
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                "message": "Agent already exists"
            }), HTTP_STATUS_CODES["CONFLICT"]
        
        # Create a new agent instance
        item = Agent(**item_data)

        # Try saving the agent to MongoDB and handle any errors
        try:
            username = item_data['username']
            Log.info(f"{log_tag}[{client_ip}][{encrypt_data(username)}][committing agent]")

            # Record start time for performance monitoring
            start_time = time.time()

            agent_id = item.save()

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"{log_tag}[{client_ip}][{agent_id}] committing agent completed in {duration:.2f} seconds")

            if agent_id and business:
                tenant_id = business.get("tenant_id")
                user_data["user_id"] = agent_id
                user_data["client_id"] = business.get("client_id")
                user_data["business_id"] = item_data["business_id"]
                user_data["tenant_id"] = tenant_id
                
                try:
                    Log.info(f"{log_tag}[{client_ip}][committing agent user")
                    # committing user data to db
                    user = User(**user_data)
                    user_client_id = user.save()
                    if user_client_id:
                        # sending OTP
                        tenant_id = decrypt_data(tenant_id)
                        shop_service = ShopApiService()
                        pin = generate_otp()
                        message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                        
                        redisKey = f'otp_token_{pin}'
                        # set_redis_with_expiry(redisKey, 300, pin)
                        set_redis(redisKey, 300, pin) # remove this and use set_redis_with_expiry after the test
                        
                        Log.info(f"{log_tag}[{client_ip}] sending OTP")
                        response = shop_service.send_sms(username, message, tenant_id)
                        Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                except Exception as e:
                        Log.info(f"{log_tag}[{client_ip}] error creating agent user: { str(e)}")
                        return jsonify({
                            "success": False,
                            "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                            "message": f"An error occurred when creating agent: {e}"
                        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                        

                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "message": "Agent created successfully."
                }), HTTP_STATUS_CODES["OK"]
            else:
                # If creating agent fails, delete the uploaded image
                if actual_path:
                    os.remove(actual_path)
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to create agent"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except PyMongoError as e:
            # If creating agent fails, delete the uploaded image
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            # If creating agent fails, delete the uploaded image
            if actual_path:
                os.remove(actual_path)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # GET Agent (List all Agents)
    @token_required
    @blp_agent.arguments(AgentIdQuerySchema, location="query")
    @blp_agent.response(200, AgentSchema)
    @blp_agent.doc(
        summary="Retrieve agent by user_id",
        description="""
            This endpoint allows you to retrieve an agent based on the `user_id` in the query parameters.
            - **GET**: Retrieve an agent by providing `user_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def get(self, agent_data):
        agent_id = agent_data.get("agent_id")  # user_id passed in the query parameters

        client_ip = request.remote_addr

        Log.info(f"[people_resource.py][AgentResource][get][{client_ip}][{agent_id}] retrieving agent by user_id")

        # If agent_id is not provided, return a 400 Bad Request
        if not agent_id:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "agent_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            # Record start time for performance monitoring
            start_time = time.time()

            # Attempt to retrieve agent by agent_id
            agent = Agent.get_by_id(agent_id)

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"[people_resource.py][AgentResource][get][{client_ip}][{agent_id}] retrieving agent completed in {duration:.2f} seconds")

            # If no agent is found for the given agent_id
            if not agent:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "Agent not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            # Log the retrieval request
            Log.info(f"[people_resource.py][AgentResource][get][{client_ip}][{agent_id}] agent found")

            # Return the agent data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": agent
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while retrieving the agent.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # PUT Agent (Update an existing agent)
    @token_required
    @blp_agent.arguments(AgentUpdateSchema, location="form")
    @blp_agent.response(200, AgentSchema)
    @blp_agent.doc(
        summary="Update an existing agent",
        description="""
            This endpoint allows you to update an existing agent by providing `user_id` in the request body.
            - **PUT**: Update an existing agent by providing details such as username, display name, role, and status.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentSchema,
                    "example": {
                        "user_id": "60a6b938d4d8c24fa0804d62",
                        "username": "janedoe_updated",
                        "display_name": "Jane Doe Updated",
                        "role": "Senior Agent",
                        "password": "newpassword456"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Agent updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Agent updated successfully"
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
                "description": "Agent not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Agent not found"
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
    def put(self, item_data):
        """Handle the PUT request to update an existing agent."""
        agent_id = item_data.get("agent_id")  # agent_id passed in the request body

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        item_data["user_id"] = user_info.get("user_id")
        item_data["business_id"] = user_info.get("business_id")

        # Check if the agent exists based on agent_id
        Log.info(f"[people_resource.py][AgentResource][put][{client_ip}] checking if agent exists")
        agent = Agent.get_by_id(agent_id)

        if not agent:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "Agent not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Attempt to update the agent data
        try:
            Log.info(f"[people_resource.py][AgentResource][put][{client_ip}] updating agent")

            start_time = time.time()

            item_data.pop("agent_id", None)

            # Update the agent with the new data
            update = Agent.update(agent_id, **item_data)

            # Record the end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            if update:
                Log.info(f"[people_resource.py][AgentResource][put][{client_ip}] updating agent completed in {duration:.2f} seconds")

                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "message": "Agent updated successfully."
                }), HTTP_STATUS_CODES["OK"]
            else:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to update agent"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while updating the agent.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    # DELETE Agent
    @token_required
    @blp_agent.arguments(AgentIdQuerySchema, location="query")
    @blp_agent.response(200)
    @blp_agent.doc(
        summary="Delete an agent by agent_id",
        description="""
            This endpoint allows you to delete an agent by providing `agent_id` in the query parameters.
            - **DELETE**: Delete an agent by providing `agent_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Agent deleted successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Agent deleted successfully"
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
                "description": "Agent not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "Agent not found"
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
    def delete(self, agent_data):
        agent_id = agent_data.get("agent_id")  # agent_id passed in the query parameters

        # Check if agent_id is provided
        if not agent_id:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "agent_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Retrieve the agent using its agent_id
        agent = Agent.get_by_id(agent_id)

        if not agent:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "Agent not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Call the delete method from the Agent model
        delete_success = Agent.delete(agent_id)

        if delete_success:
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": "Agent deleted successfully"
            }), HTTP_STATUS_CODES["OK"]
        else:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Failed to delete agent"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -----------------------AGENT REGISTRATION INITIATE-----------------------------------------
@blp_agent_registration.route("/registration/initiate", methods=["POST"])
class AgentRegistrationResource(MethodView):
     # POST Agent (Create a new Agent)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationInitSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationInitSchema)
    @blp_agent_registration.doc(
        summary="Create a new agent",
        description="""
            This endpoint allows you to create a new agent. The request requires an `Authorization` header with a Bearer token.

            - **POST**: Create a new agent by providing the `username` (phone number) and confirming 
            `agreed_terms_and_conditions`. An optional profile `image` can also be uploaded as part of the form-data.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentRegistrationInitSchema,  # Updated schema
                    "example": {
                        "username": "janedoe",  # Example username (phone number)
                        "agreed_terms_and_conditions": True,
                        "image": "file (profile.jpg)"  # Optional profile image
                    }
                }
            },
        },
        responses={
            201: {
                "description": "OTP has been sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "OTP has been sent",
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
        log_tag = '[people_resource.py][AgentRegistrationResource][post]'
        """Handle the POST request to create a new agent."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        tenant_id = None
        username = None
        
        t = user_info.get("tenant_id")
        Log.info(f"user_info: {decrypt_data(t)}")
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        
        business = Business.get_business_by_id(user_info.get("business_id"))
        
        # only preceed when user accepts terms and condition
        if not item_data.get("agreed_terms_and_conditions"):
            return prepared_response(False, "BAD_REQUEST", f"Agent must accept terms and conditions")
        
        
        if business:
            tenant_id = decrypt_data(business.get("tenant_id"))
            
            if tenant_id:
                tenant = Essensial.get_tenant_by_id(tenant_id)
                country_iso_2 = tenant.get("country_iso_2")
                username = validate_and_format_phone_number(item_data.get("username"), country_iso_2)
                
                try:
                    if username:
                        # Check if the agent already exists based on username
                        Log.info(f"{log_tag}[{client_ip}][{username}] checking if agent already exists")
                        
                        agent_check = Agent.get_by_username(username)
                        
                        if agent_check:
                            # If agent exists, delete the uploaded image before returning conflict response
                            return jsonify({
                                "success": False,
                                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                                "message": "Agent already exists"
                            }), HTTP_STATUS_CODES["CONFLICT"]
                            
                        # sending OTP
                        shop_service = ShopApiService(tenant_id)
                        
                        app_mode = os.getenv("APP_RUN_MODE")
                        
                        # needed for automated testing
                        if username in AUTOMATED_TEST_USERNAMES or app_mode =='development':
                            automated_test_otp = os.getenv("AUTOMATED_TEST_OTP")
                            
                            pin = automated_test_otp
                            
                            message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                            redisKey = f'otp_token_{username}'
                            set_redis_with_expiry(redisKey, 300, pin)
                        
                            set_redis_with_expiry("automate_test_username", 300, username)
                            set_redis_with_expiry("otp_token_automated_test", 300, pin)
                            
                            Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] AUTOMATED TESTING OTP")
                            return jsonify({
                                "success": True,
                                "status_code": HTTP_STATUS_CODES["OK"],
                                "message": "OTP has been sent",
                            }), HTTP_STATUS_CODES["OK"]
                            # needed for automated testing
                        else:
                            pin = generate_otp()
                            message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                            redisKey = f'otp_token_{username}'
                            set_redis_with_expiry(redisKey, 300, pin)
                        
                            Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] sending OTP")
                            response = shop_service.send_sms(username, message, tenant_id)
                            Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                            
                            if response and response.get("status") == "success":
                                return jsonify({
                                    "success": True,
                                    "status_code": HTTP_STATUS_CODES["OK"],
                                    "message": "OTP has been sent",
                                }), HTTP_STATUS_CODES["OK"]
                                
                            else:
                                return jsonify({
                                    "success": False,
                                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                                    "message": "Could not send OTP",
                                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                        
                    else:
                        return jsonify({
                                "success": False,
                                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                                "message": "Invalid number",
                            }), HTTP_STATUS_CODES["BAD_REQUEST"]
                except Exception as e:
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                        "message": "An unexpected error occurred",
                        "error": str(e)
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            else:
                return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                        "message": "An unexpected error occurred",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        else:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

# -----------------------AGENT REGISTRATION VERIFY OTP-----------------------------------------
@blp_agent_registration.route("/registration/verify-otp", methods=["POST"])
class AgentRegistrationVerifyOTPResource(MethodView):
     # POST Agent (Verify agent OTP)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationVerifyOTPSchema, location="form")
    @blp_agent_registration.response(201, AgentRegistrationVerifyOTPSchema)
    @blp_agent_registration.doc(
        summary="Verify OTP for agent registration",
        description="""
            This endpoint allows you to verify the OTP sent to an agent's phone number during registration. 
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Verify the OTP by providing the `username` (phone number) and the `otp` that was sent to the phone.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationVerifyOTPSchema,  # Updated schema for OTP verification
                    "example": {
                        "username": "987-654-3210",  # Example phone number (username)
                        "otp": "123456"  # Example OTP
                    }
                }
            },
        },
        responses={
            201: {
                "description": "OTP has been verified successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "account_status": [
                                        {
                                            "account_verified": {
                                                "created_at": str(datetime.utcnow()),
                                                "status": True,
                                                "ip_address": "127.0.0.1"
                                            },
                                        },
                                         {
                                            "choose_pin": {
                                                "status": False,
                                            },
                                        }, 
                                        {
                                            "basic_kyc_added": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "business_email_verified": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "uploaded_agent_id_info": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "uploaded_director_id_info": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "registration_completed": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "onboarding_in_progress": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "onboarding_in_progress": {
                                                "status": False,
                                            }
                                        }
                                    ],
                            "message": "OTP verified and agent registration is in progress",
                            "status_code": 200,
                            "success": True  # This would indicate that OTP verification was successful
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
        log_tag = '[people_resource.py][AgentRegistrationVerifyOTPResource][post]'
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        username = None
        
        business = Business.get_business_by_id(user_info.get("business_id"))
        
        if business:
            
            tenant_id = decrypt_data(business.get("tenant_id"))
            
            if tenant_id:
                
                # valid phone number only if not testing
                automated_test_username = os.getenv("AUTOMATED_TEST_USERNAME")
                if username != automated_test_username:
                    tenant = Essensial.get_tenant_by_id(tenant_id)
                    country_iso_2 = tenant.get("country_iso_2")
                    username = validate_and_format_phone_number(item_data.get("username"), country_iso_2)
                
                otp = item_data.get("otp")
                
                redisKey = f'otp_token_{username}'
                
                token_byte_string = get_redis(redisKey)
                
                if not token_byte_string:
                    return prepared_response(False, "UNAUTHORIZED", f"The OTP has expired")
                
                # Decode the byte string and convert to integer
                token = token_byte_string.decode('utf-8')
                
                if str(otp) != str(token):
                    Log.info(f"{log_tag}[otp: {otp}][token: {token}] verification failed" )
                    return prepared_response(False, "UNAUTHORIZED", f"The OTP is not valid")
                else:
                    Log.info(f"{log_tag} verification worked")
                    # remove token from redis
                    remove_redis(redisKey)
                    
                    #verification completed, proceed to create agent
                    # Assign user_id and business_id from current user
                    try:
                        business = Business.get_business_by_id(user_info.get("business_id"))
                    except ValueError as e:
                        Log.info(f"{log_tag} error pulling business information: {str(e)}")
                        
                    agent_data = {}
                    agent_data["username"] = username
                    agent_data["business_id"] = user_info.get("business_id")
                    agent_data["tenant_id"] = decrypt_data(business.get("tenant_id"))
                    
                    # Create the structure for account_status 
                    
                    account_status = [
                                        {
                                            "account_verified": {
                                                "created_at": str(datetime.utcnow()),
                                                "status": True,
                                                "ip_address": client_ip
                                            },
                                        },
                                         {
                                            "choose_pin": {
                                                "status": False,
                                            },
                                        }, 
                                        {
                                            "basic_kyc_added": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "business_email_verified": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "uploaded_agent_id_info": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "uploaded_director_id_info": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "registration_completed": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "onboarding_in_progress": {
                                                "status": False,
                                            }
                                        },
                                        {
                                            "edd_questionnaire": {
                                                "status": False,
                                            }
                                        } 
                                    ]
                    
                    agent_data["account_status"] = account_status
                    
                    try:
                     # Check if the agent already exists based on username 
                        Log.info(f"{log_tag}[{client_ip}] checking if agent already exists")
                        if Agent.check_item_exists(agent_data["business_id"], key="username", value=username):
                            # If agent exists, delete the uploaded image before returning conflict response
                            return jsonify({
                                "success": False,
                                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                                "message": "Agent already exists"
                            }), HTTP_STATUS_CODES["CONFLICT"]
                            
                            
                        # Create a new agent instance
                        Log.info(f"{log_tag} committing agent")
                        
                        # Record the start time
                        start_time = time.time()
                        
                        agent_obj = Agent(**agent_data)
                        account_status, agent_id = agent_obj.save()
                        
                        Log.info(f"{log_tag} agent_id: {agent_id}")
                        
                        # Record the end time
                        end_time = time.time()
                        
                        # Calculate the duration
                        duration = end_time - start_time
                        
                        # Log the response and time taken
                        Log.info(f"{log_tag} [{client_ip}] commit agent completed in {duration:.2f} seconds")
                        
                        if agent_id:
                            user_data = {}
                            phone = item_data['username']
                            user_data["email"] = f'{phone}@instntmny.com'
                            user_data["phone_number"] = item_data['username']
                            password = generate_temporary_password()
                            user_data["password"] = bcrypt.hashpw(password.encode("utf-8"),
                                bcrypt.gensalt()
                            ).decode("utf-8")
                            user_data["account_type"] = "super_admin"
                            user_data["type"] = "Agent"
                            user_data["business_id"] = user_info.get("business_id") 
                            user_data["agent_id"] = agent_id
                            user_data["tenant_id"] = business.get("tenant_id")
                            user_data["client_id"] = decrypt_data(business.get("client_id"))
                            
                            create_user = commit_agent_user(
                                log_tag=log_tag, 
                                client_ip=client_ip, 
                                user_data=user_data,
                                email=user_data["email"], 
                                account_status=account_status, 
                                agent_id=agent_id
                            )
                            return create_user
                            
                        else:
                            return jsonify({
                                "success": False,
                                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                                "message": f"Agent could not be created",
                            }), HTTP_STATUS_CODES["BAD_REQUEST"]
                    except Exception as e:
                        return jsonify({
                            "success": False,
                            "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                            "message": f"An unexpected error occurred: {str(e)}",
                        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                        
            else:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "An unexpected error occurred",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        else:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

# -----------------------AGENT REGISTRATION CHOOSE PIN-----------------------------------------
@blp_agent_registration.route("/registration/choose-pin", methods=["PATCH"])
class AgentRegistrationChoosePINResource(MethodView):
     # POST Agent (Create a new Agent)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationChoosePinSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationChoosePinSchema)
    @blp_agent_registration.doc(
        summary="Choose PIN for agent registration",
        description="""
            This endpoint allows an agent to set their PIN after successfully registering.
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Set the PIN for the agent by providing the `agent_id` and the `pin`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationChoosePinSchema,  # Updated schema for choosing the pin
                    "example": {
                        "agent_id": "60d21b4967d0d8992e610c85",  # Example agent ID (ObjectId)
                        "pin": "1234"  # Example PIN
                    }
                }
            },
        },
        responses={
            201: {
                "description": "PIN has been successfully set",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Account PIN updated successfully",
                            "status_code": 200,
                            "success": True  # Success should be True on successful update
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
    def patch(self, item_data):
        log_tag = '[people_resource.py][AgentRegistrationChoosePINResource][post]'
        """Handle the POST request to choose account PIN."""
        client_ip = request.remote_addr
        agent_id = item_data.get("agent_id")
        account_status = dict()
        
        
        # check if agent exist before proceeding to update the information 
        try:
            agent = Agent.get_by_id(agent_id)
            if not agent:
                Log.info(f"{log_tag} agent_id with ID: {agent_id} does not exist")
                return prepared_response(False, "NOT_FOUND", f"Agent_id with ID: {agent_id} does not exist")
            
            account_status = agent.get("account_status")
            # choose_pin = account_status
            
            # Get the status for 'choose_pin'
            choose_pin_status = next((item["choose_pin"]["status"] for item in account_status if "choose_pin" in item), None)
            
            # Check if account PIN has already been set
            # if choose_pin_status:
            #     # stop the action if status PIN has already been set
            #     return prepared_response(False, "BAD_REQUEST", f"Account PIN has already been set.")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
 
        
        try:
          
            pin = item_data["pin"]
            # update acount pin
            Log.info(f"{log_tag}[{client_ip}] updating account PIN")
            
            # Record the start time
            start_time = time.time()
            
            update_pin = User.update_account_pin_by_agent_id(agent_id, pin)
            
            # Record the end time
            end_time = time.time()
            
            # Calculate the duration
            duration = end_time - start_time
            
            # Log the response and time taken
            Log.info(f"{log_tag}[{client_ip}] updating PIN completed in {duration:.2f} seconds")
            
            
            if update_pin:
                # update choose_pin status for account_status in agents collection
                Log.info(f"{log_tag}[{client_ip}] updating account PIN")
                
                update_account_status = Agent.update_account_status_by_agent_id(
                    agent_id,
                    client_ip,
                    'choose_pin',
                    True
                )
                
                Log.info(f"{log_tag}[{client_ip}] update_account_status: {update_account_status}")
                
                if update_account_status and update_account_status.get("success"):
                    
                    return jsonify({
                        "success": True,
                        "status_code": HTTP_STATUS_CODES["OK"],
                        "message": f"Account PIN updated successfully",
                    }), HTTP_STATUS_CODES["OK"] 
                else:
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                        "message": f"PIN update failed",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
            else:
                 return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": f"Account PIN could not be updated",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
        except Exception as e:
            Log.info(f"{log_tag} error updating account PIN: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"An unexpected error occurred: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                 
# -----------------------GET REGISTRATION AGENT-----------------------------------------
@blp_agent_registration.route("/registration/agent", methods=["GET"])
class AgentRegistrationChoosePINResource(MethodView):
    # GET Agent (Retrieve by agent_id)
    @token_required
    @blp_agent.arguments(AgentIdQuerySchema, location="query")
    @blp_agent.response(200, AgentSchema)
    @blp_agent.doc(
        summary="Retrieve agent by agent_id",
        description="""
            This endpoint allows you to retrieve an agent based on the `agent_id` in the query parameters.
            - **GET**: Retrieve an agent by providing `agent_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Define that Bearer token authentication is required
    )
    def get(self, agent_data):
        log_tag = '[agent_resource.py][AgentResource][get]'
        agent_id = agent_data.get("agent_id")  # agent_id passed in the query parameters

        client_ip = request.remote_addr

        if not agent_id:
            Log.info(f"{log_tag}[{client_ip}] agent_id must be provided.")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "agent_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] retrieving agent.")
            start_time = time.time()

            # Assuming `Agent.get_by_id()` method retrieves the agent using agent_id
            agent = Agent.get_by_id(agent_id)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] retrieving agent completed in {duration:.2f} seconds")

            if not agent:
                Log.info(f"{log_tag}[{client_ip}][{agent_id}] agent not found.")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "Agent not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            Log.info(f"{log_tag}[{client_ip}][{agent_id}] agent retrieved successfully.")
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": agent
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] error retrieving agent. {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while retrieving the agent.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] error retrieving agent. {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"An unexpected error occurred: {str(e)}",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -----------------------AGENT REGISTRATION BASIC KYC-----------------------------------------
@blp_agent_registration.route("/registration/basic-kyc", methods=["PATCH"])
class AgentRegistrationBasicKYCResource(MethodView):
     # PATCH Agent (Verify agent OTP)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationBasicKYCSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationBasicKYCSchema)
    @blp_agent_registration.doc(
        summary="Update Business KYC for Agent",
        description="""
            This endpoint allows you to update the business KYC (Know Your Customer) information 
            for an agent during registration.

            The request must include an `Authorization` header with a Bearer token.

            - **PUT**: Update the business KYC by providing `agent_id`, `business_name`, 
            `business_email`, `business_address`, `contact_person_fullname`, and `contact_person_phone_number`. 
            An optional `referral_code` can also be provided.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationBasicKYCSchema,  # Schema for updating business KYC details
                    "example": {
                        "agent_id": "67ff9e32272817d5812ab2fc",  # Example agent ID (ObjectId)
                        "business_name": "ZeeTech Limited",
                        "business_email": "zeetech@gmail.com",
                        "business_address": "21 Albert Embankment",
                        "contact_person_fullname": "Samuel Opoku Daniels",
                        "contact_person_phone_number": "07568983863",
                        "referral_code": "ABC123"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Business KYC details have been successfully updated",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Business KYC updated successfully",
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
    def patch(self, item_data):
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        log_tag = f'[people_resource.py][AgentRegistrationBasicKYCResource][post][{client_ip}]'
        user_info = g.get("current_user", {})
        tenant_id = None
        agent = None
        phone_number = None
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        agent_id = item_data.get("agent_id")
        
        # check if agent exist before proceeding to update the information 
        try:
            agent = Agent.get_by_id(agent_id)
            if not agent:
                Log.info(f"{log_tag} agent_id with ID: {agent_id} does not exist")
                
                return prepared_response(False, "NOT_FOUND", f"Agent_id with ID: {agent_id} does not exist")
        
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
 
        
        Log.info(f"{log_tag} getting business information")
        business = Business.get_business_by_id(user_info.get("business_id"))
        
        if business:
            tenant_id = decrypt_data(business.get("tenant_id"))
            Log.info(f"{log_tag} getting ternant information")
            
            if tenant_id:
                # valid phone number only if not testing
                automated_test_username = os.getenv("AUTOMATED_TEST_USERNAME")
                if not automated_test_username:
                    tenant = Essensial.get_tenant_by_id(tenant_id)
                    country_iso_2 = tenant.get("country_iso_2")
                    phone_number = validate_and_format_phone_number(item_data.get("contact_person_phone_number"), country_iso_2)
                else:
                    phone_number = automated_test_username
                    
                if not phone_number:
                    return prepared_response(False, "BAD_REQUEST", "Invalid phone number")
                try:
                    update_business = Agent.update_business_kyc_by_agent_id(**item_data)
                    Log.info(f"{log_tag} update_business: {update_business}")
                    
                    if update_business and update_business.get("success"):
                        Log.info(f"{log_tag} business update was successful, updating account_status")
                        
                        update_account_status = Agent.update_account_status_by_agent_id(
                            agent_id,
                            client_ip,
                            'basic_kyc_added',
                            True
                        )
                        
                        Log.info(f"{log_tag} update_account_status: {update_account_status}")
                        if update_account_status and update_account_status.get("success"):
                            return prepared_response(True, "OK", "Business KYC updated succssfully")
                        else: 
                            return prepared_response(False, "BAD_REQUEST", "Business KYC could not be upated")
                        
                    else:
                        return prepared_response(False, "BAD_REQUEST", "Business KYC could not be upated")
                except Exception as e:
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
      
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred")
        else:
            return prepared_response(False, "UNAUTHORIZED", f"Unauthorized")

# -----------------------AGENT REGISTRATION INITIATE EMAIL VERIFICAITON-----------------------------------------
@blp_agent_registration.route("/registration/initiate-email-verification", methods=["POST"])
class AgentRegistrationInitiateEmailVerificationResource(MethodView):
     # PATCH Agent (Verify agent OTP)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationBusinessEmailSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationBusinessEmailSchema)
    @blp_agent_registration.doc(
        summary="Verify Business Email for agent",
        description="""
            This endpoint allows you to verify the business email for an agent during registration. 
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Verify the business email by providing `agent_id` and `return_url`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationBusinessEmailSchema,  # Schema for verifying business email
                    "example": {
                        "agent_id": "67ff9e32272817d5812ab2fc",  # Example agent ID (ObjectId)
                        "return_url": "http://localhost:9090/redirect"  # Example return URL
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Email has been successfully sent to the agent's business email",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Email has been sent to agent business email successfully.",
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
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        log_tag = f'[people_resource.py][AgentRegistrationInitiateEmailVerificationResource][post][{client_ip}]'
        user_info = g.get("current_user", {})
        agent = None
        business_name = None
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        agent_id = item_data.get("agent_id")
        return_url = item_data.get("return_url")
        
        # check if agent exist before proceeding to update the information 
        try:
            Log.info(f"{log_tag} checking if agent exist")
            agent = Agent.get_by_id(agent_id)
            if not agent:
                Log.info(f"{log_tag} agent_id with ID: {agent_id} does not exist")
                
                return prepared_response(False, "NOT_FOUND", f"Agent_id with ID: {agent_id} does not exist")
            
            agent_business = agent.get('business', None)
            
            
            # Retrieve the business_email safely
            if agent_business:  # Check if business list exists and is not empty
              
                business_email = agent["business"][0].get("business_email", None) 
                business_name = agent["business"][0].get("business_name", None) 
                
                Log.info(f"New business_email: {business_email}")
          
                base_url = request.host_url
                
                token = secrets.token_urlsafe(32)  # Generates a 32-byte URL-safe token
                
                encrypt_agent_id = encrypt_data(agent_id)
                
                reset_url = generate_registration_verification_token(base_url, encrypt_agent_id, token)
                
                Log.info(f"reset_url: {reset_url}")
                
                redisKey = f'email_token_{agent_id}'
                
                payload = {"token": token, "return_url": return_url}
                set_redis_with_expiry(redisKey, 300, str(payload))
                
                try:
                    Log.info(f"{log_tag} making request to send email for verification")
                    send = send_user_registration_email(business_email, business_name, reset_url)
                    if send and send.status_code == 200:
                        return prepared_response(True, "OK", f"Email has been sent to agent business email successfully.")
                    else:
                        return prepared_response(False, "BAD_REQUEST", f"An error occurred while sending email to agent's business email.")
                        
                except Exception as e:
                     Log.info(f"{log_tag} \t An error occurred sending emails: {e}")
                     return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")

            else:
                # agent business kyc not updated
                Log.info(f"{log_tag} The KYC information including the business email has not  been added. First call the 'registration/basic-kyc' before you can verify the email.")
                return prepared_response(False, "BAD_REQUEST", f"The KYC information including the business email has not  been added. First call the 'registration/basic-kyc' before you can verify the email.")
                
                
            
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")

# -----------------------AGENT REGISTRATION VERIFY EMAIL-----------------------------------------
@blp_agent_registration.route("/registration/verify-email", methods=["GET"])
class AgentRegistrationVerifyEmailResource(MethodView):
     # GET verify agent email (Verify agent Email)
    @blp_agent_registration.arguments(AgentRegistrationVerifyEmailSchema, location="query")
    @blp_agent_registration.response(200, AgentRegistrationVerifyEmailSchema)
    @blp_agent_registration.doc(
        summary="Verify Business Email for agent",
        description="""
            This endpoint allows you to verify the business email for an agent during registration. 
            The request does not require a Bearer token.
            - **POST**: Verify the business email by providing `token` and `user_id`.
            After the verification, the user will be redirected to the `return_url` provided.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationVerifyEmailSchema,  # Updated schema for verifying business email
                    "example": {
                        "token": "Hevpo9mkiuh67ffb4d02ed2c13ca4fa5a5b",  # Example token for the registration session
                        "user_id": "67ff9e32272817d5812ab2fc"  # Example user ID (ObjectId)
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Business email verification request has been processed successfully. User will be redirected.",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Verification email sent. Please check your inbox for further instructions.",
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
        """Handle the POST request to verify Email."""
        client_ip = request.remote_addr
        log_tag = f'[people_resource.py][AgentRegistrationVerifyEmailResource][post][{client_ip}]'
        
        decrypted_agent_id = None
        token = item_data.get("token")
        agent_id = item_data.get("user_id")
        
        # decrypt agent ID
        try:
            decrypted_agent_id = decrypt_data(agent_id)
            if decrypted_agent_id:
               Log.info(f"{log_tag} Agent ID decrypted")
               redisKey = f'email_token_{decrypted_agent_id}'
               
               payload = get_redis(redisKey)
               
               payload_decoded = payload.decode('utf-8')
               
               Log.info(f"{log_tag} payload_decoded: {payload_decoded}")
               
               # Convert the string to a dictionary
               payload_dict = ast.literal_eval(payload_decoded)
               
               redis_token = payload_dict["token"]
               return_url = payload_dict["return_url"]
               
               if not redis_token or not return_url:
                    Log.info(f"{log_tag} Extracting token from redis failed")
                    return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
               else:
                    # token exist, proceed to update account_status
                    Log.info(f"{log_tag} Redis token has been extracted from redis")
                    
                    
                    if str(redis_token) == str(token):
                        Log.info(f"{log_tag} Redis token same as request token")
                        update_account_status = Agent.update_account_status_by_agent_id(
                            decrypted_agent_id,
                            client_ip,
                            'business_email_verified',
                            True
                        )
                        if update_account_status and update_account_status.get("success"):
                            Log.info(f"update_account_status: {update_account_status}")
                            
                            query_params = {"status_code": 200, "message": "Email verified successfully"}
                            
                            return_url_payload = generate_return_url_with_payload(return_url, query_params)
                            
                            remove_redis(redisKey) # remove token from redis
                            Log.info(f"{log_tag} return_url_payload: {return_url_payload}")
                            return redirect(f"{return_url_payload}")
                        else:
                            return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
                    else:
                         Log.info(f"{log_tag} Redis token different from request token")
                         
                         Log.info(f"{log_tag} Redis token: {redis_token}")
                         Log.info(f"{log_tag} Request token: {token}")
                         return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
            else:
                return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
                
               
        except Exception as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")

# -----------------------AGENT REGISTRATION ADD DIRECTOR INFO-----------------------------------------
@blp_agent_registration.route("/registration/director", methods=["PATCH"])
class AgentRegistrationDirectorResource(MethodView):
     # PATCH Agent (Verify agent OTP)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationDirectorSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationDirectorSchema)
    @blp_agent_registration.doc(
        summary="Update Director ID Information for Agent",
        description="""
            This endpoint allows you to update the director ID information for an agent during registration.

            The request requires an `Authorization` header with a Bearer token.

            - **PUT**: Update the director ID details by providing:
                - `agent_id`
                - `fullname` (optional)
                - `phone_number`
                - `id_type` (optional: Passport, Driving Licence, National Identity Card)
                - `id_number` (optional)
                - `id_front_image` (optional file)
                - `id_back_image` (optional file)
                - `proof_of_address` (optional file)
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentRegistrationDirectorSchema,  # Updated schema
                    "example": {
                        "agent_id": "67ff9e32272817d5812ab2fc",  # Example agent ID (ObjectId)
                        "fullname": "John Doe",
                        "phone_number": "1234567890",
                        "id_type": "Passport",
                        "id_number": "A12345678",
                        "id_front_image": "file (front.jpg)",
                        "id_back_image": "file (back.jpg)",
                        "proof_of_address": "file (address.jpg)"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Director ID information has been successfully updated",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Director ID information updated successfully",
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
    def patch(self, item_data):
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        log_tag = f'[people_resource.py][AgentRegistrationDirectorResource][post][{client_ip}]'
        user_info = g.get("current_user", {})
        tenant_id = None
        agent = None
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        agent_id = item_data.get("agent_id")
        
        
        # check if agent exist before proceeding to update the information 
        try:
            agent = Agent.get_by_id(agent_id)
            if not agent:
                Log.info(f"{log_tag} agent_id with ID: {agent_id} does not exist")
                return prepared_response(False, "NOT_FOUND", f"Agent_id with ID: {agent_id} does not exist")
        
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
 
        
        Log.info(f"{log_tag} getting business information")
        business = Business.get_business_by_id(user_info.get("business_id"))
        
        if business:
            tenant_id = decrypt_data(business.get("tenant_id"))
            Log.info(f"{log_tag} getting ternant information")
            
            if tenant_id:
                tenant = Essensial.get_tenant_by_id(tenant_id)
                country_iso_2 = tenant.get("country_iso_2")
                phone_number = validate_and_format_phone_number(item_data.get("phone_number"), country_iso_2)
                
                if not phone_number:
                    return prepared_response(False, "BAD_REQUEST", "Invalid phone number")
                try:
                    
                    # Handle id_front_image image_file upload
                    actual_id_front_path = None
                    if 'id_front_image' in request.files:
                        image_file = request.files['id_front_image']
                        try:
                            # Use the upload function to upload the logo
                            image_path, actual_id_front_path = upload_file(image_file, user_info.get("business_id"))
                            item_data["id_front_image"] = image_path  # Store the path of the image_file
                            item_data["id_front_image_file_path"] = actual_id_front_path  # Store the actual path of the image_file
                        except ValueError as e:
                            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
                    
                    # Handle id_front_image image_file upload
                    actual_id_back_path = None
                    if 'id_back_image' in request.files:
                        id_back_image_file = request.files['id_back_image']
                        try:
                            # Use the upload function to upload the logo
                            id_back_image_path, actual_id_back_path = upload_file(id_back_image_file, user_info.get("business_id"))
                            item_data["id_back_image"] = id_back_image_path  # Store the path of the image_file
                            item_data["id_back_image_file_path"] = actual_id_back_path  # Store the actual path of the image_file
                        except ValueError as e:
                            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
                    
                    # Handle proof_of_address file upload
                    actual_proof_of_address_path = None
                    if 'proof_of_address' in request.files:
                        proof_of_address_file = request.files['proof_of_address']
                        try:
                            # Use the upload function to upload the logo
                            proof_of_address_file_path, actual_proof_of_address_path = upload_file(proof_of_address_file, user_info.get("business_id"))
                            item_data["proof_of_address"] = proof_of_address_file_path  # Store the path of the file
                            item_data["proof_of_address_file_path"] = actual_proof_of_address_path  # Store the actual path of the file
                        except ValueError as e:
                            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
                    
                    
                    update_business = Agent.update_director_id_info_by_agent_id(**item_data)
                    Log.info(f"{log_tag} update_business: {update_business}")
                    
                    if update_business and update_business.get("success"):
                        Log.info(f"{log_tag} business update was successful, updating account_status")
                        
                        update_account_status = Agent.update_account_status_by_agent_id(
                            agent_id,
                            client_ip,
                            'uploaded_director_id_info',
                            True
                        )
                        
                        Log.info(f"{log_tag} update_account_status: {update_account_status}")
                        if update_account_status and update_account_status.get("success"):
                            return prepared_response(True, "OK", "Directors ID information updated succssfully")
                        else: 
                            return prepared_response(False, "BAD_REQUEST", "Directors ID information could not be upated")
                        
                    else:
                        #delete uploaded files
                        if actual_id_front_path:
                            os.remove(actual_id_front_path)
                            
                        return prepared_response(False, "BAD_REQUEST", "Directors ID information could not be upated")
                except Exception as e:
                    #delete uploaded files
                    if actual_id_front_path:
                        os.remove(actual_id_front_path)
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
      
            else:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred")
        else:
            return prepared_response(False, "UNAUTHORIZED", f"Unauthorized")

# -----------------------AGENT REGISTRATION UPDATE EDD QUENSTIONNAIRE-----------------------------------------
@blp_agent_registration.route("/registration/update-edd-questionnaire", methods=["PATCH"])
class AgentRegistrationDirectorResource(MethodView):
     # PATCH Agent (Update EDD Questionnaire)
    @token_required
    @blp_agent_registration.arguments(AgentRegistrationUpdateEddQuestionnaireSchema, location="form")
    @blp_agent_registration.response(200, AgentRegistrationUpdateEddQuestionnaireSchema)
    @blp_agent_registration.doc(
        summary="Update EDD Questionnaire for Agent",
        description="""
            This endpoint allows you to update the EDD (Enhanced Due Diligence) questionnaire information 
            for an agent during registration.

            The request must include an `Authorization` header with a Bearer token.

            - **PUT**: Submit `agent_id` and `edd_questionnaire` to update the agent’s uploads.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AgentRegistrationUpdateEddQuestionnaireSchema,  # Updated schema
                    "example": {
                        "agent_id": "67ff9e32272817d5812ab2fc",  # Example agent ID
                        "edd_questionnaire": {
                            "question_1": "Yes",
                            "question_2": "No",
                            "notes": "Additional explanation here"
                        },
                        "edd_questionnaire_file_path": "uploads/edd_files/questionnaire_67ff9e.pdf"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "EDD questionnaire information has been successfully updated",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "EDD questionnaire updated successfully",
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
    def patch(self, item_data):
        """Handle the POST request to Update EDD Questionnaire."""
        client_ip = request.remote_addr
        log_tag = f'[people_resource.py][AgentRegistrationUpdateEddQuestionnaireSchema][post][{client_ip}]'
        user_info = g.get("current_user", {})
        agent = None
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = user_info.get("business_id") 
        agent_id = item_data.get("agent_id")
        
        if 'edd_questionnaire' not in request.files:
            return prepared_response(False, "VALIDATION_ERROR", "EDD Questionnaire is Required")
    
        # check if agent exist before proceeding to update the information 
        try:
            agent = Agent.get_by_id(agent_id)
            if not agent:
                Log.info(f"{log_tag} agent_id with ID: {agent_id} does not exist")
                return prepared_response(False, "NOT_FOUND", f"Agent_id with ID: {agent_id} does not exist")
        
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
 
        
        Log.info(f"{log_tag} getting business information")
        business = Business.get_business_by_id(user_info.get("business_id"))
        
        edd_questionnaire_path = None
        
        if business:
            
            try: 
                # Handle edd_questionnaire image_file upload
                if 'edd_questionnaire' in request.files:
                    image_file = request.files['edd_questionnaire']
                    try:
                        # Use the upload function to upload the logo
                        image_path, edd_questionnaire_path = upload_file(image_file, user_info.get("business_id"))
                        item_data["edd_questionnaire"] = image_path  # Store the path of the image_file
                        item_data["edd_questionnaire_file_path"] = edd_questionnaire_path  # Store the actual path of the image_file
                    except ValueError as e:
                        return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
                
                item_data["agent_id"] = agent_id
                update_uploads = Agent.update_agent_edd_info_by_agent_id(**item_data)
                Log.info(f"{log_tag} update_uploads: {update_uploads}")
                
                if update_uploads and update_uploads.get("success"):
                    Log.info(f"{log_tag} business update was successful, updating account_status")
                    
                    update_account_status = Agent.update_account_status_by_agent_id(
                        agent_id,
                        client_ip,
                        'edd_questionnaire',
                        True
                    )
                    
                    Log.info(f"{log_tag} update_account_status: {update_account_status}")
                    if update_account_status and update_account_status.get("success"):
                        return prepared_response(True, "OK", update_account_status.get("message"))
                    else: 
                        return prepared_response(False, "BAD_REQUEST", update_account_status.get("message"))
                    
                else:
                    #delete uploaded files
                    if edd_questionnaire_path:
                        os.remove(edd_questionnaire_path)
                        
                    if update_uploads and not update_uploads.get("success"):
                        
                        message  = update_uploads.get("message")
                        
                        return prepared_response(False, "BAD_REQUEST", message)
                        
                    return prepared_response(False, "BAD_REQUEST", "Directors ID information could not be upated")
            except Exception as e:
                #delete uploaded files
                if edd_questionnaire_path:
                    os.remove(edd_questionnaire_path)
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
        else:
            return prepared_response(False, "UNAUTHORIZED", f"Unauthorized")

# -----------------------AGENT LOGIN INITIATE-----------------------------------------
@blp_agent_login.route("/login/initiate", methods=["POST"])
class AgentLoginInitiateResource(MethodView):
     # POST Agent (Login agent)
    @blp_agent_registration.arguments(AgentLoginInitSchema, location="form")
    @blp_agent_registration.response(200, AgentLoginInitSchema)
    @blp_agent_registration.doc(
        summary="Initiate Agent Login",
        description="""
            This endpoint allows you to initiate the login process for an agent by verifying their phone number 
            (username) and country ISO2 code.

            The request must include an `Authorization` header with a Bearer token.

            - **POST**: Submit the agent's `username` (phone number) and `country_iso_2` to initiate login. 
            An OTP will be sent to the provided phone number.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentRegistrationInitSchema,
                    "example": {
                        "username": "07568983843",
                        "country_iso_2": "gb"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "OTP has been sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "OTP has been sent",
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
        log_tag = '[people_resource.py][AgentLoginInitiateResource][post]'
        """Handle the POST request to initiate agent login process."""
        client_ip = request.remote_addr
        agent_check= {}
        system_user= {}
        
        try:
            country_iso_2 = item_data.get("country_iso_2")
            country_iso_2_upper = str.upper(country_iso_2)
            
            username = validate_and_format_phone_number(item_data.get("username"), country_iso_2_upper)
            
            if username:
                # Check if the agent exists before attempting to login
                Log.info(f"{log_tag}[{client_ip}][{username}] checking if agent already exists")
                
                try:
                    agent_check = Agent.get_by_username(username)
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] not super_admin agent")
                
                try:
                    system_user = SystemUser.get_by_phone_number(username)
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] not system_user agent")
                        
                
                if not agent_check and not system_user:
                    Log.info(f"{log_tag}[{client_ip}] agent do not exists")
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                        "message": "Account not found."
                    }), HTTP_STATUS_CODES["NOT_FOUND"]
                    
                try:
                    Log.info(f"{log_tag}[{client_ip}] retrieving tenant with: {country_iso_2_upper} ") 
                    
                    tenant = Essensial.get_tenant_by_iso_2(country_iso_2_upper)
                    if tenant:
                        tenant_id = tenant.get("id")
                        Log.info(f"{log_tag}[{client_ip}] initiating login one: {username} ") 
                        
                        # sending OTP
                        shop_service = ShopApiService(tenant_id)
                        
                        automated_test_username = os.getenv("AUTOMATED_TEST_USERNAME")
                        app_mode = os.getenv("APP_RUN_MODE")
                        
                        # needed for automated testing
                        if (username == automated_test_username) or (app_mode =='development'):
                            automated_test_otp = os.getenv("AUTOMATED_TEST_OTP")
                            
                            pin = automated_test_otp
                            
                            message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                            redisKey = f'agent_otp_token_{username}'
                            set_redis_with_expiry(redisKey, 300, pin)
                        
                            set_redis_with_expiry("automate_test_username", 300, username)
                            set_redis_with_expiry("otp_token_automated_test", 300, pin)
                            
                            Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] AUTOMATED TESTING OTP")
                            return jsonify({
                                "success": True,
                                "status_code": HTTP_STATUS_CODES["OK"],
                                "message": "OTP has been sent",
                            }), HTTP_STATUS_CODES["OK"]
                            # needed for automated testing
                        else:
                            pin = generate_otp()
                            message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                            redisKey = f'agent_otp_token_{username}'
                            set_redis_with_expiry(redisKey, 300, pin)
                        
                            Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] sending OTP")
                            response = shop_service.send_sms(username, message, tenant_id)
                            Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                            
                            # return response
                            if response.get("status_code") == 500:
                                return jsonify(response)
                            
                            if response and response.get("status") == "success":
                                return jsonify({
                                    "success": True,
                                    "status_code": HTTP_STATUS_CODES["OK"],
                                    "message": "OTP has been sent",
                                }), HTTP_STATUS_CODES["OK"]
                                
                            else:
                                return jsonify({
                                    "success": False,
                                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                                    "message": "Could not send OTP",
                                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                            
                    else:
                        return jsonify({
                            "success": False,
                            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                            "message": "Could not retrieve tenant",
                        }), HTTP_STATUS_CODES["BAD_REQUEST"]
                    
                    
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] error retrieving tenant with: {country_iso_2_upper}: Error: {str(e)}") 
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                        "message": "An unexpected error occurred while retrieving tenant",
                        "error": str(e)
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
            else:
                return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                        "message": "Invalid phone number",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -----------------------AGENT LOGIN INITIATE-----------------------------------------
@blp_agent_login.route("/login/execute", methods=["POST"])
class AgentLoginExecuteResource(MethodView):
     # POST Agent (Login agent)
    @blp_agent_registration.arguments(AgentLoginExecuteSchema, location="form")
    @blp_agent_registration.response(200, AgentLoginExecuteSchema)
    @blp_agent_registration.doc(
        summary="Initiate Agent Login",
        description="""
            This endpoint allows you to initiate the login process for an agent by verifying their phone number 
            (username) and country ISO2 code.

            The request must include an `Authorization` header with a Bearer token.

            - **POST**: Submit the agent's `username` (phone number) and `country_iso_2` to initiate login. 
            An OTP will be sent to the provided phone number.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": AgentRegistrationInitSchema,
                    "example": {
                        "username": "07568983843",
                        "country_iso_2": "gb"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "OTP has been sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "OTP has been sent",
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
        log_tag = '[people_resource.py][AgentLoginExecuteResource][post]'
        """Handle the POST request to execute agent login process."""
        client_ip = request.remote_addr
        agent_id = None
        user = {}
        
        try:
            country_iso_2 = item_data.get("country_iso_2")
            country_iso_2_upper = str.upper(country_iso_2)
            
            username = validate_and_format_phone_number(item_data.get("username"), country_iso_2_upper)
            
            if username:
                # Check if the agent exists before attempting to login
                try:
                    agent_check = Agent.get_by_username(username)
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] not super_admin agent")
                
                try:
                    system_user = SystemUser.get_by_phone_number(username)
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] not system_user agent")
                        
                
                Log.info(f"{log_tag}[{client_ip}] checking if agent already exists")
                if not agent_check and not system_user:
                    Log.info(f"{log_tag}[{client_ip}] agent do not exists")
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                        "message": "Account not found."
                    }), HTTP_STATUS_CODES["NOT_FOUND"]
                    
                try:
                    Log.info(f"{log_tag}[{client_ip}] initiating verify otp for: {username} ")
                        
                    otp = item_data.get("otp")
            
                    redisKey = f'agent_otp_token_{username}'
                    
                    token_byte_string = get_redis(redisKey)
                    
                    if not token_byte_string:
                        return prepared_response(False, "UNAUTHORIZED", f"The OTP has expired")
                    
                    # Decode the byte string and convert to integer
                    token = token_byte_string.decode('utf-8')
                    
                    if str(otp) != str(token):
                        Log.info(f"{log_tag}[otp: {otp}][token: {token}] verification failed" )
                        return prepared_response(False, "UNAUTHORIZED", f"The OTP is not valid")
                    else:
                        Log.info(f"{log_tag} verification otp applied")
                        agent = Agent.get_by_phone_number(username)
                        
                        try:
                            system_user = SystemUser.get_by_phone_number(username)
                            # Log.info(f"system_user: {system_user}")
                        except Exception as e:
                            Log.info(f"{log_tag}[{client_ip}] not system_user agent")
                                
                        
                        if agent:
                            agent["_id"] = str(agent["_id"])
                            agent["business_id"] = str(agent.get("business_id"))
                            agent_id = agent["_id"]
                            
                            Log.info(f"{log_tag} agent_id: {agent_id}")
                            
                            try:
                                user = User.get_user_by_agent_id(agent_id)
                            except Exception as e:
                                Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving for user: {e}")
                                
                            if user:
                                return create_token_response_super_agent(user=user,agent_id=agent_id, client_ip=client_ip, log_tag=log_tag, redisKey=redisKey)
                                
                            else:
                                Log.info(f"{log_tag}[{client_ip}] user not found for : {username}") 
                                return jsonify({
                                    "success": False,
                                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                                    "message": f"User not found for {username}",
                                }), HTTP_STATUS_CODES["NOT_FOUND"]
                                
                        elif system_user:
                        
                            system_user_id = system_user["system_user_id"]
                            
                            try:
                                s_user = User.get_user_by_system_user_id(system_user_id)
                            except Exception as e:
                                Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving for system user: {e}")
                                
                            if s_user:
                                # Log.info(f"system_user: {system_user}")
                                agent_id = system_user["agent_id"]
                                # s_user["_id"] = str(system_user["_id"])
                                s_user["business_id"] = str(system_user.get("business_id"))
                                Log.info(f"system_user info: {s_user}")
                                return create_token_response_system_user(s_user, agent_id, client_ip, log_tag, redisKey)
                                
                            else:
                                Log.info(f"{log_tag}[{client_ip}] user not found for : {username}") 
                                return jsonify({
                                    "success": False,
                                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                                    "message": f"User not found for {username}",
                                }), HTTP_STATUS_CODES["NOT_FOUND"]
                            
                        else:
                            Log.info(f"{log_tag}[{client_ip}] agent not found for : {username}") 
                            return jsonify({
                                "success": False,
                                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                                "message": f"Agent not found for {username}",
                            }), HTTP_STATUS_CODES["NOT_FOUND"]
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] error verifying otp for : {username} and {country_iso_2_upper}: Error: {str(e)}") 
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                        "message": "An unexpected error occurred while verifying otp",
                        "error": str(e)
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
            else:
                return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                        "message": "Invalid phone number",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


def commit_agent_user(log_tag, client_ip, user_data, email, account_status, agent_id):
    # Check if the agent already exists based on username
    Log.info(f"{log_tag}[{client_ip}] checking if agent already exists")
    if User.get_user_by_email(email):
        # If agent exists, delete the uploaded image before returning conflict response
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["CONFLICT"],
            "message": "Account already exists"
        }), HTTP_STATUS_CODES["CONFLICT"]
                
    Log.info(f"{log_tag}[{client_ip}][committing agent user")
    # committing user data to db
    user = User(**user_data)
    user_client_id = user.save()
    if user_client_id:
        return jsonify({
            "success": True,
            "status_code": HTTP_STATUS_CODES["OK"],
            "agent_id": str(agent_id),
            "message": f"Agent was created",
            "account_status": account_status
        }), HTTP_STATUS_CODES["OK"] 
    else:
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["OK"],
            "message": f"Agent could not be created",
        }), HTTP_STATUS_CODES["OK"]
        
        
def create_token_response_super_agent(user, agent_id, client_ip, log_tag, redisKey):
    user_data = {}
    permissions = {}
    
    user.pop("password", None) # remove password from user object
                                
    user_data["agent_id"] = str(user['agent_id'])
    
    user_data["business_id"] = str(user['business_id'])
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    
    user_data["role"] = decrypt_data(user.get("role")) if user.get("role") else None
    user_data["type"] = user.get("type") if user.get("type") else None
    user_data["account_type"] = user.get("account_type") if user.get("account_type") else None
    user_data["fullname"] = decrypt_data(user.get("fullname")) if user.get("fullname") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    
    client_id = decrypt_data(user.get("client_id"))
    
    try:
        role_id = user.get("role") if user.get("role") else None
        
        role = None
        
        if role_id:
            role =  Role.get_by_id(role_id)
        
        if role:
            # retreive the permissions for the user
            permissions = role.get("permissions")
    except Exception as e:
        Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving permissions for user: {e}")


    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("AGENT_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE")
    refresh_time_to_live = os.getenv("AGENT_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE")
    Token.create_token(client_id, access_token, refresh_token, access_token_time_to_live, refresh_time_to_live) # change to 900 before prod
    
    # remove token from redis
    # remove_redis(redisKey)
    
    
    # Token is for 24 hours
    if agent_id:
        return jsonify({
            'access_token': access_token, 
            'token_type': 'Bearer', 
            'expires_in': access_token_time_to_live, 
            "fullname": user_data.get("fullname"),
            "agent_id": str(agent_id)
            }) # change to 900 on prod
    else:
        return jsonify({'access_token': access_token, 'token_type': 'Bearer', 'expires_in': access_token_time_to_live, "fullname": user_data.get("fullname")}) # change to 900 on prod

def create_token_response_system_user(user, agent_id, client_ip, log_tag, redisKey):
    user_data = {}
    permissions = {}
    
    user.pop("password", None) # remove password from user object
                                
    user_data["agent_id"] = str(agent_id)
    
    user_data["business_id"] = str(user['business_id'])
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    
    user_data["role"] = str(user.get("role")) if user.get("role") else None
    user_data["type"] = encrypt_data('Agent')
    user_data["account_type"] = user.get("account_type") if user.get("account_type") else None
    user_data["fullname"] = decrypt_data(user.get("fullname")) if user.get("fullname") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    
    # return jsonify(user_data)
    
    client_id = decrypt_data(user.get("client_id"))
    
    try:
        role_id = user.get("role") if user.get("role") else None
        
        role = None
        
        if role_id:
            role =  Role.get_by_id(role_id)
        
        if role:
            # retreive the permissions for the user
            permissions = role.get("permissions")
    except Exception as e:
        Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving permissions for user: {e}")

    

    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("AGENT_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE")
    refresh_time_to_live = os.getenv("AGENT_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE")
    Token.create_token(client_id, access_token, refresh_token, access_token_time_to_live, refresh_time_to_live) # change to 900 before prod
    
    # remove token from redis
    # remove_redis(redisKey)

    # Token is for 24 hours
    return jsonify({'access_token': access_token, 'token_type': 'Bearer', 'expires_in': access_token_time_to_live, "fullname": user_data.get("fullname")}) # change to 900 on prod 
