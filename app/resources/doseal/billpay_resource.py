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
from ...utils.generators import generate_internal_reference
from ...utils.pre_transaction_checks import PreTransactionCheck
#helper functions

from ...services.doseal.confirm_pin_service import confirm_pin
from ...services.shop_api_service import ShopApiService
from ...services.gateways.transaction_gateway_service import TransactionGatewayService
from ...utils.pre_transaction_checks import PreTransactionCheck
from .admin.admin_business_resource import token_required
from ...utils.logger import Log # import logging
from ...constants.service_code import (
    HTTP_STATUS_CODES, TRANSACTION_GENERAL_REQUIRED_FIELDS, BILLPAY_BILLER
)
from ...services.gateways.gateway_service import GatewayService

# model
from ...models.transaction_model import Transaction
from ...models.people_model import Agent
from ...models.beneficiary_model import Beneficiary
from ...models.sender_model import Sender
from ...models.settings_model import Limit

from ...schemas.billpay_schema import (
    BillerListSchema, AccountValidationSchema,InitiatePaymentSchema
)

blp_billpay = Blueprint("Billpay", __name__, description="Billpay Management")


# -----------------------BILLPAY-----------------------------------------
@blp_billpay.route("/billpay/biller-list", methods=["GET"])
class BillPayResource(MethodView):
    # GET biller-list (Get Biller List)
    @token_required
    @blp_billpay.arguments(BillerListSchema, location="query")
    @blp_billpay.response(200, BillerListSchema)
    @blp_billpay.doc(
        summary="Initiate new transaction",
        description="""
            This endpoint allows you to create a new transaction. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new transaction by providing details such as transaction type, payment details, recipient, amount, and optional image file.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": BillerListSchema,
                    "example": {
                        "payment_mode": "Bank",
                        "amount": "100",
                        "currency_code": "USD",
                        "transaction_type": "Transfer",
                        "receiver_msisdn": "987-654-3210",
                        "receiver_name": "Jane Doe",
                        "receiver_country_iso2": "US",
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Transaction created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Transaction created successfully",
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
    def get(self, item_data):

        """Handle the POST request to create a new transaction."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f'[transaction_resource.py][BillPayResource][get][{client_ip}]'
        
        business_id = str(user_info.get("business_id"))
        agent_id = str(user_info.get("agent_id"))
        user__id = str(user_info.get("_id"))
        
        item_data["user__id"] = str(user_info.get("_id"))
        item_data["business_id"] = business_id
        item_data["agent_id"] = agent_id
        tenant_id = decrypt_data(user_info.get("tenant_id"))
        
       
        # Initializing transaction
        try:
            Log.info(f"{log_tag}[{client_ip}] initiatring transaction")
            transaction_id = None
            
            shop_service = ShopApiService(tenant_id)
            
            country_iso_2 = item_data.get("country_iso_2")
            
            response = shop_service.get_biller_list(country_iso_2)
        
            return response
        
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{transaction_id}] error initiatring transaction: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while initiating transaction.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
    

