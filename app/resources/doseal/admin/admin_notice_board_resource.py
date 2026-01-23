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
from ....schemas.doseal.notice_board_schema import (
    NoticeBoardSchema, NoticeBoardIdQuerySchema, NoticeBoardUpdateSchema,
    NoticeBoardsSchema
)
# models
from ....models.instntmny.notice_board_model import NoticeBoard


blp_notice_board = Blueprint("Notice Board", __name__,  description="Notice Board Management")

# -----------------------------Notice Board-----------------------------------
@blp_notice_board.route("/notice-board", methods=["POST", "GET", "PATCH", "DELETE"])
class RoleResource(MethodView):

    #POST Notice (Post a Notice by user__id)
    @token_required
    @blp_notice_board.arguments(NoticeBoardSchema, location="form")
    @blp_notice_board.response(201, NoticeBoardSchema)
    @blp_notice_board.doc(
        summary="Create a new notice",
        description="""
            This endpoint allows an agent to create a new notice on the notice board. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new notice by providing details such as title, excerpt, and message.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": NoticeBoardSchema,
                    "example": {
                        "title": "New Announcement",
                        "excerpt": "This is a new announcement for our users.",
                        "message": "Here is the full message of the announcement."
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Notice created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Notice created successfully",
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
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to create a new notice."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f"[notice_board_resource][NoticeBoardResource][post][{client_ip}]"

        # Attach business and user IDs from the current user context
        item_data["business_id"] = user_info.get("business_id")
        item_data["user__id"] = user_info.get("_id")
        item_data["user_id"] = user_info.get("user_id")
        item_data["created_by"] = user_info.get("_id")
        
        # Check for duplicate notice based on the title and excerpt
        Log.info(f"{log_tag} checking if notice already exists")
        if NoticeBoard.check_item_exists_business_id(item_data["business_id"], key="title", value=item_data["title"]):
            return prepared_response(False, "CONFLICT", f"Notice with this title already exists.")

        Log.info(f"[setup_resource.py][NoticeBoardResource][post][{client_ip}] item_data")

        # Create a new NoticeBoard instance and save it
        notice = NoticeBoard(**item_data)

        try:
            Log.info(f"[setup_resource.py][NoticeBoardResource][post][{client_ip}][committing notice transaction]")
            start_time = time.time()
            notice_id = notice.save()
            end_time = time.time()

            Log.info(f"[setup_resource.py][NoticeBoardResource][post][{client_ip}][{notice_id}] completed in {end_time - start_time:.2f} sec")

            if notice_id:
                return prepared_response(True, "CREATED", f"Notice created successfully.")

            return prepared_response(False, "BAD_REQUEST", f"Failed to create notice")

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while creating the notice. {str(e)}")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

    #POST Notice (Post a user__id)
    @token_required
    @blp_notice_board.arguments(NoticeBoardIdQuerySchema, location="query")
    @blp_notice_board.response(200, NoticeBoardIdQuerySchema)
    @blp_notice_board.doc(
        summary="Retrieve a notice by notice_id",
        description="""
            This endpoint allows you to retrieve a notice based on the `notice_id` in the query parameters.
            - **GET**: Retrieve a notice by providing `notice_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Notice retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "notice_id": "60a6b938d4d8c24fa0804d62",
                                    "title": "New Announcement",
                                    "excerpt": "This is a new announcement for our users.",
                                    "message": "Here is the full message of the announcement.",
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
    def get(self, notice_data):
        notice_id = notice_data.get("notice_id")

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        log_tag = f"[notice_board_resource.py][NoticeBoardResource][get][{client_ip}][{business_id}][{notice_id}]"

        Log.info(f"[{log_tag}] retrieving notice ")

        # If notice_id is not provided, return a 400 Bad Request
        if not notice_id:
            return prepared_response(False, "BAD_REQUEST", f"notice_id must be provided.")
        
        try:
            # Record start time for performance monitoring
            start_time = time.time()

            # Attempt to retrieve notice by notice_id
            notice = NoticeBoard.get_by_id(business_id=business_id, notice_board_id=notice_id)

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"[{log_tag}][{notice_id}] retrieving notice completed in {duration:.2f} seconds")

            # If no notice is found for the given notice_id
            if not notice:
                return prepared_response(False, "NOT_FOUND", f"Notice not found")

            # Log the retrieval request
            Log.info(f"[setup_resource.py][NoticeBoardResource][get][{client_ip}][{notice_id}] notice found")

            # Return the notice data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": notice
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the notice. {str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

    # PATCH Notice (Update an existing Notice)
    @token_required
    @blp_notice_board.arguments(NoticeBoardUpdateSchema, location="form")
    @blp_notice_board.response(200, NoticeBoardUpdateSchema)
    @blp_notice_board.doc(
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
                    "schema": NoticeBoardUpdateSchema,
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
        notice_id = item_data.get("notice_id")  # notice_id passed in the request body

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        # Assign user_id and business_id from current user
        item_data["user_id"] = user_info.get("user_id")
        business_id = user_info.get("business_id")
        item_data["business_id"] = business_id

        log_tag = f"[notice_board_resource.py][NoticeBoardResource][put][{client_ip}][{business_id}][{notice_id}]"

        Log.info(f"[{log_tag}] updating notice")

        # Check if the notice exists based on notice_id
        notice = NoticeBoard.get_by_id(business_id=business_id, notice_board_id=notice_id)

        if not notice:
            Log.info(f"[{log_tag}][{notice_id}] Notice not found.")
            return prepared_response(False, "NOT_FOUND", f"Notice not found.")

        # Attempt to update the notice data
        try:
            start_time = time.time()

            item_data.pop("notice_id", None)  # Remove the notice_id from the update data

            # Update the notice with the new data
            update = NoticeBoard.update(notice_id, **item_data)

            end_time = time.time()
            duration = end_time - start_time

            if update:
                Log.info(f"{log_tag} update: {update}")
                Log.info(f"[{log_tag}][{notice_id}] updating notice completed in {duration:.2f} seconds")
                
                return prepared_response(True, "OK", f"Notice updated successfully.")
            else:
                Log.info(f"[{log_tag}][{notice_id}] Failed to update notice.")
                return prepared_response(False, "BAD_REQUEST", f"Failed to update notice.")
        except PyMongoError as e:
            Log.info(f"[{log_tag}][{notice_id}] An unexpected error occurred while updating the notice. {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while updating the notice. {str(e)}")
        except Exception as e:
            Log.info(f"[{log_tag}][{notice_id}] An unexpected error occurred. {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")


    # DELETE Notice (Delete an existing Notice)
    @token_required
    @blp_notice_board.arguments(NoticeBoardIdQuerySchema, location="query")
    @blp_notice_board.response(200)
    @blp_notice_board.doc(
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
   
    def delete(self, notice_data):
        notice_id = notice_data.get("notice_id")  # notice_id passed in the query parameters

        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        client_ip = request.remote_addr
        log_tag = f"[notice_board_resource.py][NoticeBoardResource][delete][{business_id}][{client_ip}][{notice_id}]"

        Log.info(f"[{log_tag}] initiated delete notice")

        # Check if notice_id is provided
        if not notice_id:
            return prepared_response(False, "BAD_REQUEST", f"notice_id must be provided.")

        # Retrieve the notice using its notice_id
        notice = NoticeBoard.get_by_id(notice_board_id=notice_id, business_id=business_id)

        if not notice:
            Log.info(f"{log_tag} notice not found")
            return prepared_response(False, "NOT_FOUND", f"Notice not found.")

        # Call the delete method from the NoticeBoard model
        delete_success = NoticeBoard.delete(notice_id, business_id=business_id)

        if delete_success:
            Log.info(f"{log_tag} notice deleted successfully")
            return prepared_response(True, "OK", f"Notice deleted successfully.")
        else:
            Log.info(f"{log_tag} failed to delete notice")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to delete notice.")

@blp_notice_board.route("/notice-boards", methods=["GET"])
class NoticeBoardsResource(MethodView):
    @token_required
    @blp_notice_board.arguments(NoticeBoardsSchema, location="query")
    @blp_notice_board.response(200, NoticeBoardsSchema)
    @blp_notice_board.doc(
        summary="Retrieve notice boards by business_id",
        description="""
            This endpoint allows you to retrieve notice boards based on the `business_id` in the query parameters.
            - **GET**: Retrieve notice boards by providing `business_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Bearer token authentication is required
        responses={
            200: {
                "description": "Notice boards retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "notice_id": "60a6b938d4d8c24fa0804d62",
                                    "title": "New Announcement",
                                    "excerpt": "This is a new announcement for our users.",
                                    "message": "Here is the full message of the announcement.",
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
        """Handle GET request to retrieve notice boards by business_id."""
        client_ip = request.remote_addr
        log_tag = f"[notice_board_resource.py][NoticeBoardsResource][get][{client_ip}]"

        # Get the current user's business_id
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        page = item_data.get("page", None)
        per_page = item_data.get("per_page", None)

        Log.info(f"{log_tag} initiated get notice boards")

        try:
            # Attempt to retrieve notice boards by business_id
            notice_boards = NoticeBoard.get_all(business_id=business_id, page=page, per_page=per_page)

            # If no notice boards are found for the given business_id
            if not notice_boards:
                return prepared_response(False, "NOT_FOUND", "Notice boards not found")

            # Log the retrieval request
            Log.info(f"{log_tag} notice board data found")

            # Return the notice board data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": notice_boards
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the notice boards. {str(e)}")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")





