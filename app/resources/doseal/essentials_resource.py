import bcrypt
import jwt
import os
import time
from redis import Redis
from functools import wraps
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request, g
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue

from ...utils.essentials import Essensial
from ...models.people_model import Agent
#helper functions
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.file_upload import (
    upload_file, 
    delete_old_image, 
    upload_files
)
from ...utils.generic import delete_model
from ...utils.validation import validate_payment_details
#helper functions
from ...services.shop_api_service import ShopApiService
from ...services.api_service import ApiService
from ...utils.helpers import Helper
from ...models.business_model import Client, Token, Business
from .admin.admin_business_resource import token_required
from ...models.sender_model import Sender
from ...utils.logger import Log # import logging
from ...constants.service_code import (
    HTTP_STATUS_CODES,
)
from ...utils.redis import set_redis
from ...utils.json_response import prepared_response
from ...models.user_model import User
from ...schemas.essentials_schema import (
    BankSchema, RateSchema, PostCodeSchema, AccountValidationSchema, CorridorSchema
)
from ...utils.helpers import generate_tokens
from ...schemas.business_schema import OAuthCredentialsSchema

from ...utils.rate_limits import (
    public_read_limiter,
    generic_limiter,
    crud_read_limiter,
    transaction_user_limiter,
)
blp_preauth= Blueprint("Pre Auth", __name__, description="Pre Auth Management")

blp_essentials= Blueprint("Essentials", __name__, description="Essentials Management")

# @blp_preauth.route("/oauth/token", methods=["POST"])
# class OAuthTokenResource(MethodView):
#     @public_read_limiter(
#         entity_name="countries",
#         limit_str="5 per minute; 20 per hour",
#     )
#     @blp_preauth.arguments(OAuthCredentialsSchema, location="json")
#     @blp_preauth.doc(
#         summary="Generate an OAuth token",
#         description="This endpoint authenticates a client using `client_id` and `client_secret`. "
#                     "If authentication is successful, it returns a Bearer token valid for 24 hours.",
#         responses={
#             200: {
#                 "description": "Successful authentication",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "access_token": "eyJhbGciOiJIUzI1...",
#                             "token_type": "Bearer",
#                             "expires_in": 86400
#                         }
#                     }
#                 }
#             },
#             401: {
#                 "description": "Invalid credentials or access revoked",
#                 "content": {
#                     "application/json": {
#                         "example": {
#                             "message": "Invalid client credentials"
#                         }
#                     }
#                 }
#             },
#             422:{
#             "description": "Validation error: Missing required fields",
#                 "content": {
#                 "application/json": {
#                     "example": {
#                         "code": 422,
#                         "errors": {
#                             "json": {
#                                 "client_id": [
#                                     "Client ID is required"
#                                 ],
#                                 "client_secret": [
#                                     "Client secret is required"
#                                 ]
#                             }
#                         },
#                         "status": "Unprocessable Entity"
#                     }
#                 }
#                 }
#             }
#         }
#     )
#     def post(self, item_data):
#         client_ip = request.remote_addr
        
#         log_tag = f'[essentials_resource.py][OAuthTokenResource][post][{client_ip}]'
        
#         # verify that the request contain valid key and secret
#         app_key = request.headers.get('x-app-key')
#         app_secret = request.headers.get('x-app-secret')
        
#         server_app_key = os.getenv("X_APP_KEY")
#         server_app_secret = os.getenv("X_APP_SECRET")
        
#         if str(app_key) != server_app_key or app_secret != server_app_secret:
#             Log.info(f"{log_tag}[{client_ip}] invalid x-app-key or x-app-secret in header")
#             return prepared_response(False, "UNAUTHORIZED", f"Unauthorized request.")
        
        
#         client_id = item_data.get('client_id')
#         truncated_client_id = client_id[:7] + "..." if client_id else None
        
#         Log.info(f"{log_tag} [{truncated_client_id}] request from IP: {client_ip}")
#         Log.info(f"{log_tag} [{truncated_client_id}][{client_ip}]")

#         # Validate client credentials
#         client = Client.retrieve_client(client_id)
#         if not client:
#             abort(401, message="Invalid client credentials")
            
#         business = Business.get_business(client_id)
#         if not business:
#             abort(401, message="Your access has been revoked")
        