# -----------------------BILLPAY - ACCOUNT VALIDATION-----------------------------------------
@blp_billpay.route("/billpay/account-validation", methods=["POST"])
class AccountValidationResource(MethodView):
    # POST account validation
    @token_required
    @blp_billpay.arguments(AccountValidationSchema, location="json")
    @blp_billpay.response(200, AccountValidationSchema)
    @blp_billpay.response(200)  # you can plug in a response schema later if needed
    @blp_billpay.doc(
        summary="Validate bill payment account",
        description="""
            This endpoint validates a destination account for bill payment.
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Validate an account by providing billpay_id, account_id, currencies, amounts, and countries.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": AccountValidationSchema,
                    "example": {
                        "billpay_id": "b790d050-68b3-4d16-9530-942f8f0d7cea",
                        "account_id": "P4949494",
                        "beneficiary_id": "8921eee592c7e6ddb51f2190",
                        "sender_id": "5921eee592c7e6ddb51f2178",
                        "payment_mode": "Card",
                        "send_amount": 1,
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Account validated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Account validation successful",
                            "data": {
                                "is_valid": True,
                                "account_name": "John Doe",
                                "billpay_id": "b790d050-68b3-4d16-9530-942f8f0d7cea"
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
                            "message": "An unexpected error occurred while validating account.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def post(self, item_data):
        """Handle the POST request to validate a bill payment account."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f'[transaction_resource.py][AccountValidationResource][post][{client_ip}]'

        business_id = str(user_info.get("business_id"))
        subscriber_id = str(user_info.get("subscriber_id")) if user_info.get("subscriber_id") else None
        user_id = str(user_info.get("user_id"))
        beneficiary = dict()
        
        beneficiary_id = str(item_data.get("beneficiary_id"))
        
        # Assign user_id and business_id from current user
        item_data["user_id"] = user_id
        item_data["user__id"] = str(user_info.get("_id"))
        item_data["created_by"] = str(user_info.get("_id"))
        agent_id = str(user_info.get("agent_id")) if user_info.get("agent_id") else None
        item_data["agent_id"] = agent_id
        item_data["business_id"] = business_id
        item_data["subscriber_id"] = subscriber_id
        item_data["transaction_type"] = "billpay"
        
        beneficiary_id = item_data.get("beneficiary_id")
        
        internal_reference = generate_internal_reference("BR")
        
        item_data["reference"] = internal_reference
        
        if agent_id is None:
            item_data["payment_mode"] = "Card"

        
        
        #ensure sender exists when it's an agent
        if agent_id and not item_data.get("sender_id"):
            Log.info(f"{log_tag} User is Agent. Sender Id is required")
            return prepared_response(False, "BAD_REQUEST", f"Sender Id is required")
        
        if agent_id and not item_data.get("payment_mode"):
            Log.info(f"{log_tag} Payment Mode is required")
            return prepared_response(False, "BAD_REQUEST", f"Payment Mode is required")
        
        # Require account_id if biller is ECG
        biller_id = BILLPAY_BILLER[0]["BILLER_ID"]
        if  item_data.get("billpay_id")== biller_id and item_data.get("account_id") is None:
            Log.info(f"{log_tag} Biller is ECG, therefore 'account_id' is required")
            return prepared_response(False, "BAD_REQUEST", f"'account_id' is required for this biller")
        
        

        try:
            Log.info(f"{log_tag}[{client_ip}] initiating account validation")
            
            #####################PRE TRANSACTION CHECKS FOR SUBSCRIBER#########################
            if subscriber_id is not None:
                # add sender to the payload
                item_data["sender_id"] = subscriber_id
                
                # 1. check pre transaction requirements for subscribers
                pre_transaction_check = PreTransactionCheck(subscriber_id=subscriber_id, business_id=business_id)
                initial_check_result = pre_transaction_check.initial_subscriber_transaction_checks()
                
                if initial_check_result is not None:
                    return initial_check_result
        
            #####################PRE TRANSACTION CHECKS# FOR SUBSCRIBERS########################
            
            #####################PRE TRANSACTION CHECKS FOR AGENTS#########################
        
            if agent_id is not None:
                # 1. check pre transaction requirements for agents
                pre_transaction_check = PreTransactionCheck(agent_id=agent_id, business_id=business_id)
                initial_check_result = pre_transaction_check.initial_transaction_checks()
                
                if initial_check_result is not None:
                    return initial_check_result
                
                # 2. check if agent has enough balance to cover transaction
                transaction_balance_check = pre_transaction_check.agent_has_sufficient_available(item_data.get("send_amount"))
                Log.info(f"{log_tag} transaction_balance_check: {transaction_balance_check}")
                if not transaction_balance_check:
                    Log.info(f"{log_tag} Insufficient funds for this transaction.")
                    return prepared_response(False, "BAD_REQUEST", f"Insufficient funds for this transaction") 
            
            #####################PRE TRANSACTION CHECKS AGENTS#########################

            # Ensure beneficiary exist for the particular user
            try:
                Log.info(f"{log_tag} Retrieving beneficiary information.")
                
                if item_data.get("subscriber_id") is not None:
                    beneficiary = Beneficiary.get_by_id_and_user_id_and_business_id(
                        beneficiary_id=beneficiary_id,
                        user_id=user_info.get("_id"),
                        business_id=business_id
                    )
                    
                    Log.info(f"{log_tag} beneficiary information loaded successfully")
                
                if beneficiary is None:
                    Log.info(f"{log_tag} beneficiary do not exist for this user.")
                    return prepared_response(False, "NOT_FOUND", f"Beneficiary do not exist for this user.") 
            except Exception as e:
                Log.info(f"{log_tag} error retrieving beneficiary information: {str(e)}")
                
            # Initializing transaction
            
            try:
                Log.info(f"{log_tag}[{client_ip}] initiatring transaction")
                
                response = TransactionGatewayService.initiate_input(item_data)
                
                return response
                
            
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] error initiatring transaction: {e}")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "An unexpected error occurred while initiating transaction.",
                    "error": str(e)
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error validating account: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while validating account.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -----------------------BILLPAY - INITIATE BILLPAY TRANSACTION-----------------------------------------
@blp_billpay.route("/billpay/initiate-transaction", methods=["POST"])
class InitiateBillpayTransactionResource(MethodView):
    # POST initiate billpay transaction
    @token_required
    @blp_billpay.arguments(InitiatePaymentSchema, location="json")
    @blp_billpay.response(200)  # You can plug in a response schema later if needed
    @blp_billpay.doc(
        summary="Initiate bill payment transaction",
        description="""
            This endpoint initiates a bill payment transaction after a successful
            account validation step. It expects a checksum (from the previous step)
            and a PIN for authorization.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": InitiatePaymentSchema,
                    "example": {
                        "checksum": "BR-20241122-XYZ123",
                        "pin": "1234"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Billpay transaction initiated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Billpay transaction initiated successfully",
                            "results": {
                                "transaction_id": "TXN-20241122-0001",
                                "reference": "BR202411220001",
                                "billpay_id": "b790d050-68b3-4d16-9530-942f8f0d7cea",
                                "amount_details": {
                                    "send_amount": 1.00,
                                    "send_currency": "GBP",
                                    "receive_amount": 18.50,
                                    "receive_currency": "GHS"
                                }
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
                            "message": "An unexpected error occurred while initiating billpay transaction.",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        """Handle the POST request to initiate a bill payment transaction."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = f'[transaction_resource.py][InitiateBillpayTransactionResource][post][{client_ip}]'

        business_id = str(user_info.get("business_id"))
        subscriber_id = str(user_info.get("subscriber_id")) if user_info.get("subscriber_id") else None
        user_id = str(user_info.get("user_id"))
        account_type=None

        # Enrich payload with context
        item_data["user_id"] = user_id
        item_data["user__id"] = str(user_info.get("_id"))
        item_data["created_by"] = str(user_info.get("_id"))
        item_data["business_id"] = business_id
        item_data["subscriber_id"] = subscriber_id
        agent_id = str(user_info.get("agent_id")) if user_info.get("agent_id") else None
        item_data["agent_id"] = agent_id

        tenant_id = decrypt_data(user_info.get("tenant_id"))

        try:
            Log.info(f"{log_tag}[{client_ip}] initiating billpay transaction")
            
            checksum = item_data.get("checksum", None)
            checksum_hash_transformed = str.lower(checksum)
            
            try:
                Log.info(f"{log_tag} retrieving transaction from redis")
                encrypted_transaction = get_redis(checksum_hash_transformed)
                
                if encrypted_transaction is None:
                    message = f"The transaction has expired or the checksum is invalid. Kindly call the 'transactions/initiate' endpoint again and ensure the checksum is valid."
                    Log.info(f"{log_tag}[{agent_id}] {message}")
                    return prepared_response(False, "BAD_REQUEST", f"{message}")
                
                decrypted_transaction = decrypt_data(encrypted_transaction)
                
                transaction_details = json.loads(decrypted_transaction)
                
                
            
                # Validating transaction details failed
                if transaction_details is None:
                    Log.info(f"{log_tag} transaction validation failed.")
                    return prepared_response(False, "BAD_REQUEST", f"Transaction validation failed.")
                
                amount_details = transaction_details.get("amount_details")
                send_amount = amount_details.get("send_amount")
                    
                #####################PRE TRANSACTION CHECKS#########################
                if subscriber_id is not None:
                    # 1. check pre transaction requirements for subscribers
                    pre_transaction_check = PreTransactionCheck(subscriber_id=subscriber_id, business_id=business_id)
                    initial_check_result = pre_transaction_check.initial_subscriber_transaction_checks()
                    
                    if initial_check_result is not None:
                        return initial_check_result
                #####################PRE TRANSACTION CHECKS#########################
                
                #####################PRE TRANSACTION CHECKS FOR AGENTS#########################
            
            
                if agent_id is not None:
                    # 1. check pre transaction requirements for agents
                    pre_transaction_check = PreTransactionCheck(agent_id=agent_id, business_id=business_id)
                    initial_check_result = pre_transaction_check.initial_transaction_checks()
                    
                    if initial_check_result is not None:
                        return initial_check_result
                    
                    # 2. check if agent has enough balance to cover transaction
                    transaction_balance_check = pre_transaction_check.agent_has_sufficient_available(send_amount)
                    Log.info(f"{log_tag} transaction_balance_check: {transaction_balance_check}")
                    if not transaction_balance_check:
                        Log.info(f"{log_tag} Insufficient funds for this transaction.")
                        return prepared_response(False, "BAD_REQUEST", f"Insufficient funds for this transaction") 
                
                #####################PRE TRANSACTION CHECKS AGENTS#########################
                
                
                transaction_details.pop("checksum", None)
                
                # Assign user_id and business_id from current user
                transaction_details["user_id"] = str(user_info.get("user_id"))
                transaction_details["user__id"] = str(user_info.get("_id"))
                business_id = str(user_info.get("business_id"))
                transaction_details["business_id"] = business_id
                transaction_details["checksum"] = checksum_hash_transformed
                tenant_id = transaction_details.get("tenant_id")
                
                ########### CONFIRM PIN##############################
                user__id = str(user_info.get("_id"))
                
                if agent_id is not None:
                    account_type = "agent"
                
                if subscriber_id is not None:
                    account_type = "subscriber"
                
                validate_pin_response, status = confirm_pin(user__id, item_data.get("pin"), account_type=account_type)
                validate_pin_response_json = validate_pin_response.get_json()
                
                if status == 400 or status == 500 or status == 404:
                    error_message = validate_pin_response_json.get("message")
                    Log.info(f"{log_tag} Validate PIN failed. {error_message}")
                    Log.info(f"{log_tag} status: {status}")
                    Log.info(f"{log_tag} validate_pin_response_json: {validate_pin_response_json}")
                    return jsonify(validate_pin_response_json)
                elif status != 200:
                    error_message = validate_pin_response_json.get("message")
                    Log.info(f"{log_tag} Validate PIN failed. {error_message}")
                    Log.info(f"{log_tag} status: {status}")
                    Log.info(f"{log_tag} validate_pin_response_json: {validate_pin_response_json}")
                    return jsonify(validate_pin_response_json)
                ########### CONFIRM PIN##############################
            
                # initialize gateway service with tenant ID
                gateway_service = GatewayService(tenant_id)
                
                
                json_response = gateway_service.execute_transaction_execute(**transaction_details)

                return json_response
                
            except Exception as e:
                Log.info(f"{log_tag} error retrieving transaction from redis: {str(e)}")
                return prepared_response(False, "BAD_REQUEST", f"An eror ocurred while executing transaction. Error: {str(e)}")
            
            
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error initiating billpay transaction: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while initiating billpay transaction.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
