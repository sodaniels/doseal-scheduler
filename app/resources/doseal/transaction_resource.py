import bcrypt
import jwt
import os
import time
import json
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
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.redis import get_redis
from ...utils.generic import delete_model
from ...utils.validation import validate_payment_details
from ...utils.json_response import prepared_response
from ...utils.pre_transaction_checks import PreTransactionCheck
#helper functions

from ...services.gateways.transaction_gateway_service import TransactionGatewayService
from .admin.admin_business_resource import token_required
from ...utils.logger import Log # import logging
from ...constants.service_code import (
    HTTP_STATUS_CODES, TRANSACTION_GENERAL_REQUIRED_FIELDS
)
from ...services.gateways.gateway_service import GatewayService

# model
from ...models.transaction_model import Transaction
from ...models.people_model import Agent
from ...models.beneficiary_model import Beneficiary
from ...models.sender_model import Sender
from ...models.settings_model import Limit

from ...schemas.transaction_schema import (
     TransactionSchema, TransactionExecuteSchema, SenderdQuerySchema,
     TranactionIdQuerySchema, AgentIdQuerySchema
)



blp_transaction = Blueprint("Tranaction", __name__, description="Tranaction Management")


# # -----------------------TRANACTION-----------------------------------------
# @blp_transaction.route("/transaction/initiate", methods=["POST"])
# class TransactionInitiateResource(MethodView):
#     # POST Transaction (Create a new Transaction)
#     @token_required
#     @blp_transaction.arguments(TransactionSchema, location="json")
#     @blp_transaction.response(200, TransactionSchema)
#     @blp_transaction.doc(
#         summary="Initiate new transaction",
#         description="""
#             This endpoint allows you to create a new transaction. The request requires an `Authorization` header with a Bearer token.
#             - **POST**: Create a new transaction by providing details such as transaction type, payment details, recipient, amount, and optional image file.
#         """,
#         requestBody={
#             "required": True,
#             "content": {
#                 "multipart/form-data": {
#                     "schema": TransactionSchema,
#                     "example": {
#                         "payment_mode": "Bank",
#                         "amount": "100",
#                         "currency_code": "USD",
#                         "transaction_type": "Transfer",
#                         "receiver_msisdn": "987-654-3210",
#                         "receiver_name": "Jane Doe",
#                         "receiver_country_iso2": "US",
#                     }
#                 }
#             },
#         },
#         responses={
#             201: {
#                 "description": "Transaction created successfully",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "message": "Transaction created successfully",
#                             "status_code": 200,
#                             "success": True
#                         }
#                     }
#                 }
#             },
#             400: {
#                 "description": "Invalid request data",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 400,
#                             "message": "Invalid input data"
#                         }
#                     }
#                 }
#             },
#             401: {
#                 "description": "Unauthorized request",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 401,
#                             "message": "Invalid authentication token"
#                         }
#                     }
#                 }
#             },
#             500: {
#                 "description": "Internal Server Error",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 500,
#                             "message": "An unexpected error occurred",
#                             "error": "Detailed error message here"
#                         }
#                     }
#                 }
#             }
#         },
#         security=[{"Bearer": []}],  # Bearer token authentication is required
#     )
#     def post(self, transaction_data):

#         """Handle the POST request to create a new transaction."""
#         client_ip = request.remote_addr
#         user_info = g.get("current_user", {})
#         log_tag = f'[transaction_resource.py][TransactionInitiateResource][post][{client_ip}]'
        
#         business_id = str(user_info.get("business_id"))
#         agent_id = str(user_info.get("agent_id"))
#         user_id = str(user_info.get("user_id"))
        
#         beneficiary_id = str(transaction_data.get("beneficiary_id"))
#         sender_id = str(transaction_data.get("sender_id"))
        
#         # Assign user_id and business_id from current user
#         transaction_data["user_id"] = user_id
#         transaction_data["user__id"] = str(user_info.get("_id"))
#         transaction_data["business_id"] = business_id
#         transaction_data["agent_id"] = agent_id
        
#         # block transaction if not agent
#         if agent_id is None:
#             Log.info(f"{log_tag} This is Agent Only API")
#             return prepared_response(False, "BAD_REQUEST", f"This is Agent Only API") 
        
        
#         #####################PRE TRANSACTION CHECKS#########################
        
#         # 1. check pre transaction requirements for agents
#         pre_transaction_check = PreTransactionCheck(agent_id=agent_id, business_id=business_id)
#         initial_check_result = pre_transaction_check.initial_transaction_checks()
        
#         if initial_check_result is not None:
#             return initial_check_result
        
