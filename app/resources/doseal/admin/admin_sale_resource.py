# resources/sale_resource.py
from flask import g, request
import time
from flask.views import MethodView
from pymongo.errors import PyMongoError
from flask_smorest import Blueprint
from bson import ObjectId

from ....utils.json_response import prepared_response
from .admin_business_resource import token_required
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
    sale_refund_limiter,
)
from ....utils.helpers import make_log_tag
from ....utils.crypt import decrypt_data
from ....services.pos_ledger_service import (
    place_stock_hold,
    capture_stock_hold,
    release_stock_hold,
    release_expired_stock_holds
)
from ....utils.pos_idempotent_keys import (
    keys_for_stock_hold,
    keys_for_stock_release_expired,
    keys_for_stock_release,
    keys_for_stock_capture
)
from ....schemas.admin.pos_schemas import (
    VoidSaleRequestSchema,
    VoidSaleQuerySchema,
    SaleIdQuerySchema,
    SalesListQuerySchema
)
from ....schemas.admin.product_schema import SaleRefundSchema

from ....models.admin.sale import Sale
from ....services.pos.sale.sale_service import SaleService
from ....utils.json_response import prepared_response
from ....constants.service_code import HTTP_STATUS_CODES
from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS
)
from ....utils.logger import Log


sale_blp = Blueprint( "sale",__name__, description="Sale management operations")


@sale_blp.route("sale")
class SaleResource(MethodView):
    """Single sale retrieval."""
    
    @token_required
    @crud_read_limiter("sale")
    @sale_blp.arguments(SaleIdQuerySchema, location="query")
    @sale_blp.response(HTTP_STATUS_CODES["OK"], description="Sale retrieved")
    def get(self, query_args):
        """
        Get a single sale by ID.
        
        Role-aware:
        - SUPER_ADMIN/SYSTEM_OWNER can pass business_id
        - BUSINESS_OWNER sees sales in their business
        - Staff see only their own sales
        """
        client_ip = request.remote_addr
        account_type = g.current_user.get("account_type")
        token_business_id = g.current_user.get("business_id")
        token_user__id = g.current_user.get("_id")
        
        # Determine business_id (role-aware)
        requested_business_id = query_args.get("business_id")
        
        if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]:
            business_id = requested_business_id or token_business_id
        else:
            business_id = token_business_id
        
        log_tag = f"[sale_resource.py][SaleResource][get][{client_ip}][{business_id}]"
        
        try:
            sale_id = query_args.get("sale_id")
            
            # Validate ObjectId
            try:
                ObjectId(sale_id)
            except Exception:
                Log.error(f"{log_tag} Invalid sale ID format")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Invalid sale ID format",
                    errors=["Invalid sale_id format"],
                )
            
            # Fetch sale
            sale = Sale.get_by_id(sale_id=sale_id, business_id=business_id)
            
            if not sale:
                Log.error(f"{log_tag} Sale not found.s")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Sale not found.",
                    errors=["Sale not found."],
                )
            
            # Additional role-based filtering
            if account_type not in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["BUSINESS_OWNER"]]:
                # Staff can only see their own sales
                if str(sale.get("user__id")) != str(token_user__id):
                    Log.error(f"{log_tag} Access denied - not sale creator")
                    return prepared_response(
                        status=False,
                        status_code="FORBIDDEN",
                        message="Access denied",
                        errors=["You can only view your own sales"],
                    )
            
            Log.info(f"{log_tag} Sale retrieved: {sale_id}")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sale retrieved successfully",
                data={"sale": sale},
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving sale",
                errors=[str(e)]
            )


