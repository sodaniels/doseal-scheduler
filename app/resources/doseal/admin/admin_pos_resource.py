# resources/pos_resource.py
import json
from datetime import datetime, date
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from bson.errors import InvalidId
from bson import ObjectId
from pymongo.errors import PyMongoError
from app import db

from .admin_business_resource import token_required
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
)
from ....utils.redis import get_redis
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....schemas.admin.sale_schema import (
    SaleSchema, CartPreviewRequestSchema, CartExecuteRequestSchema
)
from ....utils.helpers import sanitize_device_id

# model
from ....models.admin.setup_model import Outlet
from ....models.product_model import Product, Discount
from ....models.admin.setup_model import Tax
from ....models.admin.super_superadmin_model import Admin
from ....models.business_model import Business
# services
from ....services.pos.cart_service import CartService
from ....services.pos.sale.sale_service import SaleService
from ....services.pos.sale.sale_service import StockLedger
from ....services.pos.inventory_service import InventoryService

from ....services.gateways.doseal.transaction_gateway_service import (
    TransactionGatewayService
)
from ....utils.doseal.pre_transaction_checks import PreTransactionCheck
from ....services.gateways.doseal.gateway_service import GatewayService

from ....utils.json_response import prepared_response
from ....utils.helpers import make_log_tag
from ....constants.service_code import (
    HTTP_STATUS_CODES,
    SYSTEM_USERS
)
from ....utils.logger import Log


pos_blp = Blueprint("pos", __name__, description="POS and checkout operations")


# @pos_blp.route("/pos/checkout", methods=["POST"])
# class POSCheckoutResource(MethodView):

#     @token_required
#     @crud_write_limiter("pos_checkout")
#     @pos_blp.arguments(SaleSchema, location="json")
#     @pos_blp.response(
#         HTTP_STATUS_CODES["CREATED"], 
#         description="Sale created successfully"
#     )
#     def post(self, json_data):
#         """
#         Process POS checkout - create sale and adjust inventory.
#         Enhanced to support comprehensive reporting schema.
#         """

#         client_ip = request.remote_addr
#         user_info = g.get("current_user", {}) or {}

#         account_type = decrypt_data(user_info.get("account_type")) if user_info.get("account_type") else None
#         token_business_id = str(user_info.get("business_id"))
#         user_id = str(user_info.get("user_id"))
#         user__id = str(user_info.get("_id"))
#         agent_id = user_info.get("agent_id")
#         admin_id = user_info.get("admin_id")
#         cashier_id = user_info.get("_id")

#         # Determine business_id based on role
#         requested_business_id = json_data.get("business_id") or json_data.get("business_id")

#         if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]:
#             business_id = requested_business_id or token_business_id
#         else:
#             business_id = token_business_id

#         log_tag = make_log_tag(
#             "pos_resource.py",
#             "POSCheckoutResource",
#             "post",
#             client_ip,
#             user_id,
#             account_type,
#             token_business_id,
#             business_id,
#             cashier_id=cashier_id
#         )

#         # Validate business_id
#         if not business_id:
#             Log.error(f"{log_tag} BUSINESS_ID_REQUIRED")
#             return prepared_response(
#                 status=False,
#                 status_code="BAD_REQUEST",
#                 message="Business ID is required",
#                 errors=["business_id is required"]
#             )

#         try:
#             # CORE FIELDS - REQUIRED
#             outlet_id = json_data.get("outlet_id")
#             cart = json_data.get("cart")
#             payment_method = json_data.get("payment_method")
            
#             # CUSTOMER - OPTIONAL
#             customer_id = json_data.get("customer_id")
            
#             # STATUS - OPTIONAL (defaults to Completed)
#             status = json_data.get("status", "Completed")
            
#             # FINANCIAL - OPTIONAL
#             amount_paid = json_data.get("amount_paid")
            
#             # TRANSACTION IDENTIFIERS - OPTIONAL
#             transaction_number = json_data.get("transaction_number")
#             receipt_number = json_data.get("receipt_number")
            
#             # DISCOUNT & PROMOTION - OPTIONAL
#             discount_type = json_data.get("discount_type")
#             coupon_code = json_data.get("coupon_code")
#             promotion_id = json_data.get("promotion_id")
            