#         # 2. check if agent has enough balance to cover transaction
#         transaction_balance_check = pre_transaction_check.agent_has_sufficient_available(transaction_data.get("send_amount"))
#         Log.info(f"{log_tag} transaction_balance_check: {transaction_balance_check}")
#         if not transaction_balance_check:
#             Log.info(f"{log_tag} Insufficient funds for this transaction.")
#             return prepared_response(False, "BAD_REQUEST", f"Insufficient funds for this transaction") 
        
#         #####################PRE TRANSACTION CHECKS#########################
        
#         # Ensure beneficiary exist for the particular user
#         try:
#             Log.info(f"{log_tag} Retrieving beneficiary information.")
#             beneficiary = Beneficiary.get_by_id_and_user_id_and_business_id(
#                 beneficiary_id, user_info.get("_id"),business_id,
#             )
#             Log.info(f"{log_tag} beneficiary information loaded successfully")
            
#             if beneficiary is None:
#                 return prepared_response(False, "NOT_FOUND", f"Beneficiary do not exist for this user.") 
            
#         except Exception as e:
#             Log.info(f"{log_tag} error retrieving beneficiary information: {str(e)}")
        
        
#         # Ensure sender exist for the particular user
#         try:
#             Log.info(f"{log_tag} Retrieving sender information.")
#             sender = Sender.get_by_id_and_user_id_and_business_id(
#                 sender_id, 
#                 user_info.get("_id"),
#                 business_id,
#             )
#             Log.info(f"{log_tag} sender information loaded successfully")
            
#             if sender is None:
#                 return prepared_response(False, "NOT_FOUND", f"Sender do not exist for this user.") 
            
#         except Exception as e:
#             Log.info(f"{log_tag} error retrieving sender information: {str(e)}")
            
     
#         # Initializing transaction
#         try:
#             Log.info(f"{log_tag}[{client_ip}] initiatring transaction")
#             transaction_id = None
            
#             response = TransactionGatewayService.initiate_input(transaction_data)
        
#             return response
        
#         except Exception as e:
#             Log.info(f"{log_tag}[{client_ip}][{transaction_id}] error initiatring transaction: {e}")
#             return jsonify({
#                 "success": False,
#                 "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
#                 "message": "An unexpected error occurred while initiating transaction.",
#                 "error": str(e)
#             }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
    
# @blp_transaction.route("/transaction/execute", methods=["POST"])
# class TransactionExecuteResource(MethodView):
#     # POST Beneficiary (Create a new Beneficiary)
#     @token_required
#     @blp_transaction.arguments(TransactionExecuteSchema, location="json")
#     @blp_transaction.response(200, TransactionExecuteSchema)
#     @blp_transaction.doc(
#         summary="Create a new transaction",
#         description="""
#             This endpoint allows you to create a new transaction. The request requires an `Authorization` header with a Bearer token.
#             - **POST**: Create a new transaction by providing details such as transaction type, payment details, recipient, amount, and optional image file.
#         """,
#         requestBody={
#             "required": True,
#             "content": {
#                 "multipart/form-data": {
#                     "schema": TransactionExecuteSchema,
#                     "example": {
#                         "payment_mode": "Bank",
#                         "amount": "100",
#                         "currency_code": "USD",
#                         "transaction_type": "Transfer",
#                         "receiver_msisdn": "987-654-3210",
#                         "receiver_name": "Jane Doe",
#                         "receiver_country_iso2": "US",
#                     }
#                 }
#             },
#         },
#         responses={
#             201: {
#                 "description": "Transaction created successfully",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "message": "Transaction created successfully",
#                             "status_code": 200,
#                             "success": True
#                         }
#                     }
#                 }
#             },
#             400: {
#                 "description": "Invalid request data",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 400,
#                             "message": "Invalid input data"
#                         }
#                     }
#                 }
#             },
#             401: {
#                 "description": "Unauthorized request",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 401,
#                             "message": "Invalid authentication token"
#                         }
#                     }
#                 }
#             },
#             500: {
#                 "description": "Internal Server Error",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "success": False,
#                             "status_code": 500,
#                             "message": "An unexpected error occurred",
#                             "error": "Detailed error message here"
#                         }
#                     }
#                 }
#             }
#         },
#         security=[{"Bearer": []}],  # Bearer token authentication is required
#     )
#     def post(self, transaction_data):

#         """Handle the POST request to create a new transaction."""
#         client_ip = request.remote_addr
#         user_info = g.get("current_user", {})
#         log_tag = f'[transaction_resource.py][TransactionExecuteResource][post][{client_ip}]'
        
#         business_id = str(user_info.get("business_id"))
#         agent_id = str(user_info.get("agent_id"))
        
