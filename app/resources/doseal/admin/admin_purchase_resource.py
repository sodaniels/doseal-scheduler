# resources/purchase_resource.py
from datetime import datetime
from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from bson import ObjectId

from .admin_business_resource import token_required
from ....schemas.admin.purchase_schemas import (
    PurchaseOrderCreateSchema,
    PurchaseOrderUpdateSchema,
    PurchaseOrderIdQuerySchema,
    PurchaseOrdersListQuerySchema,
    ReceiveStockSchema
)
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter
)
from ....utils.logger import Log # import logging
from ....extensions.db import db
from ....models.admin.purchase_order import PurchaseOrder
from ....services.pos.purchase_service import PurchaseService
from ....utils.json_response import prepared_response
from ....utils.helpers import make_log_tag
from ....utils.crypt import decrypt_data
from ....constants.service_code import (
    HTTP_STATUS_CODES,SYSTEM_USERS
)

purchase_blp = Blueprint("Purchase", __name__, description="Purchase order and receiving operations"
)


@purchase_blp.route("/purchase/purchase-order")
class PurchaseOrderResource(MethodView):
    """Purchase order CRUD operations."""
    
    @token_required
    @crud_write_limiter(entity_name="purchase_order")
    @purchase_blp.arguments(PurchaseOrderCreateSchema, location="json")
    @purchase_blp.response(HTTP_STATUS_CODES["CREATED"])
    @purchase_blp.doc(
        summary="Create purchase order",
        description="""
            Create a new purchase order for supplier ordering.
            
            Role-aware:
            - SUPER_ADMIN/SYSTEM_OWNER can pass business_id
            - Others use their token business_id
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Create new purchase order."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("_id")
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "PurchaseOrderResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            outlet_id = json_data.get("outlet_id")
            supplier_id = json_data.get("supplier_id")
            ordered_items = json_data.get("ordered_items", [])
            expected_date = json_data.get("expected_date")
            notes = json_data.get("notes")
            
            # Validate required fields
            if not outlet_id or not supplier_id:
                Log.error(f"{log_tag} Missing required fields")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="outlet_id and supplier_id are required",
                    errors=["outlet_id and supplier_id are required"]
                )
            
            # Create PO
            Log.info(f"{log_tag} Creating purchase order with {len(ordered_items)} items")
            success, po_id, error = PurchaseService.create_purchase_order(
                business_id=business_id,
                outlet_id=outlet_id,
                supplier_id=supplier_id,
                user_id=user_id,
                user__id=user__id,
                ordered_items=ordered_items,
                expected_date=expected_date,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            if not success:
                Log.error(f"{log_tag} PO creation failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Purchase order creation failed: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} PO created successfully: {po_id}")
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Purchase order created successfully",
                data={"po_id": po_id}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error creating purchase order",
                errors=[str(e)]
            )
    
    @token_required
    @crud_read_limiter(entity_name="purchase_order")
    @purchase_blp.arguments(PurchaseOrderIdQuerySchema, location="query")
    @purchase_blp.response(HTTP_STATUS_CODES["OK"])
    @purchase_blp.doc(
        summary="Get purchase order by ID",
        description="Retrieve a single purchase order with full details.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Get single purchase order."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        po_id = query_args.get("po_id")
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "PurchaseOrderResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            po_id=po_id
        )
        
        try:
            if not po_id:
                Log.error(f"{log_tag} po_id is required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="po_id is required",
                )
            
            po = PurchaseOrder.get_by_id(po_id=po_id, business_id=business_id)
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Purchase order not found",
                )
            
            Log.info(f"{log_tag} PO retrieved successfully")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Purchase order retrieved successfully",
                data={"purchase_order": po}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving purchase order",
                errors=[str(e)]
            )
    
    @token_required
    @crud_write_limiter(entity_name="purchase_order")
    @purchase_blp.arguments(PurchaseOrderUpdateSchema, location="json")
    @purchase_blp.response(HTTP_STATUS_CODES["OK"])
    @purchase_blp.doc(
        summary="Update purchase order",
        description="Update PO details (only in Draft status).",
        security=[{"Bearer": []}],
    )
    def patch(self, json_data):
        """Update purchase order."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        po_id = json_data.get("po_id")
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "PurchaseOrderResource",
            "patch",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            po_id=po_id
        )
        
        try:
            if not po_id:
                Log.error(f"{log_tag} po_id is required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="po_id is required"
                )
            
            # Fetch PO
            po = PurchaseOrder.get_by_id(po_id=po_id, business_id=business_id)
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Purchase order not found"
                )
            
            # Only allow updates in Draft status
            if po.get("status") != PurchaseOrder.STATUS_DRAFT:
                Log.error(f"{log_tag} Cannot update PO in status: {po.get('status')}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Can only update purchase orders in Draft status"
                )
            
            # Build update dict (exclude po_id and business_id)
            updates = {k: v for k, v in json_data.items() if k not in ["po_id", "business_id"] and v is not None}
            
            if not updates:
                Log.error(f"{log_tag} No fields to update")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="No fields to update"
                )
            
            # Update PO
            update_doc = {}
            if "ordered_items" in updates:
                update_doc["ordered_items"] = updates["ordered_items"]
                # Recalculate totals
                update_doc["subtotal"] = sum(item.get("line_total", 0) for item in updates["ordered_items"])
                update_doc["total_items"] = sum(item.get("quantity", 0) for item in updates["ordered_items"])
            
            if "expected_date" in updates:
                update_doc["expected_date"] = updates["expected_date"]
            
            if "notes" in updates:
                update_doc["notes"] = updates["notes"]
            
            update_doc["updated_at"] = datetime.utcnow()
            
            collection = db.get_collection(PurchaseOrder.collection_name)
            result = collection.update_one(
                {"_id": ObjectId(po_id), "business_id": ObjectId(business_id)},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} PO updated successfully")
                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="Purchase order updated successfully"
                )
            else:
                Log.error(f"{log_tag} Failed to update PO")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Failed to update purchase order"
                )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error updating purchase order",
                errors=[str(e)]
            )


