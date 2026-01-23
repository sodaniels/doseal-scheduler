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
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.redis import get_redis
from ....utils.generic import delete_model
from ....utils.validation import validate_payment_details
from ....utils.json_response import prepared_response
#helper functions

from ....services.gateways.transaction_gateway_service import TransactionGatewayService
from .admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....constants.service_code import (
    HTTP_STATUS_CODES, TRANSACTION_GENERAL_REQUIRED_FIELDS
)
from ....services.gateways.gateway_service import GatewayService

# model
from ....models.transaction_model import Transaction
from ....models.people_model import Agent
from ....models.beneficiary_model import Beneficiary
from ....models.settings_model import Limit

from ....schemas.transaction_schema import (
     TransactionSchema, TransactionExecuteSchema, SenderdQuerySchema,
     TranactionIdQuerySchema, AgentIdQuerySchema, TransactionQuerySchema,
     TransactionAgentQuerySchema, TransactionSenderQuerySchema, 
     TransactionPinNumberAndIRQuerySchema, TransactionSearchQuerySchema,
     TransactionSummaryQuerySchema
)

blp_admin_transaction = Blueprint("Tranaction", __name__, description="Tranaction Management")

# -----------------------TRANACTION-----------------------------------------    
@blp_admin_transaction.route("/transactions", methods=["GET"])
class TransactionsResource(MethodView):
    # GET Transactions (Retrieve by business_id)
    @token_required
    @blp_admin_transaction.arguments(TransactionQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionQuerySchema(many=True))
    @blp_admin_transaction.doc(
        summary="Retrieve transactions by business_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `business_id`.

            - **GET**: Retrieve transactions by business_id.
            - If both are provided, `sender_id` will take precedence.
            - Supports filtering by date range (`from_date` and/or `to_date`) using ISO 8601 format with timezone (e.g., `2025-07-07T17:43:09.007+00:00`).
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `from_date` (optional): Start of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-01T00:00:00.000+00:00`).
            - `to_date` (optional): End of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-31T23:59:59.999+00:00`).
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
                "name": "from_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-01T00:00:00.000+00:00"
                },
                "description": "Start date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-01T00:00:00.000+00:00)"
            },
            {
                "in": "query",
                "name": "to_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-31T23:59:59.999+00:00"
                },
                "description": "End date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-31T23:59:59.999+00:00)"
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
                                        "_id": "68680bb222d37ca057bca4ee",
                                        "amount_details": {
                                            "destAmount": 14.27,
                                            "feeAmount": 8,
                                            "fxamount": 12.9761,
                                            "oriAmount": 1.1,
                                            "oriCurrency": "USD",
                                            "totalAmount": 9.1
                                        },
                                        "beneficiary_account": {
                                            "name": "KWAME KORANTENG ",
                                            "receiver_bank_account_id": 13649485,
                                            "type": "DEPOSIT"
                                        },
                                        "business_id": "686e2724393fbd6408c7a83a",
                                        "created_at": "2025-07-04T17:13:22.000+00:00",
                                        "description": "DEPOSIT payment from Intermex",
                                        "sender_id": "6862b6081fd41808cbd88d5b",
                                        "user_id": "32145439",
                                        "user__id": "6862b6091fd41808cbd88d5c",
                                        "agent_id": None,
                                        # ... additional transaction fields
                                    }
                                ],
                                "total_count": 26,
                                "total_pages": 26,
                                "current_page": 1,
                                "per_page": 1
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
    def get(self, item_data):
        
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        client_ip = request.remote_addr
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionsResource][get][{client_ip}][{business_id}]'
        try:
            Log.info(f"{log_tag} retrieving transactions.")
            start_time = time.time()
            
            transaction = Transaction.get_by_business_id(
               business_id=business_id,
               page=item_data.get("page"),
               per_page=item_data.get("per_page"),
               start_date=item_data.get("start_date"),
               end_date=item_data.get("end_date"),
               partner_name=item_data.get("partner_name"),
            )  

            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", f"No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error occurred while retrieving transaction. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred while retrieving transaction.. {str(e)}")