@sale_blp.route("/sales")
class SalesListResource(MethodView):
    """List sales with filters."""
    
    @token_required
    @crud_read_limiter("sales_list")
    @sale_blp.arguments(SalesListQuerySchema, location="query")
    @sale_blp.response(HTTP_STATUS_CODES["OK"], description="Sales list retrieved")
    def get(self, query_args):
        """
        List sales with pagination and filters.
        
        Role-aware:
        - SUPER_ADMIN/SYSTEM_OWNER can query any business
        - BUSINESS_OWNER sees all sales in their business
        - Staff see only their own sales
        """
        client_ip = request.remote_addr
        account_type = g.current_user.get("account_type")
        token_business_id = g.current_user.get("business_id")
        token_user__id = g.current_user.get("_id")
        
        # Determine business_id (role-aware)
        requested_business_id = query_args.get("business_id")
        
        if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]:
            business_id = requested_business_id or token_business_id
        else:
            business_id = token_business_id
        
        log_tag = f"[sale_resource.py][SalesListResource][get][{client_ip}][{business_id}]"
        
        try:
            outlet_id = query_args.get("outlet_id")
            status = query_args.get("status")
            page = query_args.get("page", 1)
            per_page = query_args.get("per_page", 50)
            
            # Get sales based on role
            if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["BUSINESS_OWNER"]]:
                # Can see all sales in business
                result = Sale.get_by_business_id(
                    business_id=business_id,
                    page=page,
                    per_page=per_page,
                    status=status,
                    outlet_id=outlet_id
                )
            else:
                # Staff see only their own sales
                # Note: This requires a custom method in Sale model
                # For now, fetch all and filter in memory (not optimal for production)
                result = Sale.get_by_business_id(
                    business_id=business_id,
                    page=page,
                    per_page=per_page,
                    status=status,
                    outlet_id=outlet_id
                )
                
                # Filter to only user's sales
                result["sales"] = [
                    sale for sale in result.get("sales", [])
                    if str(sale.get("user__id")) == str(token_user__id)
                ]
                result["total"] = len(result["sales"])
            
            Log.info(f"{log_tag} Retrieved {len(result.get('sales', []))} sales")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sales retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving sales",
                errors=[str(e)]
            )