@purchase_blp.route("/purchase/purchase-orders")
class PurchaseOrdersListResource(MethodView):
    """List purchase orders with filtering."""
    
    @token_required
    @crud_read_limiter(entity_name="purchase_orders")
    @purchase_blp.arguments(PurchaseOrdersListQuerySchema, location="query")
    @purchase_blp.response(HTTP_STATUS_CODES["OK"])
    @purchase_blp.doc(
        summary="List purchase orders",
        description="Get paginated list of purchase orders with optional filters.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """List purchase orders."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        status = query_args.get("status")
        supplier_id = query_args.get("supplier_id")
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "PurchaseOrdersListResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            supplier_id=supplier_id,
            status=status,
        )
        
        try:
            result = PurchaseOrder.get_by_business_id(
                business_id=business_id,
                page=page,
                per_page=per_page,
                status=status,
                supplier_id=supplier_id
            )
            
            Log.info(f"{log_tag} Retrieved {len(result.get('purchase_orders', []))} POs")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Purchase orders retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving purchase orders",
                errors=[str(e)]
            )


@purchase_blp.route("/purchase/purchase-order/issue")
class IssuePurchaseOrderResource(MethodView):
    """Issue purchase order to supplier."""
    
    @token_required
    @crud_write_limiter(entity_name="issue_purchase_order")
    @purchase_blp.arguments(PurchaseOrderIdQuerySchema, location="json")
    @purchase_blp.response(HTTP_STATUS_CODES["OK"])
    @purchase_blp.doc(
        summary="Issue purchase order",
        description="Send/issue purchase order to supplier (Draft → Issued).",
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Issue purchase order."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        po_id = json_data.get("po_id")
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "IssuePurchaseOrderResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            po_id=po_id,
        )
        
        try:
            if not po_id:
                Log.error(f"{log_tag} po_id is required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="po_id is required"
                )
            
            success, error = PurchaseService.issue_purchase_order(
                po_id=po_id,
                business_id=business_id,
                user_id=user_id,
                user__id=user__id
            )
            
            if not success:
                Log.error(f"{log_tag} Issue failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to issue purchase order: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} PO issued successfully")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Purchase order issued successfully",
                data={"po_id": po_id}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error issuing purchase order",
                errors=[str(e)]
            )


@purchase_blp.route("/purchase/receive")
class ReceiveStockResource(MethodView):
    """Receive stock against purchase order."""
    
    @token_required
    @crud_write_limiter(entity_name="receive_stock")
    @purchase_blp.arguments(ReceiveStockSchema, location="json")
    @purchase_blp.response(HTTP_STATUS_CODES["CREATED"])
    @purchase_blp.doc(
        summary="Receive stock from purchase order",
        description="""
            Record goods received against a purchase order.
            Creates stock ledger entries and updates PO status.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Receive stock."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("admin_id")
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        po_id = json_data.get("po_id")
        outlet_id = json_data.get("outlet_id")
        received_items = json_data.get("received_items", [])
        receive_note = json_data.get("receive_note")
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "ReceiveStockResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            po_id=po_id,
            outlet_id=outlet_id,
        )
        
        try:
            if not po_id or not outlet_id:
                Log.error(f"{log_tag} Missing required fields")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="po_id and outlet_id are required",
                    errors=["po_id and outlet_id are required"]
                )
            
            Log.info(f"{log_tag} Receiving {len(received_items)} items")
            
            success, grn_id, error = PurchaseService.receive_stock(
                po_id=po_id,
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                received_items=received_items,
                receive_note=receive_note,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            if not success:
                Log.error(f"{log_tag} Receiving failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to receive stock: {error}",
                    errors=[error],
                )
            
            Log.info(f"{log_tag} Stock received successfully, GRN: {grn_id}")
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Stock received successfully",
                data={
                    "po_id": po_id,
                    "grn_id": grn_id
                }
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error receiving stock",
                errors=[str(e)]
            )


@purchase_blp.route("/purchase/purchase-order/cancel")
class CancelPurchaseOrderResource(MethodView):
    """Cancel purchase order."""
    
    @token_required
    @crud_delete_limiter(entity_name="cancel_purchase_order")
    @purchase_blp.arguments(PurchaseOrderIdQuerySchema, location="json")
    @purchase_blp.response(HTTP_STATUS_CODES["OK"])
    @purchase_blp.doc(
        summary="Cancel purchase order",
        description="Cancel a purchase order (only if not received).",
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Cancel purchase order."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        po_id = json_data.get("po_id")
        reason = json_data.get("reason")
        
        log_tag = make_log_tag(
            "admin_purchase_resource.py",
            "CancelPurchaseOrderResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            po_id=po_id,
        )
        
        try:
            if not po_id:
                Log.error(f"{log_tag} po_id is required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="po_id is required"
                )
            
            success, error = PurchaseService.cancel_purchase_order(
                po_id=po_id,
                business_id=business_id,
                reason=reason
            )
            
            if not success:
                Log.error(f"{log_tag} Cancel failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to cancel purchase order: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} PO cancelled successfully")
            
            return prepared_response(
                status=False,
                status_code="OK",
                message="Purchase order cancelled successfully",
                data={"po_id": po_id},
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error cancelling purchase order",
                errors=[str(e)]
            )