#         #FOR AUTOMATED TESTING   
#         business_id = str(business.get("_id"))
#         set_redis('automated_test_business_id', business_id)
#         #FOR AUTOMATED TESTING
            
#         email = decrypt_data(business["email"])
            
#         # Check if the user exists based on email
#         user = User.get_user_by_email(email)
#         if user is None:
#             Log.info(f"{log_tag} [{client_ip}][{business['email']}]: login email does not exist")
#             return prepared_response(False, "UNAUTHORIZED", f"Invalid access.")
            
        
#         # Generate both access token and refresh token using the user object
#         permissions = None
#         access_token, refresh_token = generate_tokens(user, permissions)
#         Token.create_token(client_id, access_token, refresh_token, 190900, 604800)

#         # Token is for 24 hours
#         return jsonify({'access_token': access_token, 'token_type': 'Bearer', 'expires_in': 86400})


@blp_preauth.route("/tenants", methods=["GET"])
class TenantResource(MethodView):
    @public_read_limiter(
        entity_name="tenants",
        limit_str="30 per minute; 300 per hour",
    )
    @blp_preauth.doc(
        summary="Retrieve tenants",
        description="""
                This endpoint allows you to retrieve tenants.
                - **GET**: Retrieve tenant(s).
                - The request requires an `x-app-key` header with your app's key.
            """,
        security=[],
        responses={
            200: {
                "description": "Tenants retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "id": 1,
                                    "dba": "Zeemoney",
                                    "country_name": "United Kingdom",
                                    "country_iso_2": "GB",
                                    "country_iso_3": "GBR",
                                    "flag": "https://flagsapi.com/GB/flat/24.png",
                                    "country_code": "+44",
                                    "endpoint": "http://uk-tenant-endpoint",
                                    "country_currency": "GBP",
                                    "active": True,
                                    "createdAt": "2025-03-02T17:50:13.861Z",
                                    "updatedAt": "2025-03-02T17:50:13.861Z"
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
                            "message": "Missing or invalid x-app-key"
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
        log_tag = '[essentials_resource.py][TenantResource][get]'
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        # verify that the request contain valid key and secret
        app_key = request.headers.get('x-app-key')
        app_secret = request.headers.get('x-app-secret')
        
        server_app_key = os.getenv("X_APP_KEY")
        server_app_secret = os.getenv("X_APP_SECRET")
        
        if str(app_key) != server_app_key or app_secret != server_app_secret:
            Log.info(f"{log_tag}[{client_ip}] invalid x-app-key or x-app-secret in header")
            return prepared_response(False, "UNAUTHORIZED", f"Unauthorized request.")
        
        try:
            Log.info(f"{log_tag} retrieving a list of countries IP: {client_ip}")
            tenants = Essensial.tenants()
        
            if tenants:
                results = []
                for country in tenants:
                    country["_id"] = str(country["_id"])
                    results.append(country)
            
                response = {
                    "success": True,
                    "status_code": 200,
                    "data": results
                }
                return jsonify(response)
            
            else:
                response = {
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to get countries"
                }
                return jsonify(response), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error : {e}")
            return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": f"Failed to retreive countries: {str(e)}"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                       
@blp_preauth.route("/countries", methods=["GET"])
class CountryResource(MethodView):
    @public_read_limiter(
        entity_name="countries",
        limit_str="30 per minute; 300 per hour",
    )
    @blp_preauth.doc(
        summary="Retrieve countries",
        description="""
            This endpoint allows you to retrieve a list of countries.
            - **GET**: Retrieve country(s).
            - The request requires an `x-app-key` header with your app's key.
        """,
        security=[],
        responses={
            200: {
                "description": "Countries retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "id": 188,
                                    "capital": "San José",
                                    "citizenship": "Costa Rican",
                                    "country_code": 188,
                                    "currency": "Costa Rican colón (pl. colones)",
                                    "currency_code": "CRC",
                                    "currency_sub_unit": "céntimo",
                                    "currency_symbol": "₡",
                                    "currency_decimals": 2,
                                    "full_name": "Republic of Costa Rica",
                                    "iso_3166_2": "CR",
                                    "iso_3166_3": "CRI",
                                    "name": "Costa Rica",
                                    "region_code": 19,
                                    "sub_region_code": 13,
                                    "eea": 0,
                                    "calling_code": 506,
                                    "flag": "CR.png"
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
                            "message": "Missing or invalid x-app-key"
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
        """This function allows you to retreive countries list
        """
        client_ip = request.remote_addr
        log_tag = '[internal_controller.py][get_countries]'

        # verify that the request contain valid key and secret
        app_key = request.headers.get('x-app-key')
        app_secret = request.headers.get('x-app-secret')
        
        server_app_key = os.getenv("X_APP_KEY")
        server_app_secret = os.getenv("X_APP_SECRET")
        
        if str(app_key) != server_app_key or app_secret != server_app_secret:
            Log.info(f"{log_tag}[{client_ip}] invalid x-app-key or x-app-secret in header")
            return prepared_response(False, "UNAUTHORIZED", f"Unauthorized request.")
        
        try:
            Log.info(f"{log_tag} retrieving a list of countries IP: {client_ip}")
            countries = Essensial.countries()
        
            if countries:
                results = []
                for country in countries:
                    country["_id"] = str(country["_id"])
                    results.append(country)
            
                response = {
                    "success": True,
                    "status_code": 200,
                    "data": results
                }
                return jsonify(response)
            
            else:
                response = {
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to get countries"
                }
                return jsonify(response), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error : {e}")
            return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": f"Failed to retreive countries: {str(e)}"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

@blp_essentials.route("/post-codes", methods=["GET"])
class PostCodeResource(MethodView):
    @public_read_limiter(
        entity_name="post-codes",
        limit_str="30 per minute; 300 per hour",
    )
    @token_required
    @blp_essentials.doc(
        summary="Retrieve a list of postcode addresses",
        description="""
            This endpoint allows you to retrieve a list of postcode addresses for a given country and postcode.
            - **GET**: Retrieve the list of postcode addresses for the given `country_iso2` and `post_code`.
            - The request requires an `Authorization` header with a Bearer token.
            - The list of postcode addresses is fetched based on the `country_iso2` and `post_code` query parameters.
        """,
        security=[{"Bearer": []}],  # Only Bearer token authentication is required
        responses={
            200: {
                "description": "Postcode addresses retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "postcode": "1000",
                                    "city": "Accra",
                                    "district": "Greater Accra",
                                    "country": "GHA",
                                    "address": "Accra Central"
                                },
                                {
                                    "postcode": "2000",
                                    "city": "Kumasi",
                                    "district": "Ashanti",
                                    "country": "GHA",
                                    "address": "Kumasi Central"
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
                            "message": "Missing or invalid Bearer token"
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
    @blp_essentials.arguments(PostCodeSchema, location="query")
    def get(self, rate_data):
        """Returns a list of postcode addresses for the specified country and postcode.
        
        Args:
            country_iso2 (String): The 2-letter country ISO code.
            post_code (String): The starting postcode used to retrieve the postcode address details.
        
        Returns:
            Response: The API response containing the list of postcode addresses or an error message.
        """
        log_tag = '[internal_controller.py][PostcodeResource][get]'
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        user_id = str(user_info.get("_id"))
        
        try:
            Log.info(f"{log_tag} IP: {client_ip}")
            base_url = "https://ws.postcoder.com/pcw"
            api_service = ApiService(base_url)
        
            # Retrieve country_iso2 and post_code from the rate_data
            country_iso2 = rate_data.get("country_iso2")
            post_code = rate_data.get("post_code")
            
            Log.info(f"country_iso2: {country_iso2}")
        
            # Start the timer for performance measurement
            start_time = time.time()

            # Retrieve the postcode address information from the API
            response = api_service.get_post_code_address(user_id=user_id, post_code=post_code, country_iso2=country_iso2)

            # End the timer for performance measurement
            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{user_id}] retrieving postcode address completed in {duration:.2f} seconds")
            
            if response:
                jsonData = {
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "data" : response
                }
                return jsonify(jsonData), HTTP_STATUS_CODES["OK"]
            else:
                jsonData = {
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": "No postcode addresses found"
                }
                return jsonify(jsonData), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": f"Failed to retrieve postcode addresses: {str(e)}"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
