# resources/stock_resource.py
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from ....extensions.db import db
from pymongo.errors import PyMongoError
from bson import ObjectId

from ....utils.json_response import prepared_response
from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter,
    crud_delete_limiter,
    sale_refund_limiter,
)
from .admin_business_resource import token_required
from ....utils.helpers import make_log_tag
from ....utils.crypt import decrypt_data
from ....utils.json_response import prepared_response
from ....constants.service_code import HTTP_STATUS_CODES
from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS
)
from ....utils.logger import Log

from ....schemas.admin.stock_schemas import (
    StockHistoryQuerySchema,
    StockLevelsQuerySchema,
    StockDetailQuerySchema,
    StockSummaryQuerySchema
)
from ....schemas.admin.pos_schemas import (
    CheckoutRequestSchema,
    CheckoutQuerySchema,
    StockQuerySchema,
    StockAdjustmentSchema,
    StockTransferSchema
)

from ....models.admin.stock_ledger import StockLedger
from ....models.product_model import Product
from ....services.pos.inventory_service import InventoryService


stock_blp = Blueprint("stock", __name__, description="Stock information and history operations")


@stock_blp.route("/stock/history")
class StockHistoryResource(MethodView):
    """Get detailed stock movement history for a product."""
    
    @token_required
    @crud_read_limiter("stock_history")
    @stock_blp.arguments(StockHistoryQuerySchema, location="query")
    @stock_blp.response(HTTP_STATUS_CODES["OK"])
    @stock_blp.doc(
        summary="Get stock movement history",
        description="""
            Get detailed movement history for a specific product at an outlet.
            Shows all stock increases and decreases with reasons and timestamps.
            
            Returns ledger entries showing:
            - Opening stock
            - Purchases
            - Sales
            - Returns
            - Adjustments
            - Transfers
            - Damages
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle GET request for stock history."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        product_id = query_args.get("product_id")
        composite_variant_id = query_args.get("composite_variant_id")
        limit = query_args.get("limit", 100)
        
        log_tag = (
            f"[stock_resource.py][StockHistoryResource][get]"
            f"[{client_ip}][{target_business_id}][{product_id}]"
        )
        
        try:
            # Validate required fields
            if not outlet_id or not product_id:
                Log.error(f"{log_tag} Missing required fields")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="outlet_id and product_id are required"
                )
            
            # Get product details
            product = Product.get_by_id(product_id, target_business_id)
            if not product:
                Log.error(f"{log_tag} Product not found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Product not found"
                )
            
            # Get current stock level
            current_stock = InventoryService.get_available_stock(
                business_id=target_business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id
            )
            
            # Get stock history
            history = StockLedger.get_stock_history(
                business_id=target_business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id,
                limit=limit
            )
            
            # Calculate running balance for each entry
            running_balance = current_stock
            for entry in history:
                entry["balance_after"] = running_balance
                running_balance -= entry["quantity_delta"]
                entry["balance_before"] = running_balance
            
            Log.info(f"{log_tag} Retrieved {len(history)} history entries")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock history retrieved successfully",
                data={
                    "product": {
                        "product_id": product_id,
                        "product_name": product.get("name"),
                        "sku": product.get("sku"),
                        "track_inventory": product.get("track_inventory")
                    },
                    "current_stock": current_stock,
                    "history": history,
                    "total_entries": len(history)
                }
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving stock history",
                errors=[str(e)],
            )


@stock_blp.route("/stock/levels")
class StockLevelsResource(MethodView):
    """Get current stock levels for all products at an outlet."""
    
    @token_required
    @crud_read_limiter("stock_levels")
    @stock_blp.arguments(StockLevelsQuerySchema, location="query")
    @stock_blp.response(HTTP_STATUS_CODES["OK"])
    @stock_blp.doc(
        summary="Get current stock levels for all products",
        description="""
            Get current stock levels for all products at a specific outlet.
            
            Optionally filter to show only:
            - Low stock items (below alert_quantity)
            - Out of stock items (quantity = 0)
            - All items (default)
            
            Useful for:
            - Dashboard displays
            - Reorder reports
            - Inventory counts
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle GET request for stock levels."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        filter_type = query_args.get("filter", "all")  # all, low_stock, out_of_stock
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)
        
        log_tag = make_log_tag(
            "stock_resource.py",
            "StockLevelsResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )
        
        try:
            if not outlet_id:
                Log.error(f"{log_tag} outlet_id is required")
                return prepared_response(
                    status=False,
                    code_status="BAD_REQUEST",
                    message="outlet_id is required"
                )
            
            # Get all stock levels from ledger
            stock_levels = InventoryService.get_stock_levels_by_outlet(
                business_id=target_business_id,
                outlet_id=outlet_id
            )
            
            # Enrich with product details
            enriched_stock = []
            for stock_item in stock_levels:
                product_id = stock_item["product_id"]
                product = Product.get_by_id(product_id, target_business_id)
                
                if not product:
                    continue
                
                # Skip if product doesn't track inventory
                if product.get("track_inventory") != 1:
                    continue
                
                current_stock = stock_item["current_stock"] if stock_item["current_stock"] else 0
                alert_quantity = product.get("alert_quantity") if product.get("alert_quantity") else 0
        
                
                stock_info = {
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "category": product.get("category"),
                    "brand": product.get("brand"),
                    "unit": product.get("unit"),
                    "composite_variant_id": stock_item.get("composite_variant_id"),
                    "current_stock": current_stock,
                    "alert_quantity": alert_quantity,
                    "status": "OK"
                }
                
                # Determine status
                if current_stock <= 0:
                    stock_info["status"] = "OUT_OF_STOCK"
                elif alert_quantity > 0 and current_stock <= alert_quantity:
                    stock_info["status"] = "LOW_STOCK"
                
                # Apply filter
                if filter_type == "low_stock" and stock_info["status"] != "LOW_STOCK":
                    continue
                elif filter_type == "out_of_stock" and stock_info["status"] != "OUT_OF_STOCK":
                    continue
                
                enriched_stock.append(stock_info)
            
            # Sort by stock level (lowest first)
            enriched_stock.sort(key=lambda x: x["current_stock"])
            
            # Pagination
            total_count = len(enriched_stock)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_stock = enriched_stock[start_idx:end_idx]
            
            # Calculate summary stats
            out_of_stock_count = sum(1 for item in enriched_stock if item["status"] == "OUT_OF_STOCK")
            low_stock_count = sum(1 for item in enriched_stock if item["status"] == "LOW_STOCK")
            ok_count = sum(1 for item in enriched_stock if item["status"] == "OK")
            
            Log.info(f"{log_tag} Retrieved {len(paginated_stock)} stock items")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock levels retrieved successfully",
                data={
                    "stock_items": paginated_stock,
                    "total_count": total_count,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": (total_count + per_page - 1) // per_page,
                    "summary": {
                        "out_of_stock": out_of_stock_count,
                        "low_stock": low_stock_count,
                        "ok": ok_count
                    }
                }
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving stock levels",
                errors=[str(e)]
            )