#             # REFUND/VOID - OPTIONAL
#             refund_reason = json_data.get("refund_reason")
#             void_reason = json_data.get("void_reason")
#             authorized_by = json_data.get("authorized_by")
            
            
#             try:
#                 #get cash_session_id in redis
#                 redisKey = f'cash_session_token_{token_business_id}_{user__id}'
#                 cash_session_id_encoded = get_redis(redisKey)
                
#                 if cash_session_id_encoded is None:
#                     Log.error(f"{log_tag} Cash Session has not been open")
#                     return prepared_response(
#                         status=False,
#                         status_code="BAD_REQUEST",
#                         message=f"Cash Session has not been open",
#                     )
                    
#                 cash_session_id_string = cash_session_id_encoded.decode('utf-8')
#                 if cash_session_id_string:
#                     cash_session_id = ObjectId(cash_session_id_string)
                    
#             except Exception as e:
#                 Log.error(f"{log_tag} Open failed: {e}")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message=f"Failed to open cash session",
#                 )
                
            
#             # OPERATIONAL - OPTIONAL
#             device_id = json_data.get("device_id")
            
#             # METADATA - OPTIONAL
#             notes = json_data.get("notes")
#             reference_note = json_data.get("reference_note")

#             # Validate required fields
#             if not outlet_id:
#                 Log.error(f"{log_tag} OUTLET_ID_REQUIRED")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Outlet ID is required",
#                     errors=["outlet_id is required"]
#                 )

#             if not cart:
#                 Log.error(f"{log_tag} CART_REQUIRED")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Cart is required",
#                     errors=["cart is required"]
#                 )

#             if not payment_method:
#                 Log.error(f"{log_tag} PAYMENT_METHOD_REQUIRED")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Payment method is required",
#                     errors=["payment_method is required"]
#                 )

#             # Validate ObjectId formats
#             try:
#                 ObjectId(outlet_id)
#                 if customer_id:
#                     ObjectId(customer_id)
#                 if promotion_id:
#                     ObjectId(promotion_id)
#                 if authorized_by:
#                     ObjectId(authorized_by)
#                 if cash_session_id:
#                     ObjectId(cash_session_id)
#             except Exception as e:
#                 Log.error(f"{log_tag} INVALID_ID_FORMAT: {str(e)}")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Invalid ID format",
#                     errors=[f"Invalid ID format: {str(e)}"]
#                 )

#             # Validate cart structure
#             if not cart.get("lines") or not isinstance(cart.get("lines"), list):
#                 Log.error(f"{log_tag} INVALID_CART_STRUCTURE")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Invalid cart structure",
#                     errors=["cart.lines must be a non-empty array"]
#                 )

#             if not cart.get("totals") or not isinstance(cart.get("totals"), dict):
#                 Log.error(f"{log_tag} INVALID_CART_TOTALS")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Invalid cart totals",
#                     errors=["cart.totals is required"]
#                 )

#             # Validate required cart.totals fields
#             required_totals = ["subtotal", "total_discount", "total_tax", "total_cost", "grand_total"]
#             missing_totals = [field for field in required_totals if field not in cart["totals"]]
#             if missing_totals:
#                 Log.error(f"{log_tag} MISSING_CART_TOTALS: {missing_totals}")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message="Missing required cart totals",
#                     errors=[f"Missing cart.totals fields: {', '.join(missing_totals)}"]
#                 )

#             # Validate each line item has required fields
#             required_line_fields = [
#                 "product_id", "product_name", "category", "quantity", 
#                 "unit_price", "unit_cost", "tax_rate", "tax_amount", 
#                 "subtotal", "line_total"
#             ]
            
#             for idx, line in enumerate(cart["lines"]):
#                 missing_fields = [field for field in required_line_fields if field not in line]
#                 if missing_fields:
#                     Log.error(f"{log_tag} MISSING_LINE_FIELDS at index {idx}: {missing_fields}")
#                     return prepared_response(
#                         status=False,
#                         status_code="BAD_REQUEST",
#                         message=f"Missing required fields in cart line {idx}",
#                         errors=[f"Line {idx} missing: {', '.join(missing_fields)}"]
#                     )

