# services/inventory_report_service.py
from datetime import datetime
from bson import ObjectId
from app import db
from ....utils.logger import Log
from ..inventory_service import InventoryService
from ....models.product_model import Product


class InventoryReportService:
    """Service for generating inventory reports."""
    
    @staticmethod
    def generate_current_stock_report(business_id, outlet_id, include_zero_stock=False):
        """
        Generate current stock levels report.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            include_zero_stock: Bool - include out of stock items
            
        Returns:
            Dict with current stock data
        """
        log_tag = f"[inventory_report_service.py][InventoryReportService][generate_current_stock_report][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get stock levels from ledger
            stock_levels = InventoryService.get_stock_levels_by_outlet(
                business_id=business_id,
                outlet_id=outlet_id
            )
            
            # Enrich with product details
            stock_items = []
            total_value = 0.0
            out_of_stock = 0
            low_stock = 0
            adequate_stock = 0
            
            for stock_item in stock_levels:
                product_id = stock_item["product_id"]
                current_stock = stock_item["current_stock"]
                
                # Skip zero stock if not requested
                if not include_zero_stock and current_stock <= 0:
                    continue
                
                # Get product details
                product = Product.get_by_id(product_id, business_id)
                
                if not product:
                    continue
                
                # Skip if not tracking inventory
                if product.get("track_inventory") != 1:
                    continue
                
                alert_quantity = product.get("alert_quantity") or 0
                
                # Determine status
                if current_stock <= 0:
                    status = "OUT_OF_STOCK"
                    out_of_stock += 1
                elif alert_quantity > 0 and current_stock <= alert_quantity:
                    status = "LOW_STOCK"
                    low_stock += 1
                else:
                    status = "OK"
                    adequate_stock += 1
                
                # Calculate value (if cost price available)
                stock_value = 0.0
                prices = product.get("prices", {})
                if isinstance(prices, dict) and "cost_price" in prices:
                    cost_price = float(prices.get("cost_price", 0))
                    stock_value = current_stock * cost_price
                    total_value += stock_value
                
                stock_items.append({
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "category": product.get("category"),
                    "brand": product.get("brand"),
                    "current_stock": current_stock,
                    "alert_quantity": alert_quantity,
                    "status": status,
                    "stock_value": round(stock_value, 2)
                })
            
            # Sort by status (out of stock first, then low stock)
            stock_items.sort(key=lambda x: (
                0 if x["status"] == "OUT_OF_STOCK" else 1 if x["status"] == "LOW_STOCK" else 2,
                x["current_stock"]
            ))
            
            summary = {
                "report_date": datetime.utcnow().isoformat(),
                "total_items": len(stock_items),
                "total_quantity": sum(item["current_stock"] for item in stock_items),
                "total_value": round(total_value, 2),
                "out_of_stock": out_of_stock,
                "low_stock": low_stock,
                "adequate_stock": adequate_stock
            }
            
            Log.info(f"{log_tag} Generated report for {len(stock_items)} items")
            
            return {
                "outlet_id": str(outlet_id),
                "stock_items": stock_items,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_stock_movement_report(business_id, outlet_id, start_date, end_date):
        """
        Generate stock movement report by type.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            
        Returns:
            Dict with movement data
        """
        log_tag = f"[inventory_report_service.py][InventoryReportService][generate_stock_movement_report][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            collection = db.get_collection("stock_ledger")
            
            # Aggregate movements by product and type
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "outlet_id": outlet_id,
                        "created_at": {
                            "$gte": start_date,
                            "$lte": end_date
                        }
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "product_id": "$product_id",
                            "reference_type": "$reference_type"
                        },
                        "quantity": {"$sum": "$quantity_delta"}
                    }
                }
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Organize by product
            product_movements = {}
            
            for item in results:
                product_id = str(item["_id"]["product_id"])
                ref_type = item["_id"]["reference_type"]
                quantity = float(item["quantity"])
                
                if product_id not in product_movements:
                    product_movements[product_id] = {
                        "product_id": product_id,
                        "movements": {}
                    }
                
                product_movements[product_id]["movements"][ref_type] = quantity
            
            # Enrich with product details and calculate net
            movements = []
            
            for product_id, data in product_movements.items():
                product = Product.get_by_id(product_id, business_id)
                
                if not product:
                    continue
                
                movements_data = data["movements"]
                
                # Calculate net change
                net_change = sum(movements_data.values())
                
                movements.append({
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "purchases": movements_data.get("PURCHASE", 0.0),
                    "sales": movements_data.get("SALE", 0.0),
                    "returns": movements_data.get("SALE_RETURN", 0.0),
                    "adjustments": movements_data.get("ADJUSTMENT", 0.0),
                    "transfers_in": movements_data.get("TRANSFER_IN", 0.0),
                    "transfers_out": movements_data.get("TRANSFER_OUT", 0.0),
                    "net_change": round(net_change, 2)
                })
            
            # Calculate summary by type
            summary_by_type = {}
            for movement in movements:
                for key in ["purchases", "sales", "returns", "adjustments", "transfers_in", "transfers_out"]:
                    if key not in summary_by_type:
                        summary_by_type[key] = 0.0
                    summary_by_type[key] += movement[key]
            
            Log.info(f"{log_tag} Generated movement report for {len(movements)} products")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "movements": movements,
                "summary_by_type": {k: round(v, 2) for k, v in summary_by_type.items()}
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_stock_valuation_report(business_id, outlet_id):
        """
        Generate stock valuation report.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            
        Returns:
            Dict with valuation data
        """
        log_tag = f"[inventory_report_service.py][InventoryReportService][generate_stock_valuation_report][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get current stock levels
            stock_levels = InventoryService.get_stock_levels_by_outlet(
                business_id=business_id,
                outlet_id=outlet_id
            )
            
            items = []
            total_cost_value = 0.0
            total_retail_value = 0.0
            category_breakdown = {}
            
            for stock_item in stock_levels:
                product_id = stock_item["product_id"]
                current_stock = stock_item["current_stock"]
                
                if current_stock <= 0:
                    continue
                
                # Get product details
                product = Product.get_by_id(product_id, business_id)
                
                if not product:
                    continue
                
                # Get prices
                prices = product.get("prices", {})
                if not isinstance(prices, dict):
                    continue
                
                cost_price = float(prices.get("cost_price", 0))
                selling_price = float(prices.get("selling_price", 0))
                
                if cost_price <= 0:
                    continue
                
                # Calculate values
                cost_value = current_stock * cost_price
                retail_value = current_stock * selling_price
                potential_profit = retail_value - cost_value
                
                total_cost_value += cost_value
                total_retail_value += retail_value
                
                # Category breakdown
                category = product.get("category", "Uncategorized")
                if category not in category_breakdown:
                    category_breakdown[category] = {
                        "cost_value": 0.0,
                        "retail_value": 0.0
                    }
                
                category_breakdown[category]["cost_value"] += cost_value
                category_breakdown[category]["retail_value"] += retail_value
                
                items.append({
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "category": category,
                    "quantity": current_stock,
                    "cost_per_unit": round(cost_price, 2),
                    "retail_per_unit": round(selling_price, 2),
                    "total_cost_value": round(cost_value, 2),
                    "total_retail_value": round(retail_value, 2),
                    "potential_profit": round(potential_profit, 2)
                })
            
            # Format category breakdown
            by_category = []
            for category, values in category_breakdown.items():
                by_category.append({
                    "category": category,
                    "cost_value": round(values["cost_value"], 2),
                    "retail_value": round(values["retail_value"], 2),
                    "percentage_of_total": round((values["cost_value"] / total_cost_value * 100) if total_cost_value > 0 else 0, 2)
                })
            
            by_category.sort(key=lambda x: x["cost_value"], reverse=True)
            
            summary = {
                "valuation_date": datetime.utcnow().isoformat(),
                "total_cost_value": round(total_cost_value, 2),
                "total_retail_value": round(total_retail_value, 2),
                "total_potential_profit": round(total_retail_value - total_cost_value, 2),
                "markup_percentage": round(((total_retail_value - total_cost_value) / total_cost_value * 100) if total_cost_value > 0 else 0, 2)
            }
            
            Log.info(f"{log_tag} Generated valuation report for {len(items)} items")
            
            return {
                "outlet_id": str(outlet_id),
                "items": items,
                "summary": summary,
                "by_category": by_category
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_reorder_report(business_id, outlet_id):
        """
        Generate reorder suggestions report.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            
        Returns:
            Dict with reorder suggestions
        """
        log_tag = f"[inventory_report_service.py][InventoryReportService][generate_reorder_report][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get current stock levels
            stock_levels = InventoryService.get_stock_levels_by_outlet(
                business_id=business_id,
                outlet_id=outlet_id
            )
            
            items_to_reorder = []
            
            for stock_item in stock_levels:
                product_id = stock_item["product_id"]
                current_stock = stock_item["current_stock"]
                
                # Get product details
                product = Product.get_by_id(product_id, business_id)
                
                if not product:
                    continue
                
                # Check if needs reorder
                alert_quantity = product.get("alert_quantity") or 0
                
                if alert_quantity <= 0 or current_stock > alert_quantity:
                    continue
                
                # Determine urgency
                if current_stock <= 0:
                    urgency = "CRITICAL"
                elif current_stock <= alert_quantity * 0.5:
                    urgency = "HIGH"
                else:
                    urgency = "MEDIUM"
                
                # Suggest order quantity (2x alert quantity minus current)
                suggested_quantity = max(alert_quantity * 2 - current_stock, alert_quantity)
                
                items_to_reorder.append({
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "current_stock": current_stock,
                    "alert_quantity": alert_quantity,
                    "suggested_order_quantity": round(suggested_quantity, 2),
                    "urgency": urgency
                })
            
            # Sort by urgency
            urgency_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
            items_to_reorder.sort(key=lambda x: (urgency_order[x["urgency"]], x["current_stock"]))
            
            summary = {
                "total_items": len(items_to_reorder),
                "critical_urgency": sum(1 for item in items_to_reorder if item["urgency"] == "CRITICAL"),
                "high_urgency": sum(1 for item in items_to_reorder if item["urgency"] == "HIGH"),
                "medium_urgency": sum(1 for item in items_to_reorder if item["urgency"] == "MEDIUM")
            }
            
            Log.info(f"{log_tag} Generated reorder report for {len(items_to_reorder)} items")
            
            return {
                "outlet_id": str(outlet_id),
                "items_to_reorder": items_to_reorder,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None