@sale_blp.route("/sale/void")
class VoidSaleResource(MethodView):
    """Void a sale and reverse inventory."""
    
    @token_required
    @crud_delete_limiter("void_sale")
    @sale_blp.arguments(VoidSaleQuerySchema, location="query")
    @sale_blp.arguments(VoidSaleRequestSchema, location="json")
    @sale_blp.response(HTTP_STATUS_CODES["OK"], description="Sale voided")
    def post(self, query_args, json_data):
        """
        Void a sale and restore inventory.
        
        Role-aware:
        - SUPER_ADMIN/SYSTEM_OWNER can void any sale in any business
        - BUSINESS_OWNER can void sales in their business
        - Staff cannot void sales (permission-based)
        
        TODO: Add permission check for 'void_sale' permission
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("admin_id")
        

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = query_args.get("business_id") or json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
        
        # log_tag = f"[sale_resource.py][VoidSaleResource][post][{client_ip}][{business_id}]"
        
        log_tag = make_log_tag(
            "sale_resource.py",
            "VoidSaleResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        
        try:
            # Permission check (basic)
            if account_type not in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["BUSINESS_OWNER"]]:
                Log.error(f"{log_tag} Insufficient permissions to void sales")
                return prepared_response(
                    status=False,
                    status_code="FORBIDDEN",
                    message="You do not have permission to void sales",
                    errors=["void_sale permission required"]
                )
            
            sale_id = json_data.get("sale_id")
            reason = json_data.get("reason")
            
            if not sale_id:
                Log.error(f"{log_tag} Sale ID required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Sale ID is required",
                    errors=["sale_id is required"]
                )
            
            # Validate ObjectId
            try:
                ObjectId(sale_id)
            except Exception:
                Log.error(f"{log_tag} Invalid sale ID format")
                return prepared_response(
                    success=False,
                    status_code="BAD_REQUEST",
                    message="Invalid sale ID format",
                    errors=["Invalid sale_id format"]
                )
            
            # Fetch sale to get outlet_id
            sale = Sale.get_by_id(sale_id=sale_id, business_id=target_business_id)
            
            if not sale:
                Log.error(f"{log_tag} Sale not found.")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Sale not found.",
                    errors=["Sale not found."]
                )
            
            outlet_id = sale.get("outlet_id")
            sale_hold_id = sale.get("hold_id")
            
            # Void the sale
            Log.info(f"{log_tag} Voiding sale {sale_id}")
            success, error = SaleService.void_sale(
                sale_id=sale_id,
                business_id=target_business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                reason=reason,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            if not success:
                Log.error(f"{log_tag} Void failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to void sale: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} Sale voided successfully: {sale_id}")
            
            try:
                k = keys_for_stock_release(target_business_id, sale_hold_id, reason="payment_failed")

                res = release_stock_hold(
                    business_id=target_business_id,
                    hold_id=sale_hold_id,
                    idempotency_key=k.idem,
                    reason="payment_failed"
                )
                Log.info(f"res state: {res}")
            except Exception as e:
                Log.error(f"{log_tag} Error: {str(e)}")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Error releasing stock",
                    errors=[str(e)]
                )
               
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sale voided successfully",
                data={"sale_id": sale_id}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error voiding sale",
                errors=[str(e)]
            )

    # ---------------------- REFUND SALE (role-aware) ---------------------- #
    @sale_blp.route("/sale/refund", methods=["POST"])
    class SaleRefundResource(MethodView):
        @token_required
        @sale_refund_limiter("salerefund")
        @sale_blp.arguments(SaleRefundSchema, location="form")
        @sale_blp.response(200)
        @sale_blp.doc(
            summary="Refund a sale (role-aware)",
            description="""
                Create a refund transaction for an existing sale.

                • SYSTEM_OWNER / SUPER_ADMIN:
                    - may submit business_id in the form to target any business
                    - if omitted, defaults to their own business_id

                • Other roles:
                    - always restricted to their own business_id.

                If `refund_amount` is omitted, a full refund is performed.

                A new Sale record is created to represent the refund, with:
                    - a cart whose `totals.grand_total` is negative for the refunded amount
                    - `amount_paid` negative for the refunded amount
                    - linked to the original sale logically via `reference_note`.

                The original sale's status is updated to:
                    - `Refunded` for full refund
                    - `Partially_Refunded` for partial refund
            """,
            security=[{"Bearer": []}],
        )
        def post(self, payload):
            sale_id = payload.get("sale_id")
            form_business_id = payload.get("business_id")
            refund_amount = payload.get("refund_amount")
            refund_date = payload.get("date")       # optional, used to stamp refund cart
            reason = payload.get("reason")
            outlet_id = payload.get("outlet_id")    # optional; falls back to original sale outlet

            client_ip = request.remote_addr
            user_info = g.get("current_user", {}) or {}

            auth_user__id = str(user_info.get("_id"))
            auth_business_id = str(user_info.get("business_id"))
            account_type_enc = user_info.get("account_type")
            account_type = decrypt_data(account_type_enc) if account_type_enc else None

            agent_id = user_info.get("agent_id")
            admin_id = user_info.get("admin_id")

            # Resolve target business
            if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
                target_business_id = form_business_id
            else:
                target_business_id = auth_business_id

            log_tag = make_log_tag(
                "admin_admin_product_resource.py",
                "SaleRefundResource",
                "post",
                client_ip,
                auth_user__id,
                account_type,
                auth_business_id,
                target_business_id,
            )

            if not sale_id:
                Log.info(f"{log_tag} sale_id must be provided")
                return prepared_response(False, "BAD_REQUEST", "sale_id must be provided.")

            # -------------------- Fetch original sale -------------------- #
            try:
                original_sale = Sale.get_by_id(sale_id, target_business_id)
            except Exception as e:
                Log.info(f"{log_tag} error fetching original sale for refund: {e}")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "An unexpected error occurred while retrieving the original sale.",
                    errors=str(e),
                )

            if not original_sale:
                Log.info(f"{log_tag} original sale not found")
                return prepared_response(False, "NOT_FOUND", "Original sale not found.")

            current_status = (original_sale.get("status") or "").strip()

            # Disallow refunds for voided / already refunded sales
            if current_status in {
                Sale.STATUS_VOIDED,
                Sale.STATUS_REFUNDED,
            }:
                Log.info(f"{log_tag} cannot refund sale with status={current_status}")
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    f"Cannot refund a sale with status '{current_status}'.",
                )

            # -------------------- Determine original total -------------------- #
            original_cart = original_sale.get("cart") or {}
            original_totals = (original_cart.get("totals") or {}).copy()
            original_total = float(original_totals.get("grand_total") or 0.0)

            # -------------------- Determine refund amount -------------------- #
            if refund_amount is None:
                # Full refund
                refund_amount_value = original_total
            else:
                try:
                    refund_amount_value = float(refund_amount)
                except (TypeError, ValueError):
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Refund amount must be a valid number.",
                    )

                if refund_amount_value <= 0:
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Refund amount must be greater than zero.",
                    )
                if refund_amount_value > original_total:
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Refund amount cannot exceed original sale total.",
                    )

            # Decide new status for original sale
            if refund_amount_value == original_total:
                new_original_status = Sale.STATUS_REFUNDED
            else:
                new_original_status = Sale.STATUS_PARTIALLY_REFUNDED

            # -------------------- Build refund sale cart -------------------- #
            # We reuse the original cart structure but override grand_total (and optionally stamp refund date)
            refund_totals = original_totals.copy()
            refund_totals["grand_total"] = -abs(refund_amount_value)

            refund_cart = original_cart.copy()
            refund_cart["totals"] = refund_totals

            if refund_date:
                # Optional: store refund date inside cart metadata
                meta = refund_cart.get("meta", {})
                meta["refund_date"] = refund_date
                refund_cart["meta"] = meta

            # If outlet not passed, fallback to original sale outlet
            target_outlet_id = outlet_id or original_sale.get("outlet_id")

            # Payment method: mirror original or fallback to CASH
            original_payment_method = original_sale.get("payment_method", Sale.PAYMENT_CASH)

            refund_reference_note = reason or f"Refund for sale {sale_id}"

            # For accounting symmetry, amount_paid is negative refund_amount_value
            refund_amount_paid = -abs(refund_amount_value)

            # -------------------- Create refund sale -------------------- #
            try:
                Log.info(f"{log_tag} creating refund sale")
                start_time = time.time()

                refund_sale = Sale(
                    business_id=target_business_id,
                    outlet_id=target_outlet_id,
                    user_id=user_info.get("user_id"),
                    user__id=auth_user__id,
                    payment_method=original_payment_method,
                    cart=refund_cart,
                    amount_paid=refund_amount_paid,
                    customer_id=original_sale.get("customer_id"),
                    status=Sale.STATUS_COMPLETED,
                    reference_note=refund_reference_note,
                    agent_id=agent_id,
                    admin_id=admin_id,
                )
                refund_sale_id = refund_sale.save()

                # -------------------- Update original sale status -------------------- #
                Sale.update_status(
                    sale_id=sale_id,
                    business_id=target_business_id,
                    new_status=new_original_status,
                    note=reason,
                )

                duration = time.time() - start_time
                Log.info(
                    f"{log_tag} refund sale created with id={refund_sale_id} "
                    f"in {duration:.2f} seconds (original_status -> {new_original_status})"
                )

                return prepared_response(
                    True,
                    "OK",
                    "Refund processed successfully.",
                    data={
                        "refund_sale_id": str(refund_sale_id),
                        "original_sale_id": str(sale_id),
                        "original_status": new_original_status,
                        "refunded_amount": refund_amount_value,
                    },
                )

            except PyMongoError as e:
                Log.info(f"{log_tag} PyMongoError while creating refund sale: {e}")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "An unexpected error occurred while processing the refund.",
                    errors=str(e),
                )

            except Exception as e:
                Log.info(f"{log_tag} unexpected error while creating refund sale: {e}")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "An unexpected error occurred.",
                    errors=str(e),
                )
                
