@stock_blp.route("/stock/detail")
class StockDetailResource(MethodView):
    """Get comprehensive stock information for a specific product."""
    
    @token_required
    @crud_read_limiter("stock_detail")
    @stock_blp.arguments(StockDetailQuerySchema, location="query")
    @stock_blp.response(HTTP_STATUS_CODES["OK"])
    @stock_blp.doc(
        summary="Get detailed stock information for a product",
        description="""
            Get comprehensive stock information including:
            - Current stock level at specified outlet
            - Product details
            - Alert status
            - Recent movements (last 10)
            - Stock across all outlets (optional)
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle GET request for detailed stock info."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = user_info.get("_id")
        
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id
        
        product_id = query_args.get("product_id")
        outlet_id = query_args.get("outlet_id")
        composite_variant_id = query_args.get("composite_variant_id")
        include_all_outlets = query_args.get("include_all_outlets", False)
        
        log_tag = make_log_tag(
            "stock_resource.py",
            "StockDetailResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )
        
        try:
            if not product_id:
                Log.error(f"{log_tag} product_id is required")
                return prepared_response(
                    status=False,
                    code_status="BAD_REQUEST",
                    message="product_id is required"
                )
            
            # Get product details
            product = Product.get_by_id(product_id, target_business_id)
            if not product:
                Log.error(f"{log_tag} Product not found")
                return prepared_response(
                    status=False,
                    code_status="NOT_FOUND",
                    message="Product not found"
                )
            
            # Get stock at specified outlet
            current_stock = None
            recent_movements = []
            if outlet_id:
                current_stock = InventoryService.get_available_stock(
                    business_id=target_business_id,
                    outlet_id=outlet_id,
                    product_id=product_id,
                    composite_variant_id=composite_variant_id
                )
                
                # Get recent movements (last 10)
                recent_movements = StockLedger.get_stock_history(
                    business_id=target_business_id,
                    outlet_id=outlet_id,
                    product_id=product_id,
                    composite_variant_id=composite_variant_id,
                    limit=10
                )
            
            # Get stock across all outlets if requested
            all_outlets_stock = []
            total_stock = 0.0
            if include_all_outlets:
                collection = db.get_collection("stock_ledger")
                
                pipeline = [
                    {"$match": {
                        "business_id": ObjectId(target_business_id),
                        "product_id": ObjectId(product_id)
                    }},
                    {"$group": {
                        "_id": "$outlet_id",
                        "total_quantity": {"$sum": "$quantity_delta"}
                    }}
                ]
                
                if composite_variant_id:
                    pipeline[0]["$match"]["composite_variant_id"] = ObjectId(composite_variant_id)
                
                results = list(collection.aggregate(pipeline))
                
                for result in results:
                    outlet_stock = float(result["total_quantity"])
                    all_outlets_stock.append({
                        "outlet_id": str(result["_id"]),
                        "stock": outlet_stock
                    })
                    total_stock += outlet_stock
            
            # Determine alert status
            alert_quantity = product.get("alert_quantity", 0)
            alert_status = "OK"
            if current_stock is not None:
                if current_stock <= 0:
                    alert_status = "OUT_OF_STOCK"
                elif alert_quantity > 0 and current_stock <= alert_quantity:
                    alert_status = "LOW_STOCK"
            
            Log.info(f"{log_tag} Stock detail retrieved successfully")
            
            response_data = {
                "product": {
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "product_type": product.get("product_type"),
                    "category": product.get("category"),
                    "brand": product.get("brand"),
                    "track_inventory": product.get("track_inventory"),
                    "alert_quantity": alert_quantity,
                    "status": product.get("status")
                },
                "current_outlet": {
                    "outlet_id": outlet_id,
                    "current_stock": current_stock,
                    "alert_status": alert_status
                } if outlet_id else None,
                "recent_movements": recent_movements
            }
            
            if include_all_outlets:
                response_data["all_outlets"] = {
                    "outlets": all_outlets_stock,
                    "total_stock": total_stock
                }
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock detail retrieved successfully",
                data=response_data
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving stock detail",
                errors=[str(e)]
            )


@stock_blp.route("/stock/summary")
class StockSummaryResource(MethodView):
    """Get stock summary/analytics for business or outlet."""
    
    @token_required
    @crud_read_limiter("stock_summary")
    @stock_blp.arguments(StockSummaryQuerySchema, location="query")
    @stock_blp.response(HTTP_STATUS_CODES["OK"])
    @stock_blp.doc(
        summary="Get stock summary and analytics",
        description="""
            Get aggregated stock metrics including:
            - Total products tracked
            - Out of stock count
            - Low stock count
            - Total inventory value (if cost prices available)
            - Top 10 low stock items
            
            Can be filtered by outlet or show business-wide summary.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Handle GET request for stock summary."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = user_info.get("_id")
        
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        
        log_tag = make_log_tag(
            "stock_resource.py",
            "StockSummaryResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )
        
        try:
            # Get all products that track inventory
            products_result = Product.get_by_business_id(
                business_id=target_business_id,
                page=None,
                per_page=None
            )
            
            tracked_products = [
                p for p in products_result.get("products", [])
                if p.get("track_inventory") == 1
            ]
            
            # Calculate stock metrics
            out_of_stock = []
            low_stock = []
            ok_stock = []
            total_value = 0.0
            
            for product in tracked_products:
                product_id = product["_id"]
                
                # Get stock level
                if outlet_id:
                    stock = InventoryService.get_available_stock(
                        business_id=target_business_id,
                        outlet_id=outlet_id,
                        product_id=product_id
                    )
                else:
                    # Get total stock across all outlets
                    collection = db.get_collection("stock_ledger")
                    pipeline = [
                        {"$match": {
                            "business_id": ObjectId(target_business_id),
                            "product_id": ObjectId(product_id)
                        }},
                        {"$group": {
                            "_id": None,
                            "total": {"$sum": "$quantity_delta"}
                        }}
                    ]
                    result = list(collection.aggregate(pipeline))
                    stock = float(result[0]["total"]) if result else 0.0
                
                alert_qty = product.get("alert_quantity") if product.get("alert_quantity") else 0
                
                stock_info = {
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "current_stock": stock,
                    "alert_quantity": alert_qty
                }
                
                # Calculate value if cost price available
                prices = product.get("prices", {})
                if isinstance(prices, dict) and "cost_price" in prices:
                    cost_price = float(prices.get("cost_price", 0))
                    stock_info["stock_value"] = stock * cost_price
                    total_value += stock_info["stock_value"]
                
                # Categorize
                if stock <= 0:
                    out_of_stock.append(stock_info)
                elif alert_qty > 0 and stock <= alert_qty:
                    low_stock.append(stock_info)
                else:
                    ok_stock.append(stock_info)
            
            # Sort low stock by current stock (ascending)
            low_stock.sort(key=lambda x: x["current_stock"])
            
            Log.info(f"{log_tag} Summary retrieved: {len(tracked_products)} products")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock summary retrieved successfully",
                data={
                    "summary": {
                        "total_products_tracked": len(tracked_products),
                        "out_of_stock_count": len(out_of_stock),
                        "low_stock_count": len(low_stock),
                        "ok_stock_count": len(ok_stock),
                        "total_inventory_value": round(total_value, 2)
                    },
                    "out_of_stock_items": out_of_stock[:10],  # Top 10
                    "low_stock_items": low_stock[:10],  # Top 10 lowest
                    "outlet_id": outlet_id if outlet_id else "all_outlets"
                }
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving stock summary",
                errors=[str(e)]
            )


@stock_blp.route("/stock/transfer")
class StockTransferResource(MethodView):
    """
    Handle stock transfers between outlets.
    Creates two StockLedger entries:
        - TRANSFER_OUT from source outlet
        - TRANSFER_IN to destination outlet
    """
    @token_required
    @crud_write_limiter("stock_transfer")
    @stock_blp.arguments(StockTransferSchema, location="json")
    @stock_blp.response(HTTP_STATUS_CODES["CREATED"], description="Stock transferred")
    @stock_blp.doc(
        summary="Transfer stock between outlets (role-aware)",
        description="""
            Transfer stock of a product (and optional composite variant) from one outlet to another.

            • SYSTEM_OWNER / SUPER_ADMIN:
                - may submit `business_id` in the payload to target any business
                - if omitted, defaults to their own `business_id`

            • Other roles:
                - `business_id` is always forced to the authenticated user's `business_id`.

            Flow:
                1. Validate that source outlet has sufficient stock.
                2. Create a TRANSFER_OUT ledger entry at source outlet.
                3. Create a TRANSFER_IN ledger entry at destination outlet.

            This endpoint does NOT directly modify any `product` document stock fields;
            all stock is derived from the `stock_ledger`.
        """,
        security=[{"Bearer": []}],
        responses={
            201: {
                "description": "Stock transferred successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 201,
                            "message": "Stock transferred successfully.",
                            "data": {
                                "from_outlet_id": "60a6b938d4d8c24fa0804d62",
                                "to_outlet_id": "60a6b938d4d8c24fa0804d63",
                                "product_id": "67b2fdcc440676485b1b4d89",
                                "composite_variant_id": None,
                                "quantity": 5,
                                "out_ledger_id": "67b2fe2e440676485b1b4d90",
                                "in_ledger_id": "67b2fe2e440676485b1b4d91",
                            },
                        }
                    }
                },
            },
            400: {
                "description": "Bad request / invalid input",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Source and destination outlets must be different.",
                        }
                    }
                },
            },
            409: {
                "description": "Insufficient stock at source outlet",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 409,
                            "message": "Insufficient stock for transfer.",
                            "data": {
                                "items": [
                                    {
                                        "product_id": "67b2fdcc440676485b1b4d89",
                                        "composite_variant_id": None,
                                        "required": 10,
                                        "available": 3,
                                        "shortfall": 7,
                                    }
                                ]
                            },
                        }
                    }
                },
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred while processing the stock transfer.",
                            "error": "Detailed error message here",
                        }
                    }
                },
            },
        },
    )
    def post(self, json_data):
        """
        Handle the POST request to transfer stock between outlets.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("_id")

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        # Normalise payload
        json_data["business_id"] = target_business_id
        if not json_data.get("user_id"):
            json_data["user_id"] = user_info.get("user_id")
        json_data["user__id"] = auth_user__id

        log_tag = make_log_tag(
            "admin_stock_resource.py",
            "StockTransferResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        from_outlet_id = json_data.get("from_outlet_id")
        to_outlet_id = json_data.get("to_outlet_id")
        product_id = json_data.get("product_id")
        composite_variant_id = json_data.get("composite_variant_id")
        quantity = json_data.get("quantity")
        note = json_data.get("note")

        # Basic validations
        if not from_outlet_id or not to_outlet_id:
            Log.info(f"{log_tag} from_outlet_id or to_outlet_id not provided")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "Both from_outlet_id and to_outlet_id must be provided.",
            )

        if from_outlet_id == to_outlet_id:
            Log.info(f"{log_tag} source and destination outlets are the same")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "Source and destination outlets must be different.",
            )

        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            Log.info(f"{log_tag} invalid quantity: {quantity}")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "quantity must be a valid number.",
            )

        if quantity <= 0:
            Log.info(f"{log_tag} non-positive quantity: {quantity}")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "quantity must be greater than zero.",
            )

        # --------------------------------------------
        # 1) Validate stock at source outlet
        # --------------------------------------------
        try:
            is_ok, insufficient_items = InventoryService.validate_stock_availability(
                business_id=target_business_id,
                outlet_id=from_outlet_id,
                items=[
                    {
                        "product_id": product_id,
                        "composite_variant_id": composite_variant_id,
                        "quantity": quantity,
                    }
                ],
            )
        except Exception as e:
            Log.error(f"{log_tag} error validating stock availability: {str(e)}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while validating stock availability.",
                errors=str(e),
            )

        if not is_ok:
            Log.error(f"{log_tag} insufficient stock: {insufficient_items}")
            return prepared_response(
                False,
                "BAD_REQUEST",
                "Insufficient stock for transfer.",
                data={"items": insufficient_items},
            )

        # --------------------------------------------
        # 2) Perform transfer (two ledger entries)
        # --------------------------------------------

        # Reference type constants from StockLedger
        REF_OUT = StockLedger.REF_TYPE_TRANSFER_OUT
        REF_IN = StockLedger.REF_TYPE_TRANSFER_IN

        try:
            # 2.1 Decrease stock at source (TRANSFER_OUT)
            out_ledger_id = InventoryService.decrease_stock(
                business_id=target_business_id,
                outlet_id=from_outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id,
                quantity=quantity,
                reference_type=REF_OUT,
                reference_id=None,
                user_id=json_data["user_id"],
                user__id=json_data["user__id"],
                note=note,
                unit_cost=None,
                agent_id=agent_id,
                admin_id=admin_id,
            )

            if not out_ledger_id:
                Log.error(f"{log_tag} failed to create TRANSFER_OUT ledger entry")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to record stock decrease (TRANSFER_OUT).",
                )

            # 2.2 Increase stock at destination (TRANSFER_IN)
            in_ledger_id = InventoryService.increase_stock(
                business_id=target_business_id,
                outlet_id=to_outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id,
                quantity=quantity,
                reference_type=REF_IN,
                reference_id=None,
                user_id=json_data["user_id"],
                user__id=json_data["user__id"],
                note=note,
                unit_cost=None,
                agent_id=agent_id,
                admin_id=admin_id,
            )

            if not in_ledger_id:
                Log.error(f"{log_tag} failed to create TRANSFER_IN ledger entry")
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to record stock increase (TRANSFER_IN). "
                    "Please review stock ledger for inconsistencies.",
                )

            Log.info(
                f"{log_tag} stock transfer completed: "
                f"{quantity} units of product {product_id} "
                f"from outlet {from_outlet_id} to {to_outlet_id} "
                f"(out_ledger={out_ledger_id}, in_ledger={in_ledger_id})"
            )

            return prepared_response(
                True,
                "CREATED",
                "Stock transferred successfully.",
                data={
                    "from_outlet_id": from_outlet_id,
                    "to_outlet_id": to_outlet_id,
                    "product_id": product_id,
                    "composite_variant_id": composite_variant_id,
                    "quantity": quantity,
                    "out_ledger_id": out_ledger_id,
                    "in_ledger_id": in_ledger_id,
                }
            )

        except PyMongoError as e:
            Log.error(f"{log_tag} PyMongoError during stock transfer: {str(e)}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected database error occurred while processing the stock transfer.",
                errors=str(e),
            )

        except Exception as e:
            Log.error(f"{log_tag} unexpected error during stock transfer: {str(e)}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred while processing the stock transfer.",
                errors=str(e),
            )

@stock_blp.route("/stock/check")
class StockCheckResource(MethodView):
    """Check available stock for a product/variant."""
    
    @token_required
    @crud_read_limiter("stockcheck")
    @stock_blp.arguments(StockQuerySchema, location="query")
    @stock_blp.response(HTTP_STATUS_CODES["OK"], description="Stock level retrieved")
    def get(self, query_args):
        """Get available stock quantity."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        account_type = user_info.get("account_type") if user_info.get("account_type") else None
        token_business_id = str(user_info.get("business_id"))
        user_id = str(user_info.get("user_id"))
        user__id = str(user_info.get("_id"))

        # Determine business_id (role-aware)
        requested_business_id = query_args.get("business_id")
        if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]:
            business_id = requested_business_id or token_business_id
        else:
            business_id = token_business_id

        log_tag = make_log_tag(
            "pos_resource.py",
            "StockCheckResource",
            "get",
            client_ip,
            user_id,
            account_type,
            token_business_id,
            business_id
        )

        # Basic business_id validation
        if not business_id:
            Log.error(f"{log_tag} BUSINESS_ID_REQUIRED")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="Business ID is required",
                errors=["business_id is required"],
            )

        try:
            outlet_id = query_args.get("outlet_id")
            product_id = query_args.get("product_id")
            composite_variant_id = query_args.get("composite_variant_id")

            Log.info(
                f"{log_tag} Stock check request | "
                f"outlet_id:{outlet_id} | product_id:{product_id} | composite_variant_id:{composite_variant_id}"
            )

            # Minimal validation: outlet_id and at least one of product/composite
            if not outlet_id:
                Log.error(f"{log_tag} OUTLET_ID_REQUIRED")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Outlet ID is required",
                    errors=["outlet_id is required"],
                )

            if not product_id and not composite_variant_id:
                Log.error(f"{log_tag} PRODUCT_OR_VARIANT_REQUIRED")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Either product_id or composite_variant_id is required",
                    errors=["product_id or composite_variant_id is required"],
                )

            available_stock = InventoryService.get_available_stock(
                business_id=business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id
            )

            Log.info(f"{log_tag} STOCK_RETRIEVED available_stock={available_stock}")

            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock level retrieved successfully",
                data={
                    "product_id": product_id,
                    "composite_variant_id": composite_variant_id,
                    "outlet_id": outlet_id,
                    "available_stock": available_stock,
                },
            )

        except Exception as e:
            Log.error(f"{log_tag} STOCK_CHECK_ERROR {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error checking stock",
                errors=[str(e)],
            )