#             # Create sale with enhanced schema
#             Log.info(f"{log_tag} Creating sale (grand_total={cart['totals']['grand_total']})")
#             success, sale_id, error = SaleService.create_sale_from_cart(
#                 business_id=business_id,
#                 outlet_id=outlet_id,
#                 user_id=user_id,
#                 user__id=user__id,
#                 cart=cart,
#                 payment_method=payment_method,
#                 # Core fields
#                 cashier_id=cashier_id,
#                 customer_id=customer_id,
#                 status=status,
#                 amount_paid=amount_paid,
#                 # Transaction identifiers
#                 transaction_number=transaction_number,
#                 receipt_number=receipt_number,
#                 # Discount & promotion
#                 discount_type=discount_type,
#                 coupon_code=coupon_code,
#                 promotion_id=promotion_id,
#                 # Refund/void tracking
#                 refund_reason=refund_reason,
#                 void_reason=void_reason,
#                 authorized_by=authorized_by,
#                 # Operational tracking
#                 cash_session_id=cash_session_id,
#                 device_id=device_id,
#                 # Metadata
#                 notes=notes,
#                 reference_note=reference_note,
#                 # Legacy fields
#                 agent_id=agent_id,
#                 admin_id=admin_id,
#             )

#             if not success:
#                 Log.error(f"{log_tag} SALE_CREATION_FAILED: {error}")
#                 return prepared_response(
#                     status=False,
#                     status_code="BAD_REQUEST",
#                     message=f"Sale creation failed: {error}",
#                     errors=[error]
#                 )

#             Log.info(f"{log_tag} Sale created successfully sale_id={sale_id}")

#             return prepared_response(
#                 status=True,
#                 status_code="CREATED",
#                 message="Sale completed successfully",
#                 data={
#                     "sale_id": sale_id,
#                     "transaction_number": transaction_number,
#                     "receipt_number": receipt_number,
#                     "cart": cart
#                 }
#             )

#         except Exception as e:
#             Log.error(f"{log_tag} INTERNAL_SERVER_ERROR {str(e)}")
#             return prepared_response(
#                 status=False,
#                 status_code="INTERNAL_SERVER_ERROR",
#                 message="An error occurred during checkout",
#                 errors=[str(e)]
#             )


#==================================
#INITIATE POS REQUEST
#==================================
@pos_blp.route("/pos/checkout/initiate", methods=["POST"])
class POSCartInitiateResource(MethodView):
    """
    Build a cart for preview/confirmation before final checkout.
    Enhanced with proper discount handling and validation.
    """
    
    @token_required
    @crud_read_limiter("pos_cart_initiate")
    @pos_blp.arguments(CartPreviewRequestSchema, location="json")
    @pos_blp.response(HTTP_STATUS_CODES["OK"])
    def post(self, transaction_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        admin_id = str(user_info.get("_id"))

        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        tenant_id_enc = user_info.get("tenant_id")
        tenant_id = decrypt_data(decrypt_data(tenant_id_enc)) if tenant_id_enc else None
        

        auth_business_obj = user_info.get("business_id")
        auth_business_id = str(auth_business_obj) if auth_business_obj else None
        user_id = str(user_info.get("user_id")) if user_info.get("user_id") else None

        # Role-aware business selection
        requested_business_id = transaction_data.get("business_id")
        if account_type in (SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
            
        transaction_data["account_type"] = account_type
        transaction_data["business_id"] = business_id
        transaction_data["tenant_id"] = tenant_id
        transaction_data["cashier_id"] = admin_id
        transaction_data["user__id"] = admin_id
        transaction_data["user_id"] = user_id

        log_tag = make_log_tag(
            "admin_pos_resource.py",
            "POSCartInitiateResource",
            "post",
            client_ip,
            user_id,
            account_type,
            auth_business_id,
            business_id,
        )

        if not business_id:
            Log.error(f"{log_tag} BUSINESS_ID_REQUIRED")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="Business ID is required.",
                errors=["business_id is required or must be resolvable from token"],
            )
        

        #####################PRE TRANSACTION CHECKS#########################
        # 1. check pre transaction requirements for outlet
        pre_transaction_check = PreTransactionCheck(
            admin_id=admin_id, 
            business_id=business_id,
            account_type=account_type
        )
        initial_check_result = pre_transaction_check.initial_transaction_checks()
        
        if initial_check_result is not None:
            return initial_check_result

        #####################PRE TRANSACTION CHECKS#########################
        
        try:
            #get cash_session_id in redis
            redisKey = f'cash_session_token_{business_id}_{admin_id}'
            cash_session_id_encoded = get_redis(redisKey)
            
            if cash_session_id_encoded is None:
                Log.error(f"{log_tag} Cash Session has not been open")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Cash Session has not been open",
                )
                
            cash_session_id_string = cash_session_id_encoded.decode('utf-8')
            if cash_session_id_string:
                cash_session_id = cash_session_id_string
                transaction_data["cash_session_id"] = cash_session_id
                
                
                
        except Exception as e:
            Log.error(f"{log_tag} Open failed: {e}")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message=f"Failed to open cash session",
            )
        
        
    # Initializing transaction
        try:
            Log.info(f"{log_tag}[{client_ip}] initiatring transaction")
            
            response = TransactionGatewayService.initiate_input(transaction_data)
        
            return response
        
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error initiatring transaction: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred while initiating transaction.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