@blp_admin_transaction.route("/agent/transactions", methods=["GET"])
class TransactionsAgentResource(MethodView):
    # GET Transactions (Retrieve by business_id and agent_id)
    @token_required
    @blp_admin_transaction.arguments(TransactionAgentQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionAgentQuerySchema(many=True))
    @blp_admin_transaction.doc(
        summary="Retrieve transactions by sender_id or agent_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `sender_id` or an `agent_id`.

            - **GET**: Retrieve transactions by providing either `sender_id` or `agent_id` as query parameters.
            - If both are provided, `sender_id` will take precedence.
            - Supports filtering by date range (`from_date` and/or `to_date`) using ISO 8601 format with timezone (e.g., `2025-07-07T17:43:09.007+00:00`).
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `sender_id` (optional): ID of the sender.
            - `agent_id` (optional): ID of the agent (used if `sender_id` is not provided).
            - `from_date` (optional): Start of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-01T00:00:00.000+00:00`).
            - `to_date` (optional): End of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-31T23:59:59.999+00:00`).
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
                "name": "from_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-01T00:00:00.000+00:00"
                },
                "description": "Start date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-01T00:00:00.000+00:00)"
            },
            {
                "in": "query",
                "name": "to_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-31T23:59:59.999+00:00"
                },
                "description": "End date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-31T23:59:59.999+00:00)"
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
                                        "_id": "68680bb222d37ca057bca4ee",
                                        "amount_details": {
                                            "destAmount": 14.27,
                                            "feeAmount": 8,
                                            "fxamount": 12.9761,
                                            "oriAmount": 1.1,
                                            "oriCurrency": "USD",
                                            "totalAmount": 9.1
                                        },
                                        "beneficiary_account": {
                                            "name": "KWAME KORANTENG ",
                                            "receiver_bank_account_id": 13649485,
                                            "type": "DEPOSIT"
                                        },
                                        "business_id": "686e2724393fbd6408c7a83a",
                                        "created_at": "2025-07-04T17:13:22.000+00:00",
                                        "description": "DEPOSIT payment from Intermex",
                                        "sender_id": "6862b6081fd41808cbd88d5b",
                                        "user_id": "32145439",
                                        "user__id": "6862b6091fd41808cbd88d5c",
                                        "agent_id": None,
                                        # ... additional transaction fields
                                    }
                                ],
                                "total_count": 26,
                                "total_pages": 26,
                                "current_page": 1,
                                "per_page": 1
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
    def get(self, item_data):
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        agent_id = item_data.get("agent_id")
        client_ip = request.remote_addr
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionsAgentResource][get][{client_ip}][{business_id}][{agent_id}]'

        try:
            Log.info(f"{log_tag} retrieving transactions by agent_id and business_id.")
            start_time = time.time()
            
            transaction = Transaction.get_by_business_id_and_agent_id(
               business_id=business_id,
               agent_id=agent_id,
               page=item_data.get("page"),
               per_page=item_data.get("per_page"),
               start_date=item_data.get("start_date"),
               end_date=item_data.get("end_date"),
            )  

            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", f"No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error occurred while retrieving transaction. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred while retrieving transaction.. {str(e)}")

@blp_admin_transaction.route("/sender/transactions", methods=["GET"])
class TransactionsSenderResource(MethodView):
    # GET Transactions (Retrieve by business_id and agensender_idt_id)
    @token_required
    @blp_admin_transaction.arguments(TransactionSenderQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionSenderQuerySchema(many=True))
    @blp_admin_transaction.doc(
        summary="Retrieve transactions by sender_id or agent_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `sender_id` or an `agent_id`.

            - **GET**: Retrieve transactions by providing either `sender_id` or `agent_id` as query parameters.
            - If both are provided, `sender_id` will take precedence.
            - Supports filtering by date range (`from_date` and/or `to_date`) using ISO 8601 format with timezone (e.g., `2025-07-07T17:43:09.007+00:00`).
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `sender_id` (optional): ID of the sender.
            - `agent_id` (optional): ID of the agent (used if `sender_id` is not provided).
            - `from_date` (optional): Start of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-01T00:00:00.000+00:00`).
            - `to_date` (optional): End of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-31T23:59:59.999+00:00`).
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
                "name": "from_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-01T00:00:00.000+00:00"
                },
                "description": "Start date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-01T00:00:00.000+00:00)"
            },
            {
                "in": "query",
                "name": "to_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-31T23:59:59.999+00:00"
                },
                "description": "End date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-31T23:59:59.999+00:00)"
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
                                        "_id": "68680bb222d37ca057bca4ee",
                                        "amount_details": {
                                            "destAmount": 14.27,
                                            "feeAmount": 8,
                                            "fxamount": 12.9761,
                                            "oriAmount": 1.1,
                                            "oriCurrency": "USD",
                                            "totalAmount": 9.1
                                        },
                                        "beneficiary_account": {
                                            "name": "KWAME KORANTENG ",
                                            "receiver_bank_account_id": 13649485,
                                            "type": "DEPOSIT"
                                        },
                                        "business_id": "686e2724393fbd6408c7a83a",
                                        "created_at": "2025-07-04T17:13:22.000+00:00",
                                        "description": "DEPOSIT payment from Intermex",
                                        "sender_id": "6862b6081fd41808cbd88d5b",
                                        "user_id": "32145439",
                                        "user__id": "6862b6091fd41808cbd88d5c",
                                        "agent_id": None,
                                        # ... additional transaction fields
                                    }
                                ],
                                "total_count": 26,
                                "total_pages": 26,
                                "current_page": 1,
                                "per_page": 1
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
    def get(self, item_data):
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        sender_id = item_data.get("sender_id")
        client_ip = request.remote_addr
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionsSenderResource][get][{client_ip}][{business_id}][{sender_id}]'

        try:
            Log.info(f"{log_tag} retrieving transactions by sender_id and business_id.")
            start_time = time.time()
            
            transaction = Transaction.get_by_business_id_and_sender_id(
               business_id=business_id,
               sender_id=sender_id,
               page=item_data.get("page"),
               per_page=item_data.get("per_page"),
               start_date=item_data.get("start_date"),
               end_date=item_data.get("end_date"),
            )  

            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", f"No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error occurred while retrieving transaction. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred while retrieving transaction.. {str(e)}")

