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
from bson import ObjectId
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue

from datetime import datetime, timedelta
#helper functions
from ....utils.amounts import parse_amount, format_underscored
from ....utils.helpers import generate_tokens
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.helpers import validate_and_format_phone_number
from ....utils.json_response import prepared_response
from ....utils.essentials import Essensial
from ....utils.generators import generate_confirm_email_token
from ....services.wallet_service import (
    list_accounts,
    seed_treasury_once_opening_balance,
    credit_initial_float,
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
    get_agent_account,
    list_holds
)
from ....utils.agent_balance_keys import (
    keys_for_init0,
    keys_for_treasury_seed,
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)
from tasks import send_user_registration_email
#helper functions

from .admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....constants.service_code import (
    HTTP_STATUS_CODES, PERMISSION_FIELDS_FOR_ADMINS, PERMISSION_FIELDS_FOR_ADMIN_ROLE,
    PERMISSION_FIELDS_FOR_AGENT_ROLE
)
from ....models.business_model import Client, Token

# schemas
from ....schemas.doseal.username_schema import (
    UpdateUsernameSchema, GetAgentQuerySchema, UpdateAgentAccountBalanceSchema,
    TreasureInitialTopupSchema, TreasurePlaceHoldSchema, TreasureCaptureHoldSchema,
    TreasureRefundCaptureSchema, TreasureReleaseHoldSchema, GetAgentsQuerySchema,
    GetAgentByAgentIdQuerySchema,TreasureGetAgentAccountSchema,
    TreasureGetAccountsSchema
)
from ....schemas.login_schema import LoginSchema
# models
from ....models.admin.super_superadmin_model import (
    Role, Expense, Admin
)

from app.models.business_model import Business
from app.models.user_model import User
from app.models.people_model import Agent
blp_agent_management= Blueprint("Agent Management", __name__,  description="Agent Management")