#         transaction_details = None

#         checksum = transaction_data.get("checksum", None)
#         checksum_hash_transformed = str.lower(checksum)
        
#         try:
#             Log.info(f"{log_tag} retrieving transaction from redis")
#             encrypted_transaction = get_redis(checksum_hash_transformed)
            
#             if encrypted_transaction is None:
#                 message = f"The transaction has expired or the checksum is invalid. Kindly call the 'transactions/initiate' endpoint again and ensure the checksum is valid."
#                 Log.info(f"{log_tag}[{agent_id}] {message}")
#                 return prepared_response(False, "BAD_REQUEST", f"{message}")
            
#             decrypted_transaction = decrypt_data(encrypted_transaction)
            
#             transaction_details = json.loads(decrypted_transaction)
        
            
#             if transaction_details:
                
#                 #####################PRE TRANSACTION CHECKS#########################
#                 if agent_id is not None:
#                     # 1. check pre transaction requirements for agents
#                     pre_transaction_check = PreTransactionCheck(agent_id=agent_id, business_id=business_id)
#                     initial_check_result = pre_transaction_check.initial_transaction_checks()
                    
#                     if initial_check_result is not None:
#                         return initial_check_result
                    
#                     # 2. check if agent has enough balance to cover transaction
#                     amount_details = transaction_details.get("amount_details")
#                     transaction_balance_check = pre_transaction_check.agent_has_sufficient_available(amount_details.get("send_amount"))
#                     Log.info(f"{log_tag} transaction_balance_check: {transaction_balance_check}")
#                     if not transaction_balance_check:
#                         Log.info(f"{log_tag} Insufficient funds for this transaction.")
#                         return prepared_response(False, "BAD_REQUEST", f"Insufficient funds for this transaction") 
                
#                 #####################PRE TRANSACTION CHECKS#########################
                
                
                
#                 transaction_details.pop("checksum", None)
                
#                 agent_id = str(user_info.get("agent_id"))
#                 # Assign user_id and business_id from current user
#                 transaction_details["user_id"] = str(user_info.get("user_id"))
#                 transaction_details["user__id"] = str(user_info.get("_id"))
#                 transaction_details["agent_id"] = agent_id
#                 business_id = str(user_info.get("business_id"))
#                 transaction_details["business_id"] = business_id
#                 transaction_details["checksum"] = checksum_hash_transformed
#                 tenant_id = transaction_details.get("tenant_id")
                
#                 # initialize gateway service with tenant ID
#                 gateway_service = GatewayService(tenant_id)
                
#                 json_response = gateway_service.execute_transaction_execute(**transaction_details)
            
#                 return json_response
#             else:
#                 return prepared_response(False, "BAD_REQUEST", f"Transaction validation failed.")
#         except Exception as e:
#             Log.info(f"{log_tag} error retrieving transaction from redis: {str(e)}")
#             return prepared_response(False, "BAD_REQUEST", f"An eror ocurred while executing transaction. Error: {str(e)}")
     
     
        
