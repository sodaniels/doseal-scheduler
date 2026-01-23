# services/reports/inventory_optimization_service.py
from datetime import datetime, timedelta
from bson import ObjectId
from ....models.product_model import Product
from ....models.admin.sale import Sale
from app import db
from ....utils.logger import Log


class InventoryOptimizationService:
    """Service for generating inventory optimization reports."""
    
    @staticmethod
    def generate_dead_stock_report(business_id, days_threshold=60, outlet_id=None):
        """
        Generate dead stock report (slow-moving/non-moving inventory).
        
        Args:
            business_id: Business ObjectId or string
            days_threshold: Days without sales to consider dead (default 60)
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with dead stock data
        """
        log_tag = f"[inventory_optimization_service.py][InventoryOptimizationService][generate_dead_stock_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            threshold_date = datetime.utcnow() - timedelta(days=days_threshold)
            
            # Get all products
            products_collection = db.get_collection(Product.collection_name)
            sales_collection = db.get_collection(Sale.collection_name)
            
            product_query = {"business_id": business_id}
            if outlet_id:
                product_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            products = list(products_collection.find(product_query))
            
            dead_stock_items = []
            total_dead_stock_value = 0.0
            
            for product in products:
                product_id = product["_id"]
                
                # Find last sale date
                last_sale = sales_collection.find_one(
                    {
                        "business_id": business_id,
                        "cart.lines.product_id": product_id,
                        "status": "Completed"
                    },
                    sort=[("created_at", -1)]
                )
                
                last_sale_date = last_sale.get("created_at") if last_sale else None
                days_since_last_sale = (datetime.utcnow() - last_sale_date).days if last_sale_date else 9999
                
                # Check if dead stock
                if days_since_last_sale >= days_threshold:
                    quantity = float(product.get("quantity", 0))
                    cost_price = float(product.get("cost_price", 0))
                    value = quantity * cost_price
                    total_dead_stock_value += value
                    
                    # Calculate holding cost (estimate 20% annual = 0.055% daily)
                    holding_cost = value * 0.00055 * days_since_last_sale
                    
                    dead_stock_items.append({
                        "product_id": str(product_id),
                        "product_name": product.get("name"),
                        "sku": product.get("sku"),
                        "category": product.get("category"),
                        "quantity_on_hand": quantity,
                        "cost_price": round(cost_price, 2),
                        "total_value": round(value, 2),
                        "last_sale_date": last_sale_date.isoformat() if last_sale_date else None,
                        "days_since_last_sale": days_since_last_sale if days_since_last_sale < 9999 else None,
                        "estimated_holding_cost": round(holding_cost, 2),
                        "status": "Never Sold" if days_since_last_sale >= 9999 else "Dead Stock"
                    })
            
            # Sort by value (highest first)
            dead_stock_items.sort(key=lambda x: x["total_value"], reverse=True)
            
            # Categorize by severity
            critical = [item for item in dead_stock_items if item["days_since_last_sale"] and item["days_since_last_sale"] >= 180]
            warning = [item for item in dead_stock_items if item["days_since_last_sale"] and 90 <= item["days_since_last_sale"] < 180]
            attention = [item for item in dead_stock_items if item["days_since_last_sale"] and days_threshold <= item["days_since_last_sale"] < 90]
            never_sold = [item for item in dead_stock_items if not item["days_since_last_sale"]]
            
            Log.info(f"{log_tag} Generated dead stock report with {len(dead_stock_items)} items")
            
            return {
                "threshold_days": days_threshold,
                "summary": {
                    "total_dead_stock_items": len(dead_stock_items),
                    "total_value_tied_up": round(total_dead_stock_value, 2),
                    "critical_items": len(critical),
                    "warning_items": len(warning),
                    "attention_items": len(attention),
                    "never_sold_items": len(never_sold),
                    "estimated_holding_cost": round(sum(item["estimated_holding_cost"] for item in dead_stock_items), 2)
                },
                "dead_stock_items": dead_stock_items[:100],  # Limit to top 100
                "by_severity": {
                    "critical": critical[:20],
                    "warning": warning[:20],
                    "attention": attention[:20],
                    "never_sold": never_sold[:20]
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_stock_turnover_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate stock turnover report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with stock turnover metrics
        """
        log_tag = f"[inventory_optimization_service.py][InventoryOptimizationService][generate_stock_turnover_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            products_collection = db.get_collection(Product.collection_name)
            sales_collection = db.get_collection(Sale.collection_name)
            
            # Build query
            product_query = {"business_id": business_id}
            sales_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": "Completed"
            }
            
            if outlet_id:
                outlet_obj_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
                product_query["outlet_id"] = outlet_obj_id
                sales_query["outlet_id"] = outlet_obj_id
            
            # Get sales data by product
            sales_pipeline = [
                {"$match": sales_query},
                {"$unwind": "$cart.lines"},
                {
                    "$group": {
                        "_id": "$cart.lines.product_id",
                        "quantity_sold": {"$sum": "$cart.lines.quantity"},
                        "cogs": {"$sum": {"$multiply": ["$cart.lines.quantity", "$cart.lines.cost_price"]}}
                    }
                }
            ]
            
            sales_by_product = {
                str(item["_id"]): {
                    "quantity_sold": float(item["quantity_sold"]),
                    "cogs": float(item["cogs"])
                }
                for item in sales_collection.aggregate(sales_pipeline)
            }
            
            # Get current inventory
            products = list(products_collection.find(product_query))
            
            turnover_items = []
            days_in_period = (end_date - start_date).days or 1
            
            for product in products:
                product_id = str(product["_id"])
                current_quantity = float(product.get("quantity", 0))
                cost_price = float(product.get("cost_price", 0))
                
                sales_data = sales_by_product.get(product_id, {"quantity_sold": 0, "cogs": 0})
                quantity_sold = sales_data["quantity_sold"]
                cogs = sales_data["cogs"]
                
                # Calculate average inventory (simplified: (beginning + ending) / 2)
                # Assuming beginning inventory = current + sold
                beginning_inventory = current_quantity + quantity_sold
                average_inventory = (beginning_inventory + current_quantity) / 2
                average_inventory_value = average_inventory * cost_price
                
                # Calculate turnover ratio
                if average_inventory_value > 0:
                    turnover_ratio = cogs / average_inventory_value
                    # Annualize if period is less than a year
                    annualized_turnover = turnover_ratio * (365 / days_in_period)
                else:
                    turnover_ratio = 0
                    annualized_turnover = 0
                
                # Calculate days inventory outstanding
                dio = 365 / annualized_turnover if annualized_turnover > 0 else 9999
                
                # Classify turnover speed
                if annualized_turnover >= 12:
                    speed = "Fast"
                elif annualized_turnover >= 6:
                    speed = "Medium"
                elif annualized_turnover > 0:
                    speed = "Slow"
                else:
                    speed = "No Movement"
                
                turnover_items.append({
                    "product_id": product_id,
                    "product_name": product.get("name"),
                    "sku": product.get("sku"),
                    "category": product.get("category"),
                    "current_quantity": current_quantity,
                    "quantity_sold": quantity_sold,
                    "average_inventory": round(average_inventory, 2),
                    "cogs": round(cogs, 2),
                    "turnover_ratio": round(turnover_ratio, 2),
                    "annualized_turnover": round(annualized_turnover, 2),
                    "days_inventory_outstanding": round(dio, 0) if dio < 9999 else None,
                    "turnover_speed": speed
                })
            
            # Sort by turnover ratio
            turnover_items.sort(key=lambda x: x["turnover_ratio"], reverse=True)
            
            # Categorize
            fast_movers = [item for item in turnover_items if item["turnover_speed"] == "Fast"]
            medium_movers = [item for item in turnover_items if item["turnover_speed"] == "Medium"]
            slow_movers = [item for item in turnover_items if item["turnover_speed"] == "Slow"]
            no_movement = [item for item in turnover_items if item["turnover_speed"] == "No Movement"]
            
            # Calculate overall metrics
            total_cogs = sum(item["cogs"] for item in turnover_items)
            total_avg_inventory = sum(item["average_inventory"] * float(products_collection.find_one({"_id": ObjectId(item["product_id"])}).get("cost_price", 0)) for item in turnover_items)
            overall_turnover = (total_cogs / total_avg_inventory) if total_avg_inventory > 0 else 0
            
            Log.info(f"{log_tag} Generated stock turnover report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": days_in_period
                },
                "summary": {
                    "overall_turnover_ratio": round(overall_turnover * (365 / days_in_period), 2),
                    "total_products": len(turnover_items),
                    "fast_movers": len(fast_movers),
                    "medium_movers": len(medium_movers),
                    "slow_movers": len(slow_movers),
                    "no_movement": len(no_movement)
                },
                "turnover_items": turnover_items[:100],
                "by_speed": {
                    "fast_movers": fast_movers[:20],
                    "medium_movers": medium_movers[:20],
                    "slow_movers": slow_movers[:20]
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_stockout_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate stockout report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with stockout data
        """
        log_tag = f"[inventory_optimization_service.py][InventoryOptimizationService][generate_stockout_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # This would require a stockout_log collection that tracks when products go out of stock
            # For now, we'll identify currently out-of-stock items and estimate impact
            
            products_collection = db.get_collection(Product.collection_name)
            sales_collection = db.get_collection(Sale.collection_name)
            
            product_query = {
                "business_id": business_id,
                "quantity": {"$lte": 0}
            }
            
            if outlet_id:
                product_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get out-of-stock products
            out_of_stock = list(products_collection.find(product_query))
            
            stockout_items = []
            total_lost_sales = 0.0
            
            for product in out_of_stock:
                product_id = product["_id"]
                
                # Get historical sales to estimate lost sales
                sales_pipeline = [
                    {
                        "$match": {
                            "business_id": business_id,
                            "cart.lines.product_id": product_id,
                            "created_at": {
                                "$gte": start_date - timedelta(days=30),
                                "$lt": start_date
                            },
                            "status": "Completed"
                        }
                    },
                    {"$unwind": "$cart.lines"},
                    {"$match": {"cart.lines.product_id": product_id}},
                    {
                        "$group": {
                            "_id": None,
                            "avg_daily_sales": {"$avg": "$cart.lines.quantity"},
                            "avg_price": {"$avg": "$cart.lines.unit_price"}
                        }
                    }
                ]
                
                historical_sales = list(sales_collection.aggregate(sales_pipeline))
                
                if historical_sales:
                    avg_daily_sales = float(historical_sales[0].get("avg_daily_sales", 0))
                    avg_price = float(historical_sales[0].get("avg_price", 0))
                    
                    # Estimate days out of stock (simplified)
                    days_out = (datetime.utcnow() - product.get("last_stocked_date", datetime.utcnow())).days if product.get("last_stocked_date") else 0
                    
                    estimated_lost_quantity = avg_daily_sales * days_out
                    estimated_lost_revenue = estimated_lost_quantity * avg_price
                    total_lost_sales += estimated_lost_revenue
                    
                    stockout_items.append({
                        "product_id": str(product_id),
                        "product_name": product.get("name"),
                        "sku": product.get("sku"),
                        "category": product.get("category"),
                        "current_quantity": float(product.get("quantity", 0)),
                        "days_out_of_stock": days_out,
                        "average_daily_sales": round(avg_daily_sales, 2),
                        "estimated_lost_quantity": round(estimated_lost_quantity, 2),
                        "estimated_lost_revenue": round(estimated_lost_revenue, 2)
                    })
            
            # Sort by lost revenue
            stockout_items.sort(key=lambda x: x["estimated_lost_revenue"], reverse=True)
            
            # Get frequently stocked-out items (would need historical stockout log)
            frequently_stocked_out = []  # TODO: Implement with stockout_log
            
            Log.info(f"{log_tag} Generated stockout report with {len(stockout_items)} items")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "currently_out_of_stock": len(stockout_items),
                    "estimated_total_lost_revenue": round(total_lost_sales, 2)
                },
                "out_of_stock_items": stockout_items,
                "frequently_stocked_out": frequently_stocked_out
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_abc_analysis_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate ABC analysis report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with ABC classification
        """
        log_tag = f"[inventory_optimization_service.py][InventoryOptimizationService][generate_abc_analysis_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            sales_collection = db.get_collection(Sale.collection_name)
            products_collection = db.get_collection(Product.collection_name)
            
            # Build query
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": "Completed"
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get sales by product
            pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {
                    "$group": {
                        "_id": "$cart.lines.product_id",
                        "revenue": {"$sum": "$cart.lines.line_total"},
                        "quantity_sold": {"$sum": "$cart.lines.quantity"}
                    }
                },
                {"$sort": {"revenue": -1}}
            ]
            
            sales_results = list(sales_collection.aggregate(pipeline))
            
            # Calculate total revenue
            total_revenue = sum(float(item["revenue"]) for item in sales_results)
            
            # Calculate cumulative revenue and classify
            cumulative_revenue = 0.0
            classified_items = []
            
            for item in sales_results:
                product_id = item["_id"]
                revenue = float(item["revenue"])
                cumulative_revenue += revenue
                cumulative_percentage = (cumulative_revenue / total_revenue * 100) if total_revenue > 0 else 0
                
                # ABC Classification
                if cumulative_percentage <= 80:
                    classification = "A"
                elif cumulative_percentage <= 95:
                    classification = "B"
                else:
                    classification = "C"
                
                # Get product details
                product = products_collection.find_one({"_id": product_id})
                
                if product:
                    quantity_on_hand = float(product.get("quantity", 0))
                    cost_price = float(product.get("cost_price", 0))
                    
                    classified_items.append({
                        "product_id": str(product_id),
                        "product_name": product.get("name"),
                        "sku": product.get("sku"),
                        "category": product.get("category"),
                        "classification": classification,
                        "revenue": round(revenue, 2),
                        "revenue_percentage": round((revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                        "cumulative_percentage": round(cumulative_percentage, 2),
                        "quantity_sold": float(item["quantity_sold"]),
                        "quantity_on_hand": quantity_on_hand,
                        "stock_value": round(quantity_on_hand * cost_price, 2)
                    })
            
            # Separate by classification
            a_items = [item for item in classified_items if item["classification"] == "A"]
            b_items = [item for item in classified_items if item["classification"] == "B"]
            c_items = [item for item in classified_items if item["classification"] == "C"]
            
            # Calculate summary
            a_revenue = sum(item["revenue"] for item in a_items)
            b_revenue = sum(item["revenue"] for item in b_items)
            c_revenue = sum(item["revenue"] for item in c_items)
            
            Log.info(f"{log_tag} Generated ABC analysis report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "total_products": len(classified_items),
                    "total_revenue": round(total_revenue, 2),
                    "a_items_count": len(a_items),
                    "a_items_percentage": round((len(a_items) / len(classified_items) * 100) if classified_items else 0, 2),
                    "a_items_revenue": round(a_revenue, 2),
                    "a_items_revenue_percentage": round((a_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "b_items_count": len(b_items),
                    "b_items_percentage": round((len(b_items) / len(classified_items) * 100) if classified_items else 0, 2),
                    "b_items_revenue": round(b_revenue, 2),
                    "b_items_revenue_percentage": round((b_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "c_items_count": len(c_items),
                    "c_items_percentage": round((len(c_items) / len(classified_items) * 100) if classified_items else 0, 2),
                    "c_items_revenue": round(c_revenue, 2),
                    "c_items_revenue_percentage": round((c_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2)
                },
                "classifications": {
                    "a_items": a_items,
                    "b_items": b_items,
                    "c_items": c_items
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None