# -----------------------------UPDATE AGENT PHONE NUMBER-----------------------------------
@blp_agent_management.route("/upate-agent-username", methods=["POST"])
class UpdateAgentUsernameResource(MethodView):
    @token_required
    @blp_agent_management.arguments(UpdateUsernameSchema, location="form")
    @blp_agent_management.response(200, UpdateUsernameSchema)
    @blp_agent_management.doc(
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
        username = user_data.get("username")
        country_iso_2 = user_data.get("country_iso_2")
        
        
        user_info = g.get("current_user", {})
        admin_id = str(user_info.get("_id"))
        
        log_tag = '[admin_agent_management_resource][UpdateAgentUsernameResource][post]'
        
        username = validate_and_format_phone_number(username, country_iso_2)
        
        
        Log.info(f"{log_tag} [{client_ip}][{admin_id}][{username}] initiating update agent username")
        
        if not username:
            Log.info(f"{log_tag} Invalid phone number of {country_iso_2}")
            return prepared_response(False, "BAD_REQUEST", f"Invalid phone number of {country_iso_2}")
    
        # Check if the agent exists based on username
        agent = Agent.get_by_phone_number(username)
        # Log.info(f"agent: {agent}")
        if  agent is None:
            error_message = f"Agent with username {username} does not exists"
            Log.info(f"{log_tag} [{client_ip}][{username}]: {error_message}")
            return prepared_response(False, "NOT_FOUND", f"{error_message}")
        
        update_data = dict()
        update_data["username"] = username
        update_data["business_id"] = user_info.get("business_id")
        agent_id = str(agent["_id"])
        
        try:
            update = Agent.update_info_agent_by_id(agent_id, **update_data)
            if update:
                Log.info(f"{log_tag} Agent username updated successfully: {update}")
                return prepared_response(True, "OK", f"Agent username updated successfully")
            else:
                return jsonify({"message": "Error"})
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error updating agent username: {str(e)}")
        

# -----------------------------GET AGENT BY USERNAME-----------------------------------
@blp_agent_management.route("/agent", methods=["GET"])
class GetAgentByUsernameResource(MethodView):
    @token_required
    @blp_agent_management.arguments(GetAgentQuerySchema, location="query")
    @blp_agent_management.response(200, GetAgentQuerySchema)
    @blp_agent_management.doc(
        summary="Retrieve Agent by Username and Business ID",
        description="""
            This endpoint retrieves the details of an agent by their `username` and the associated `business_id`.  
            Both `username` and `business_id` are required query parameters.
        """,
        parameters=[
            {
                "in": "query",
                "name": "username",
                "required": True,
                "schema": {
                    "type": "string",
                },
                "description": "The username of the agent"
            },
            {
                "in": "query",
                "name": "business_id",
                "required": True,
                "schema": {
                    "type": "string",
                },
                "description": "The business ID associated with the agent"
            }
        ],
        responses={
            200: {
                "description": "Agent retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": {
                                "_id": "6899fde0df447d896f1f1c3f",
                                "account_status": [
                                    {
                                        "account_verified": {
                                            "created_at": "2025-08-11 14:27:44.304812",
                                            "ip_address": "127.0.0.1",
                                            "status": True
                                        }
                                    },
                                    {
                                        "choose_pin": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "basic_kyc_added": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "business_email_verified": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "uploaded_agent_id_info": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "uploaded_director_id_info": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "registration_completed": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "onboarding_in_progress": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "edd_questionnaire": {
                                            "status": False
                                        }
                                    }
                                ],
                                "agent_id": None,
                                "alt_email": None,
                                "alt_phone_number": None,
                                "balance": 0,
                                "balance_update_status": None,
                                "business_id": "686e2724393fbd6408c7a83a",
                                "created_at": "Mon, 11 Aug 2025 15:27:44 GMT",
                                "date_of_birth": None,
                                "device_uuid": None,
                                "first_name": None,
                                "identification": None,
                                "last_name": None,
                                "middle_name": None,
                                "post_code": None,
                                "referral_code": None,
                                "referrals": [],
                                "referrer": None,
                                "remote_ip": None,
                                "request": None,
                                "tenant_id": "1",
                                "transactions": 0,
                                "updated_at": "Mon, 11 Aug 2025 15:27:44 GMT",
                                "user__id": None,
                                "user_id": "71033956",
                                "username": "447015551029"
                            },
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Validation error - Missing or invalid query parameters",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Username is required"
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
                "description": "Internal server error",
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
    def get(self, user_data):

        client_ip = request.remote_addr
        username = user_data.get("username")
        agent_id = user_data.get("agent_id")
        business_id = user_data.get("business_id")
        
        user_info = g.get("current_user", {})
        admin_id = user_info.get("_id")
        
        agent = None
        
        log_tag = f"[admin_agent_management_resource][GetAgentByUsernameResource][get][{client_ip}][{username}][{business_id}]"

        Log.info(f"{log_tag} retrieving agent by username")
        Log.info(f"{log_tag} retrieved by: {admin_id}")

        try:
            # Record start time for performance monitoring
            start_time = time.time()
            
            schema = GetAgentQuerySchema()
            
            try:
                # This will trigger field-level and schema-level validation
                validated_data = schema.load(user_data)
                print("Valid!", validated_data)
            except ValidationError as err:
                print("Errors:", err.messages)

            
            # Attempt to retrieve agent by agent_id
            if agent_id is not None:
                agent = Agent.get_by_id_and_business_id(agent_id=agent_id, business_id=business_id)


            # Attempt to retrieve agent by username
            if username is not None:
                agent = Agent.get_by_username_and_business_id(username=username, business_id=business_id)

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"{log_tag} retrieving agent completed in {duration:.2f} seconds")

            # If no agent is found for the given agent_id
            if not agent:
                Log.info(f"{log_tag} Agent not found")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "Agent not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            # Log the retrieval request
            Log.info(f"{log_tag} agent found")

            # Return the agent data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": agent
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} An unexpected error occurred while retrieving the agent. {str(e)}")
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
                "message": "Error retrieving agent",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -----------------------------GET AGENTS-----------------------------------
@blp_agent_management.route("/agents", methods=["GET"])
class GetAgentsByUsernameResource(MethodView):
    @token_required
    @blp_agent_management.arguments(GetAgentsQuerySchema, location="query")
    @blp_agent_management.response(200, GetAgentsQuerySchema)
    @blp_agent_management.doc(
        summary="Retrieve Agent by Username and Business ID",
        description="""
            This endpoint retrieves the details of an agent by their `username` and the associated `business_id`.  
            Both `username` and `business_id` are required query parameters.
        """,
        parameters=[
            {
                "in": "query",
                "name": "username",
                "required": True,
                "schema": {
                    "type": "string",
                },
                "description": "The username of the agent"
            },
            {
                "in": "query",
                "name": "business_id",
                "required": True,
                "schema": {
                    "type": "string",
                },
                "description": "The business ID associated with the agent"
            }
        ],
        responses={
            200: {
                "description": "Agent retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": {
                                "_id": "6899fde0df447d896f1f1c3f",
                                "account_status": [
                                    {
                                        "account_verified": {
                                            "created_at": "2025-08-11 14:27:44.304812",
                                            "ip_address": "127.0.0.1",
                                            "status": True
                                        }
                                    },
                                    {
                                        "choose_pin": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "basic_kyc_added": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "business_email_verified": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "uploaded_agent_id_info": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "uploaded_director_id_info": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "registration_completed": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "onboarding_in_progress": {
                                            "status": False
                                        }
                                    },
                                    {
                                        "edd_questionnaire": {
                                            "status": False
                                        }
                                    }
                                ],
                                "agent_id": None,
                                "alt_email": None,
                                "alt_phone_number": None,
                                "balance": 0,
                                "balance_update_status": None,
                                "business_id": "686e2724393fbd6408c7a83a",
                                "created_at": "Mon, 11 Aug 2025 15:27:44 GMT",
                                "date_of_birth": None,
                                "device_uuid": None,
                                "first_name": None,
                                "identification": None,
                                "last_name": None,
                                "middle_name": None,
                                "post_code": None,
                                "referral_code": None,
                                "referrals": [],
                                "referrer": None,
                                "remote_ip": None,
                                "request": None,
                                "tenant_id": "1",
                                "transactions": 0,
                                "updated_at": "Mon, 11 Aug 2025 15:27:44 GMT",
                                "user__id": None,
                                "user_id": "71033956",
                                "username": "447015551029"
                            },
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Validation error - Missing or invalid query parameters",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Username is required"
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
                "description": "Internal server error",
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
        admin_id = user_info.get("_id")
        business_id = item_data.get("business_id")
        
        log_tag = f"[admin_agent_management_resource][GetAgentsByUsernameResource][get][{client_ip}][{business_id}]"

        Log.info(f"{log_tag} retrieving agent by business_id")
        Log.info(f"{log_tag} retrieved by: {admin_id}")

        try:
            # Record start time for performance monitoring
            start_time = time.time()

            # Attempt to retrieve agent by agent_id
            agents = Agent.get_agents_business_id(
                business_id=business_id,
                page=item_data.get("page"),
                per_page=item_data.get("per_page"),
            )

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"{log_tag} retrieving agents completed in {duration:.2f} seconds")

            # If no agent is found for the given agent_id
            if not agents:
                Log.info(f"{log_tag} Agents not found")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "Agents not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            # Log the retrieval request
            Log.info(f"{log_tag} agents found")

            # Return the agents data as a response
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": agents
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} An unexpected error occurred while retrieving the agents. {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while retrieving the agents.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Error retrieving agent",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -----------------------------TREASURE INITIAL TOP-UP-----------------------------------
@blp_agent_management.route("/treasure-initial-top-up", methods=["POST"])
class TreasureInitialTopupResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureInitialTopupSchema, location="form")
    @blp_agent_management.response(200, TreasureInitialTopupSchema)
    @blp_agent_management.doc(
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
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        amt = user_data.get("amount")
        amount_dec = format_underscored(amt) 
        
        admin_id = user_info.get("_id")
        user_id = str(user_info.get("_id"))
        
        log_tag = f'[admin_agent_management_resource][TreasureInitialTopupResource][post][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag}  treasury topping up initial business balance")
        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            k = keys_for_treasury_seed(business_id)
            response = seed_treasury_once_opening_balance(
                business_id=ObjectId(business_id),
                amount=amount_dec,
                seeded_by=ObjectId(user_id), 
                idempotency_key=k.idem,
                reference=k.ref,
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Agent has been funded successfully")
                return jsonify(response)
            if response.get("status_code") == 409:
                Log.info(f"{log_tag} Treasury initial funding failed: {response} ")
                return jsonify(response)
            else:
                Log.info(f"{log_tag} Treasury initial funding failed")
                return prepared_response(False, "BAD_REQUEST", f"Treasury initial funding failed")

        except Exception as e:
            Log.error(f"{log_tag} Error performing treasure initial top-up: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Error performing treasure initial top-up",
                "error_code": str(e)
            })
       
    
# -----------------------------TREASURE CREDIT FLOAT-----------------------------------
@blp_agent_management.route("/treasure-credit-float", methods=["POST"])
class TreasureCreateCreditFloatResource(MethodView):
    @token_required
    @blp_agent_management.arguments(UpdateAgentAccountBalanceSchema, location="form")
    @blp_agent_management.response(200, UpdateAgentAccountBalanceSchema)
    @blp_agent_management.doc(
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
        business_id = user_data.get("business_id")
        agent_id = user_data.get("agent_id")
        amt = user_data.get("amount")
        
        user_info = g.get("current_user", {})
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureCreateCreditFloatResource][post][{client_ip}][{admin_id}][{business_id}][{agent_id}]'
        
        Log.info(f"{log_tag}  initiating treasure create credit float")
        
        try:
            # Attempt to retrieve agent by agent_id
            agent = Agent.get_by_id_and_business_id(agent_id=agent_id, business_id=business_id)
            if agent is None:
                Log.info(f"{log_tag} Agent not found!")
                return prepared_response(False, "BAD_REQUEST", f"Agent not found!")
            
            funding_request_id = f"{admin_id}:{str(ObjectId()) }"
            
            k = keys_for_funding(business_id, agent_id, funding_request_id, amt)
            
            Log.info(f"{log_tag} funded by: {admin_id}{amt}")
            
            response = credit_initial_float(
                business_id=business_id, 
                agent_id=agent_id, 
                amount=amt, 
                idempotency_key=k.idem, 
                reference=k.ref
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Agent has been funded successfully")
                return jsonify(response)
            else:
                return prepared_response(False, "BAD_REQUEST", f"Agent could not be funded!")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error funding agent: {str(e)}")
        
        
# -----------------------------TREASURE PLACE HOLD-----------------------------------
@blp_agent_management.route("/treasure-place-hold", methods=["POST"])
class TreasurePlaceHoldResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasurePlaceHoldSchema, location="form")
    @blp_agent_management.response(200, TreasurePlaceHoldSchema)
    @blp_agent_management.doc(
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
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        agent_id = user_data.get("agent_id")
        internal_reference = user_data.get("internal_reference")
        purpose = user_data.get("purpose")
        amt = user_data.get("amount")
        amount_dec = format_underscored(amt) 
        
        admin_id = user_info.get("_id")
        user_id = str(user_info.get("_id"))
        
        log_tag = f'[admin_agent_management_resource][TreasurePlaceHoldResource][post][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag}  treasury topping up initial business balance")
        
        try:
            # Attempt to retrieve agent by agent_id
            agent = Agent.get_by_id(agent_id)
            if not agent:
                return prepared_response(False, "BAD_RNOT_FOUNDEQUEST", f"Agent not found")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error getting agent: {str(e)}")
       
        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            k = keys_for_hold(business_id, agent_id, client_ref=internal_reference, amount=amount_dec)
            response = place_hold(
                business_id=business_id,
                agent_id=agent_id,
                amount=amount_dec,     
                idempotency_key=k.idem,
                ref=k.ref,
                purpose=purpose,
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Agent ledger position put to hold successfully")
                return jsonify(response)
            else:
                return prepared_response(False, "BAD_REQUEST", f"Agent ledger position putting to hold failed")

        except Exception as e:
            Log.error(f"{log_tag} Error putting agent ledger position on hold: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Error putting agent ledger position on hold",
                "error_code": str(e)
            })
       

# -----------------------------TREASURE CAPTURE HOLD-----------------------------------
@blp_agent_management.route("/treasure-capture-hold", methods=["POST"])
class TreasureCaptureHoldResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureCaptureHoldSchema, location="form")
    @blp_agent_management.response(200, TreasureCaptureHoldSchema)
    @blp_agent_management.doc(
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
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        hold_id = user_data.get("hold_id")
        payout_network_account = user_data.get("payout_network_account")
        
        
        log_tag = f'[admin_agent_management_resource][TreasureCaptureHoldResource][post][{client_ip}][{business_id}]'

        Log.info(f"{log_tag}  releasing capture hold")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            k = keys_for_capture(business_id, hold_id)
            
            response = capture_hold(
                business_id=ObjectId(business_id),
                hold_id=hold_id,  
                idempotency_key=k.idem
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Performing capture hold")
                return jsonify(response)
            else:
                return prepared_response(False, "BAD_REQUEST", f"Capture holding failed")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
   
# -----------------------------TREASURE RELEASE HOLD-----------------------------------
@blp_agent_management.route("/treasure-release-hold", methods=["POST"])
class TreasureReleaseHoldResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureReleaseHoldSchema, location="form")
    @blp_agent_management.response(200, TreasureReleaseHoldSchema)
    @blp_agent_management.doc(
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
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        hold_id = user_data.get("hold_id")
        
        agent_id = str(user_data.get("agent_id"))
        
        
        log_tag = f'[admin_agent_management_resource][TreasureReleaseHoldResource][post][{client_ip}][{business_id}][{agent_id}]'

        Log.info(f"{log_tag}  releasing capture hold")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            k = keys_for_release(business_id, hold_id)
            
            response = release_hold(
                business_id=ObjectId(business_id),
                hold_id=hold_id,    
                idempotency_key=k.idem
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Performing capture hold")
                return jsonify(response)
            else:
                return prepared_response(False, "BAD_REQUEST", f"Capture holding failed")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
           

# -----------------------------TREASURE REFUND HOLD-----------------------------------
@blp_agent_management.route("/treasure-refund-capture", methods=["POST"])
class TreasureRefundCaptureResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureRefundCaptureSchema, location="form")
    @blp_agent_management.response(200, TreasureRefundCaptureSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureRefundCaptureSchema,  # Assuming you have a LoginSchema to validate the input data
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
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        original_txn_id = user_data.get("original_txn_id")
        reason = user_data.get("reason")
        
        admin_id = user_info.get("_id")
        user_id = str(user_info.get("_id"))
        
        log_tag = f'[admin_agent_management_resource][TreasureRefundCaptureResource][post][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} refund capture")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            k = keys_for_refund(business_id, original_txn_id, reason=reason)
            
            response = refund_capture(
                business_id=business_id,
                original_txn_id=original_txn_id,
                reason=reason,     
                idempotency_key=k.idem
            )
            
            if response.get("status_code") == 200:
                Log.info(f"{log_tag} Performing capture hold")
                return jsonify(response)
            else:
                return prepared_response(False, "BAD_REQUEST", f"Capture holding failed")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       

# -----------------------------TREASURE GET AGENT ACCOUNT-----------------------------------
@blp_agent_management.route("/treasure-agent-account", methods=["GET"])
class TreasureAgentAccountResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureGetAgentAccountSchema, location="query")
    @blp_agent_management.response(200, TreasureGetAgentAccountSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureRefundCaptureSchema,  # Assuming you have a LoginSchema to validate the input data
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
    def get(self, user_data):
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        agent_id = user_data.get("agent_id")
        
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureAgentAccountResource][get][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} get holds")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            
            response = get_agent_account(
                business_id=business_id,
                agent_id=agent_id,
            )
            
            if response is not None:
                Log.info(f"{log_tag} retrieved agent data")
                response["business_id"] = str(response.get("business_id"))
                response["agent_id"] = str(response.get("agent_id"))
                response["_id"] = str(response.get("_id"))
                response["owner_id"] = str(response.get("owner_id"))
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "data": response
                }), HTTP_STATUS_CODES["OK"]
            else:
                return prepared_response(False, "BAD_REQUEST", f"No Account found for agent")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       
# -----------------------------TREASURE GET AGENT ACCOUNT-----------------------------------
@blp_agent_management.route("/treasure-agent-accounts", methods=["GET"])
class TreasureAgentAccountResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureGetAccountsSchema, location="query")
    @blp_agent_management.response(200, TreasureGetAccountsSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureGetAccountsSchema,  # Assuming you have a LoginSchema to validate the input data
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
    def get(self, user_data):
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureAgentAccountResource][get][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} get holds")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            
            response = list_accounts(
                business_id=business_id,
                type_= user_data.get("type")
            )
            
            if response is not None:
                Log.info(f"{log_tag} retrieved agent accounts")
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "data": response
                }), HTTP_STATUS_CODES["OK"]
            else:
                return prepared_response(False, "BAD_REQUEST", f"No Account found for agent")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       

# -----------------------------TREASURE ACCOUNT-----------------------------------
@blp_agent_management.route("/treasure-account", methods=["GET"])
class TreasureAccountResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureGetAccountsSchema, location="query")
    @blp_agent_management.response(200, TreasureGetAccountsSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureGetAccountsSchema,  # Assuming you have a LoginSchema to validate the input data
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
    def get(self, user_data):
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureAccountResource][get][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} get holds")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            
            response = list_accounts(
                business_id=business_id,
                type_= "TREASURY"
            )
            
            if response is not None:
                Log.info(f"{log_tag} retrieved agent treasurer")
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "data": response
                }), HTTP_STATUS_CODES["OK"]
            else:
                return prepared_response(False, "BAD_REQUEST", f"No Account found for agent")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       