@blp_transaction.route("/transactions", methods=["GET"])
class TransactionsByAgentResource(MethodView):
    # GET Aget Transactions (Retrieve by agent_id)
    @token_required
    @blp_transaction.arguments(SenderdQuerySchema, location="query")
    @blp_transaction.response(200, TransactionSchema(many=True))
    @blp_transaction.doc(
        summary="Retrieve transactions by sender_id or agent_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `sender_id` or an `agent_id`.

            - **GET**: Retrieve transactions by providing either `sender_id` or `agent_id` as query parameters.
            - If both are provided, `sender_id` will take precedence.
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `sender_id` (optional): ID of the sender.
            - `agent_id` (optional): ID of the agent (used if `sender_id` is not provided).
            - `page` (optional): Page number for pagination (default is 1).
            - `per_page` (optional): Number of transactions per page (default is 10).
        """,
        parameters=[
            {
                "in": "query",
                "name": "sender_id",
                "schema": {"type": "string"},
                "description": "Sender ID to filter transactions"
            },
            {
                "in": "query",
                "name": "agent_id",
                "schema": {"type": "string"},
                "description": "Agent ID to filter transactions (used if sender_id is not provided)"
            },
            {
                "in": "query",
                "name": "page",
                "schema": {"type": "integer"},
                "description": "Page number for pagination"
            },
            {
                "in": "query",
                "name": "per_page",
                "schema": {"type": "integer"},
                "description": "Number of transactions per page"
            }
        ],
        responses={
            200: {
                "description": "Transactions retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "transactions": [
                                    {
                                        "transaction_id": "abc123",
                                        "amount": 100,
                                        "currency": "USD",
                                        "status": "Completed",
                                        "sender_id": "user123",
                                        "agent_id": "agent456",
                                        "created_at": "2025-05-10T12:00:00Z"
                                    }
                                ],
                                "total_count": 25,
                                "total_pages": 3,
                                "current_page": 1,
                                "per_page": 10
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request parameters",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Missing sender_id or agent_id"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid or missing authentication token"
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
                            "error": "Detailed error message"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}]
    )
    def get(self, transaction_data):
        log_tag = '[transaction_resource.py][TransactionsByAgentResource][get]'
        
        user_info = g.get("current_user", {})
        agent_id = user_info.get("agent_id")
        sender_id = transaction_data.get("sender_id") if transaction_data.get("sender_id") else None
        client_ip = request.remote_addr
        transaction = {}

        if not agent_id:
            Log.info(f"{log_tag}[{client_ip}] agent_id must be provided.")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "agent_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] retrieving transactions.")
            start_time = time.time()
            
            if sender_id:
                transaction = Transaction.get_by_sender_id(sender_id)
            else:
                transaction = Transaction.get_by_agent_id(agent_id)

            duration = time.time() - start_time
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "No transaction found for this agent."
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.error(f"{log_tag}[{client_ip}][{agent_id}] Mongo error: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Database error occurred while retrieving transaction.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}][{agent_id}] General error: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
     
@blp_transaction.route("/transaction", methods=["GET"])
class TransactionsByAgentResource(MethodView):
    # GET Aget Transactions (Retrieve by agent_id)
    @token_required
    @blp_transaction.arguments(TranactionIdQuerySchema, location="query")
    @blp_transaction.response(200, TransactionSchema(many=True))
    @blp_transaction.doc(
        summary="Retrieve transactions by sender_id or agent_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `sender_id` or an `agent_id`.

            - **GET**: Retrieve transactions by providing either `sender_id` or `agent_id` as query parameters.
            - If both are provided, `sender_id` will take precedence.
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `sender_id` (optional): ID of the sender.
            - `agent_id` (optional): ID of the agent (used if `sender_id` is not provided).
            - `page` (optional): Page number for pagination (default is 1).
            - `per_page` (optional): Number of transactions per page (default is 10).
        """,
        parameters=[
            {
                "in": "query",
                "name": "sender_id",
                "schema": {"type": "string"},
                "description": "Sender ID to filter transactions"
            },
            {
                "in": "query",
                "name": "agent_id",
                "schema": {"type": "string"},
                "description": "Agent ID to filter transactions (used if sender_id is not provided)"
            },
            {
                "in": "query",
                "name": "page",
                "schema": {"type": "integer"},
                "description": "Page number for pagination"
            },
            {
                "in": "query",
                "name": "per_page",
                "schema": {"type": "integer"},
                "description": "Number of transactions per page"
            }
        ],
        responses={
            200: {
                "description": "Transactions retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "transactions": [
                                    {
                                        "transaction_id": "abc123",
                                        "amount": 100,
                                        "currency": "USD",
                                        "status": "Completed",
                                        "sender_id": "user123",
                                        "agent_id": "agent456",
                                        "created_at": "2025-05-10T12:00:00Z"
                                    }
                                ],
                                "total_count": 25,
                                "total_pages": 3,
                                "current_page": 1,
                                "per_page": 10
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request parameters",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Missing sender_id or agent_id"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid or missing authentication token"
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
                            "error": "Detailed error message"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}]
    )
    def get(self, transaction_data):
        log_tag = '[transaction_resource.py][TransactionsByAgentResource][get]'
        
        user_info = g.get("current_user", {})
        agent_id = user_info.get("agent_id")
        transaction_id = transaction_data.get("transaction_id")
        client_ip = request.remote_addr
        transaction = {}

        if not agent_id:
            Log.info(f"{log_tag}[{client_ip}] agent_id must be provided.")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": "agent_id must be provided."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}][{transaction_id}] retrieving transaction.")
            start_time = time.time()
            
            transaction = Transaction.get_by_id(transaction_id, agent_id)

            duration = time.time() - start_time
            Log.info(f"{log_tag}[{client_ip}][{agent_id}][{transaction_id}] transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                    "message": "No transaction found for this agent."
                }), HTTP_STATUS_CODES["NOT_FOUND"]

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.error(f"{log_tag}[{client_ip}][{agent_id}][{transaction_id}] Mongo error: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Database error occurred while retrieving transaction.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}][{agent_id}][{transaction_id}] General error: {str(e)}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
  

# -----------------------TRANACTION-----------------------------------------