@blp_admin_transaction.route("/transaction", methods=["GET"])
class TransactionDetailResource(MethodView):
    # GET Transactions (Retrieve by pin_number)
    @token_required
    @blp_admin_transaction.arguments(TransactionPinNumberAndIRQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionPinNumberAndIRQuerySchema(many=True))
    @blp_admin_transaction.doc(
        summary="Retrieve transactions by sender_id or agent_id",
        description="""
            This endpoint allows you to retrieve transactions associated with either a `sender_id` or an `agent_id`.

            - **GET**: Retrieve transactions by providing either `sender_id` or `agent_id` as query parameters.
            - If both are provided, `sender_id` will take precedence.
            - Supports filtering by date range (`from_date` and/or `to_date`) using ISO 8601 format with timezone (e.g., `2025-07-07T17:43:09.007+00:00`).
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `sender_id` (optional): ID of the sender.
            - `agent_id` (optional): ID of the agent (used if `sender_id` is not provided).
            - `from_date` (optional): Start of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-01T00:00:00.000+00:00`).
            - `to_date` (optional): End of date range for filtering transactions (ISO 8601 format, e.g., `2025-07-31T23:59:59.999+00:00`).
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
                "name": "from_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-01T00:00:00.000+00:00"
                },
                "description": "Start date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-01T00:00:00.000+00:00)"
            },
            {
                "in": "query",
                "name": "to_date",
                "schema": {
                    "type": "string",
                    "format": "date-time",
                    "example": "2025-07-31T23:59:59.999+00:00"
                },
                "description": "End date/time (inclusive) for transaction filtering (ISO 8601 with timezone, e.g., 2025-07-31T23:59:59.999+00:00)"
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
                                        "_id": "68680bb222d37ca057bca4ee",
                                        "amount_details": {
                                            "destAmount": 14.27,
                                            "feeAmount": 8,
                                            "fxamount": 12.9761,
                                            "oriAmount": 1.1,
                                            "oriCurrency": "USD",
                                            "totalAmount": 9.1
                                        },
                                        "beneficiary_account": {
                                            "name": "KWAME KORANTENG ",
                                            "receiver_bank_account_id": 13649485,
                                            "type": "DEPOSIT"
                                        },
                                        "business_id": "686e2724393fbd6408c7a83a",
                                        "created_at": "2025-07-04T17:13:22.000+00:00",
                                        "description": "DEPOSIT payment from Intermex",
                                        "sender_id": "6862b6081fd41808cbd88d5b",
                                        "user_id": "32145439",
                                        "user__id": "6862b6091fd41808cbd88d5c",
                                        "agent_id": None,
                                        # ... additional transaction fields
                                    }
                                ],
                                "total_count": 26,
                                "total_pages": 26,
                                "current_page": 1,
                                "per_page": 1
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
    def get(self, item_data):
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        pin_number = item_data.get("pin_number")
        internal_reference = item_data.get("internal_reference")
        client_ip = request.remote_addr
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionDetailResource][get][{client_ip}][{business_id}][{pin_number}]'

        try:
            Log.info(f"{log_tag} retrieving transactions by pin_number and business_id.")
            start_time = time.time()
            
            # retrieve transaction detail based on pin_number
            if pin_number is not None:
                transaction = Transaction.get_by_business_id_and_pin_number(
                    business_id=business_id,
                    pin_number=pin_number,
                )  
            
            # retrieve transaction detail based on internal_reference
            if internal_reference is not None:
                transaction = Transaction.get_by_business_id_and_internal_reference(
                    business_id=business_id,
                    internal_reference=internal_reference,
                )


            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction retrieved in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", f"No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error occurred while retrieving transaction. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred while retrieving transaction.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred while retrieving transaction.. {str(e)}")


@blp_admin_transaction.route("/transaction/search", methods=["GET"])
class TransactionDetailResource(MethodView):
    @token_required
    @blp_admin_transaction.arguments(TransactionSearchQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionSearchQuerySchema(many=True))
    @blp_admin_transaction.doc(
        summary="Search for a transaction by pin, internal reference, receiver ID, sender ID, or account",
        description="""
            This endpoint allows you to search for a transaction using one of several identifiers:
            `pin_number`, `internal_reference`, `receiverId`, `senderId`, or `account`.

            - **GET**: Provide any one of the supported query parameters to fetch transaction details.
            - If more than one parameter is provided, search will be performed in this priority: `pin_number`, `internal_reference`, `receiverId`, `senderId`, `account`.
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `pin_number` (optional): The pin number associated with the transaction.
            - `internal_reference` (optional): The internal reference associated with the transaction.
            - `receiverId` (optional): The receiver's ID.
            - `senderId` (optional): The sender's ID.
            - `account` (optional): The account associated with the transaction.
        """,
        parameters=[
            {
                "in": "query",
                "name": "pin_number",
                "schema": {"type": "string"},
                "description": "Pin number of the transaction to fetch detail.",
                "example": "N780531905"
            },
            {
                "in": "query",
                "name": "internal_reference",
                "schema": {"type": "string"},
                "description": "Internal reference of the transaction to fetch detail.",
                "example": "CR_20250704171322986141"
            },
            {
                "in": "query",
                "name": "receiverId",
                "schema": {"type": "string"},
                "description": "Receiver ID of the transaction to fetch detail.",
                "example": "77026221"
            },
            {
                "in": "query",
                "name": "senderId",
                "schema": {"type": "string"},
                "description": "Sender ID of the transaction to fetch detail.",
                "example": "6862b6081fd41808cbd88d5b"
            },
            {
                "in": "query",
                "name": "account",
                "schema": {"type": "string"},
                "description": "Account number of the transaction to fetch detail.",
                "example": "13018867594"
            },
        ],
        responses={
            200: {
                "description": "Transaction retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "_id": "68680bb222d37ca057bca4ee",
                                "pin_number": "N780531905",
                                "internal_reference": "CR_20250704171322986141",
                                "receiverId": "77026221",
                                "senderId": "6862b6081fd41808cbd88d5b",
                                "account": "13018867594",
                                "amount_details": {
                                    "destAmount": 14.27,
                                    "feeAmount": 8,
                                    "fxamount": 12.9761,
                                    "oriAmount": 1.1,
                                    "oriCurrency": "USD",
                                    "totalAmount": 9.1
                                },
                                "business_id": "686e2724393fbd6408c7a83a",
                                "created_at": "2025-07-04T17:13:22.000+00:00",
                                "description": "DEPOSIT payment from Intermex",
                                # ... additional fields ...
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
                            "message": "At least one search parameter is required (pin_number, internal_reference, receiverId, senderId, or account)."
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
            404: {
                "description": "Transaction not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "No transaction found."
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
    def get(self, item_data):
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        pin_number = item_data.get("pin_number")
        internal_reference = item_data.get("internal_reference")
        receiver_id = item_data.get("receiverId")
        sender_id = item_data.get("senderId")
        account = item_data.get("account")
        client_ip = request.remote_addr
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionDetailResource][get][{client_ip}][{business_id}]'

        try:
            Log.info(f"{log_tag} Searching transaction by priority fields.")
            start_time = time.time()

            # Priority search: pin_number > internal_reference > receiverId > senderId > account
            if pin_number:
                Log.info(f"{log_tag} Searching by pin_number: {pin_number}")
                transaction = Transaction.get_by_business_id_and_pin_number(
                    business_id=business_id,
                    pin_number=pin_number,
                )
            elif internal_reference:
                Log.info(f"{log_tag} Searching by internal_reference: {internal_reference}")
                transaction = Transaction.get_by_business_id_and_internal_reference(
                    business_id=business_id,
                    internal_reference=internal_reference,
                )
            elif receiver_id:
                Log.info(f"{log_tag} Searching by receiverId: {receiver_id}")
                transaction = Transaction.get_by_business_id_and_receiverId(
                    business_id=business_id,
                    receiver_id=receiver_id,
                )
            elif sender_id:
                Log.info(f"{log_tag} Searching by senderId: {sender_id}")
                transaction = Transaction.search_by_business_id_and_senderId(
                    business_id=business_id,
                    sender_id=sender_id,
                )
            elif account:
                Log.info(f"{log_tag} Searching by account: {account}")
                transaction = Transaction.search_by_business_id_and_account(
                    business_id=business_id,
                    account=account,
                )

            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction search completed in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", "No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error: {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred: {str(e)}")

@blp_admin_transaction.route("/transaction/summary", methods=["GET"])
class TransactionSummaryResource(MethodView):
    @token_required
    @blp_admin_transaction.doc(
        summary="Search for a transaction by pin, internal reference, receiver ID, sender ID, or account",
        description="""
            This endpoint allows you to search for a transaction using one of several identifiers:
            `pin_number`, `internal_reference`, `receiverId`, `senderId`, or `account`.

            - **GET**: Provide any one of the supported query parameters to fetch transaction details.
            - If more than one parameter is provided, search will be performed in this priority: `pin_number`, `internal_reference`, `receiverId`, `senderId`, `account`.
            - Requires a valid Bearer token in the `Authorization` header.

            **Query Parameters:**
            - `pin_number` (optional): The pin number associated with the transaction.
            - `internal_reference` (optional): The internal reference associated with the transaction.
            - `receiverId` (optional): The receiver's ID.
            - `senderId` (optional): The sender's ID.
            - `account` (optional): The account associated with the transaction.
        """,
        parameters=[
            {
                "in": "query",
                "name": "pin_number",
                "schema": {"type": "string"},
                "description": "Pin number of the transaction to fetch detail.",
                "example": "N780531905"
            },
            {
                "in": "query",
                "name": "internal_reference",
                "schema": {"type": "string"},
                "description": "Internal reference of the transaction to fetch detail.",
                "example": "CR_20250704171322986141"
            },
            {
                "in": "query",
                "name": "receiverId",
                "schema": {"type": "string"},
                "description": "Receiver ID of the transaction to fetch detail.",
                "example": "77026221"
            },
            {
                "in": "query",
                "name": "senderId",
                "schema": {"type": "string"},
                "description": "Sender ID of the transaction to fetch detail.",
                "example": "6862b6081fd41808cbd88d5b"
            },
            {
                "in": "query",
                "name": "account",
                "schema": {"type": "string"},
                "description": "Account number of the transaction to fetch detail.",
                "example": "13018867594"
            },
        ],
        responses={
            200: {
                "description": "Transaction retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "_id": "68680bb222d37ca057bca4ee",
                                "pin_number": "N780531905",
                                "internal_reference": "CR_20250704171322986141",
                                "receiverId": "77026221",
                                "senderId": "6862b6081fd41808cbd88d5b",
                                "account": "13018867594",
                                "amount_details": {
                                    "destAmount": 14.27,
                                    "feeAmount": 8,
                                    "fxamount": 12.9761,
                                    "oriAmount": 1.1,
                                    "oriCurrency": "USD",
                                    "totalAmount": 9.1
                                },
                                "business_id": "686e2724393fbd6408c7a83a",
                                "created_at": "2025-07-04T17:13:22.000+00:00",
                                "description": "DEPOSIT payment from Intermex",
                                # ... additional fields ...
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
                            "message": "At least one search parameter is required (pin_number, internal_reference, receiverId, senderId, or account)."
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
            404: {
                "description": "Transaction not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "No transaction found."
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
    @blp_admin_transaction.arguments(TransactionSummaryQuerySchema, location="query")
    @blp_admin_transaction.response(200, TransactionSummaryQuerySchema(many=True))
    def get(self, item_data):
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        client_ip = request.remote_addr
        partner_name = item_data.get("partner_name")
        transaction = {}
        log_tag = f'[admin_transaction_resource.py][TransactionSummaryResource][get][{client_ip}][{business_id}]'

        try:
            Log.info(f"{log_tag} Searching transaction by priority fields.")
            start_time = time.time()

            transaction = Transaction.transaction_summary_by_business(
                business_id=business_id,
                partner_name=partner_name
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} transaction summary completed in {duration:.2f} seconds")

            if not transaction:
                Log.info(f"{log_tag} No transaction found.")
                return prepared_response(False, "NOT_FOUND", "No transaction found.")

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": transaction
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag} Database error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Database error: {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag} An error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred: {str(e)}")