# -----------------------------TREASURE CLEARNING-----------------------------------
@blp_agent_management.route("/treasure-clearing", methods=["GET"])
class TreasureClearingResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureGetAccountsSchema, location="query")
    @blp_agent_management.response(200, TreasureGetAccountsSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureGetAccountsSchema,  # Assuming you have a LoginSchema to validate the input data
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
    def get(self, user_data):
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureClearingResource][get][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} get holds")

        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            
            response = list_accounts(
                business_id=business_id,
                type_= "CLEARING"
            )
            
            if response is not None:
                Log.info(f"{log_tag} retrieved treasure clearing")
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "data": response
                }), HTTP_STATUS_CODES["OK"]
            else:
                return prepared_response(False, "BAD_REQUEST", f"No Account found for treasurer")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       

# -----------------------------TREASURE LIST HOLDS-----------------------------------
@blp_agent_management.route("/treasure-list-holds", methods=["GET"])
class TreasureListHoldsResource(MethodView):
    @token_required
    @blp_agent_management.arguments(TreasureGetAccountsSchema, location="query")
    @blp_agent_management.response(200, TreasureGetAccountsSchema)
    @blp_agent_management.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": TreasureGetAccountsSchema,  # Assuming you have a LoginSchema to validate the input data
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
    def get(self, user_data):
        user_info = g.get("current_user", {})
        
        client_ip = request.remote_addr
        
        business_id = user_data.get("business_id")
        
        admin_id = user_info.get("_id")
        
        log_tag = f'[admin_agent_management_resource][TreasureListHoldsResource][get][{client_ip}][{admin_id}][{business_id}]'
          
        Log.info(f"{log_tag} update by: {admin_id}")

        Log.info(f"{log_tag} get holds")
        
        try:
            # check if business_id exist
            bussiness = Business.get_business_by_id(business_id=business_id)
            if bussiness is None:
                Log.info(f"{log_tag} Business not found!")
                return prepared_response(False, "BAD_REQUEST", f"Business not found!")
            
            
            response = list_holds(
                business_id=business_id,
            )
            
            if response is not None:
                Log.info(f"{log_tag} retrieved treasure clearing")
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "data": response
                }), HTTP_STATUS_CODES["OK"]
            else:
                return prepared_response(False, "BAD_REQUEST", f"No Account found for treasurer")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Performing capture hold: {str(e)}")
       






