#==================================
#EXECUTE POS REQUEST
#==================================
@pos_blp.route("/pos/checkout/execute", methods=["POST"])
class POSCartExecuteResource(MethodView):
    """
    Excute the cart and process payment
    """
    
    @token_required
    @crud_read_limiter("pos_cart_execute")
    @pos_blp.arguments(CartExecuteRequestSchema, location="json")
    @pos_blp.response(HTTP_STATUS_CODES["OK"])
    def post(self, request_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        admin_id = str(user_info.get("_id"))

        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        tenant_id_enc = user_info.get("tenant_id")
        tenant_id = decrypt_data(decrypt_data(tenant_id_enc)) if tenant_id_enc else None
        

        auth_business_obj = user_info.get("business_id")
        auth_business_id = str(auth_business_obj) if auth_business_obj else None
        user_id = str(user_info.get("user_id")) if user_info.get("user_id") else None

        # Role-aware business selection
        requested_business_id = request_data.get("business_id")
        if account_type in (SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
            

        log_tag = make_log_tag(
            "admin_pos_resource.py",
            "POSCartExecuteResource",
            "post",
            client_ip,
            user_id,
            account_type,
            auth_business_id,
            business_id,
        )

        if not business_id:
            Log.error(f"{log_tag} BUSINESS_ID_REQUIRED")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="Business ID is required.",
                errors=["business_id is required or must be resolvable from token"],
            )
        

        #####################PRE TRANSACTION CHECKS#########################
        # 1. check pre transaction requirements for outlet
        pre_transaction_check = PreTransactionCheck(
            admin_id=admin_id, 
            business_id=business_id,
            account_type=account_type
        )
        initial_check_result = pre_transaction_check.initial_transaction_checks()
        
        if initial_check_result is not None:
            return initial_check_result

        #####################PRE TRANSACTION CHECKS#########################
        
        
        try:
            
            request_details = None
            decrypted_transaction = None
            device_id = sanitize_device_id(request_data.get("device_id"))

            checksum = request_data.get("checksum", None)
            checksum_hash_transformed = str.lower(checksum)
            
            encrypted_transaction = get_redis(checksum_hash_transformed)
            
            if encrypted_transaction is None:
                message = f"The transaction has expired or invalid"
                Log.info(f"{log_tag} {message}")
                return prepared_response(False, "BAD_REQUEST", f"{message}")
            
            
            encrypted_hased_private_decoded = encrypted_transaction.decode("utf-8")
            Log.info(f"encrypted_hased_private_decoded: {encrypted_hased_private_decoded}")
            
            redis_key_string = f"{device_id}_{encrypted_hased_private_decoded}"
            
            encrypted_transaction_main = get_redis(redis_key_string)
            
            if encrypted_transaction_main is None:
                message = f"The transaction has expired or invalid"
                Log.info(f"{log_tag} {message}")
                return prepared_response(False, "BAD_REQUEST", f"{message}")
            
            if encrypted_transaction_main:
                encrypted_transaction_decode = encrypted_transaction_main.decode("utf-8")
                decrypted_transaction_obj = decrypt_data(encrypted_transaction_decode)
            
            request_details = json.loads(decrypted_transaction_obj)
        
            # Validating transaction details failed
            if request_details is None:
                Log.info(f"{log_tag} request validation failed.")
                return prepared_response(False, "BAD_REQUEST", f"Request validation failed.")
            
            # initialize gateway service with tenant ID
            gateway_service = GatewayService(tenant_id)
            
            json_response = gateway_service.execute_request_execute(checksum, **request_details)
        
            return json_response
            
        except Exception as e:
            Log.info(f"{log_tag} error retrieving request from redis: {str(e)}")
            return prepared_response(False, "BAD_REQUEST", f"An eror ocurred while executing request. Error: {str(e)}")