@stock_blp.route("/stock/adjust")
class StockAdjustmentResource(MethodView):
    """Manual stock adjustments (opening stock, damages, etc.)."""
    
    @token_required
    @crud_write_limiter("stock_adjustment")
    @stock_blp.arguments(StockAdjustmentSchema, location="json")
    @stock_blp.response(HTTP_STATUS_CODES["CREATED"], description="Stock adjusted")
    def post(self, json_data):
        """Create manual stock adjustment."""
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {})
        
        account_type = user_info.get("account_type")
        token_business_id = user_info.get("business_id")
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("admin_id")
        business_id = None
        
        # Determine business_id (role-aware)
        requested_business_id = json_data.get("business_id")
        
        if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]:
            business_id = requested_business_id or token_business_id
        else:
            business_id = token_business_id
        
        log_tag = f"[pos_resource.py][StockAdjustmentResource][post][{client_ip}][{business_id}]"
        
        try:
            outlet_id = json_data.get("outlet_id")
            product_id = json_data.get("product_id")
            composite_variant_id = json_data.get("composite_variant_id")
            quantity = json_data.get("quantity")
            adjustment_type = json_data.get("adjustment_type")
            note = json_data.get("note")
            
            # Determine if increase or decrease
            if quantity > 0:
                ledger_id = InventoryService.increase_stock(
                    business_id=str(business_id),
                    outlet_id=outlet_id,
                    product_id=product_id,
                    quantity=abs(quantity),
                    reference_type=adjustment_type,
                    user_id=user_id,
                    user__id=user__id,
                    composite_variant_id=composite_variant_id,
                    note=note,
                    agent_id=agent_id,
                    admin_id=admin_id
                )
            else:
                ledger_id = InventoryService.decrease_stock(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    product_id=product_id,
                    quantity=abs(quantity),
                    reference_type=adjustment_type,
                    user_id=user_id,
                    user__id=user__id,
                    composite_variant_id=composite_variant_id,
                    note=note,
                    agent_id=agent_id,
                    admin_id=admin_id
                )
            
            if not ledger_id:
                Log.error(f"{log_tag} Stock adjustment failed")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Stock adjustment failed",
                    errors=["Failed to create ledger entry"]
                )
            
            Log.info(f"{log_tag} Stock adjusted: {ledger_id}")
            
            # Get new stock level
            new_stock = InventoryService.get_available_stock(
                business_id=business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                composite_variant_id=composite_variant_id
            )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock adjusted successfully",
                data={
                    "ledger_id": ledger_id,
                    "new_stock_level": new_stock
                },
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error adjusting stock",
                errors=[str(e)]
            )



































