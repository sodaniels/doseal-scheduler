# services/customer_report_service.py
from datetime import datetime, timedelta
from bson import ObjectId
from ....models.admin.sale import Sale
from app import db
from ....utils.logger import Log
from ....models.admin.customer_model import Customer


class CustomerReportService:
    """Service for generating customer reports and analytics."""
    
    @staticmethod
    def generate_top_customers_report(business_id, start_date, end_date, limit=50):
        """
        Generate top customers by revenue report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            limit: Max number of customers to return
            
        Returns:
            Dict with top customers data
        """
        log_tag = f"[customer_report_service.py][CustomerReportService][generate_top_customers_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Aggregate sales by customer
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "customer_id": {"$exists": True, "$ne": None},
                        "created_at": {
                            "$gte": start_date,
                            "$lte": end_date
                        },
                        "status": "Completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$customer_id",
                        "purchase_count": {"$sum": 1},
                        "total_spent": {"$sum": "$cart.totals.grand_total"},
                        "total_discount": {"$sum": "$cart.totals.total_discount"},
                        "first_purchase": {"$min": "$created_at"},
                        "last_purchase": {"$max": "$created_at"}
                    }
                },
                {
                    "$addFields": {
                        "average_purchase": {
                            "$divide": ["$total_spent", "$purchase_count"]
                        }
                    }
                },
                {"$sort": {"total_spent": -1}},
                {"$limit": limit}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Enrich with customer details
            customers = []
            total_revenue = sum(float(item["total_spent"]) for item in results)
            
            for rank, item in enumerate(results, 1):
                customer_id = str(item["_id"])
                
                # Get customer details
                customer = Customer.get_by_id(customer_id, business_id)
                
                if not customer:
                    continue
                
                total_spent = float(item["total_spent"])
                
                # Calculate customer tenure
                first_purchase = item["first_purchase"]
                last_purchase = item["last_purchase"]
                tenure_days = (datetime.utcnow() - first_purchase).days
                
                # Calculate purchase frequency (purchases per month)
                months = max(tenure_days / 30, 1)
                frequency = float(item["purchase_count"]) / months
                
                customers.append({
                    "rank": rank,
                    "customer_id": customer_id,
                    "customer_name": customer.get("name"),
                    "email": customer.get("email"),
                    "phone": customer.get("phone"),
                    "purchase_count": int(item["purchase_count"]),
                    "total_spent": round(total_spent, 2),
                    "average_purchase": round(float(item["average_purchase"]), 2),
                    "total_discount": round(float(item["total_discount"]), 2),
                    "first_purchase_date": first_purchase.isoformat(),
                    "last_purchase_date": last_purchase.isoformat(),
                    "customer_tenure_days": tenure_days,
                    "purchase_frequency": round(frequency, 2),
                    "contribution_percentage": round((total_spent / total_revenue * 100) if total_revenue > 0 else 0, 2)
                })
            
            # Calculate summary statistics
            top_10_revenue = sum(c["total_spent"] for c in customers[:10])
            top_20_revenue = sum(c["total_spent"] for c in customers[:20])
            
            summary = {
                "total_customers": len(customers),
                "total_revenue": round(total_revenue, 2),
                "top_10_contribution": round((top_10_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                "top_20_contribution": round((top_20_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                "average_customer_value": round(total_revenue / len(customers) if len(customers) > 0 else 0, 2)
            }
            
            Log.info(f"{log_tag} Generated report for {len(customers)} customers")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "customers": customers,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_customer_purchase_history(business_id, customer_id, start_date=None, end_date=None, limit=100):
        """
        Generate detailed purchase history for a specific customer.
        
        Args:
            business_id: Business ObjectId or string
            customer_id: Customer ObjectId or string
            start_date: Optional datetime - period start
            end_date: Optional datetime - period end
            limit: Max number of purchases to return
            
        Returns:
            Dict with customer purchase history
        """
        log_tag = f"[customer_report_service.py][CustomerReportService][generate_customer_purchase_history][{business_id}][{customer_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            customer_id = ObjectId(customer_id) if not isinstance(customer_id, ObjectId) else customer_id
            
            # Get customer details
            customer = Customer.get_by_id(str(customer_id), str(business_id))
            
            if not customer:
                Log.error(f"{log_tag} Customer not found")
                return None
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "customer_id": customer_id,
                "status": {"$ne": "Voided"}
            }
            
            if start_date and end_date:
                match_query["created_at"] = {
                    "$gte": start_date,
                    "$lte": end_date
                }
            
            collection = db.get_collection(Sale.collection_name)
            
            # Get purchases
            purchases = list(collection.find(match_query).sort("created_at", -1).limit(limit))
            
            # Format purchases
            formatted_purchases = []
            total_spent = 0.0
            total_items = 0
            returns = 0
            
            for sale in purchases:
                # Check if return
                is_return = sale.get("status") in ["Refunded", "Partially_Refunded"]
                if is_return:
                    returns += 1
                
                cart = sale.get("cart", {})
                totals = cart.get("totals", {})
                lines = cart.get("lines", [])
                
                amount = float(totals.get("grand_total", 0))
                total_spent += amount
                
                # Extract items
                items = []
                for line in lines:
                    items.append({
                        "product_name": line.get("product_name"),
                        "quantity": float(line.get("quantity", 0)),
                        "unit_price": float(line.get("unit_price", 0)),
                        "line_total": float(line.get("line_total", 0))
                    })
                    total_items += float(line.get("quantity", 0))
                
                formatted_purchases.append({
                    "sale_id": str(sale["_id"]),
                    "date": sale.get("created_at").isoformat() if sale.get("created_at") else None,
                    "outlet_id": str(sale.get("outlet_id")),
                    "items": items,
                    "item_count": len(items),
                    "subtotal": round(float(totals.get("subtotal", 0)), 2),
                    "discount": round(float(totals.get("total_discount", 0)), 2),
                    "tax": round(float(totals.get("total_tax", 0)), 2),
                    "total": round(amount, 2),
                    "payment_method": sale.get("payment_method"),
                    "status": sale.get("status"),
                    "is_return": is_return
                })
            
            # Calculate summary
            purchase_count = len([p for p in formatted_purchases if not p["is_return"]])
            
            summary = {
                "period_purchases": purchase_count,
                "period_spending": round(total_spent, 2),
                "items_purchased": int(total_items),
                "average_items_per_visit": round(total_items / purchase_count if purchase_count > 0 else 0, 2),
                "returns": returns,
                "return_rate": round((returns / len(formatted_purchases) * 100) if len(formatted_purchases) > 0 else 0, 2)
            }
            
            Log.info(f"{log_tag} Generated history with {len(formatted_purchases)} purchases")
            
            first_name = customer.get("first_name")
            last_name = customer.get("last_name")
            
            fullname = f"{first_name} {last_name}"
            return {
                "customer": {
                    "customer_id": str(customer_id),
                    "customer_name": fullname,
                    "email": customer.get("email"),
                    "phone": customer.get("phone")
                },
                "purchases": formatted_purchases,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_customer_segmentation_report(business_id):
        """
        Generate customer segmentation analysis.
        
        Args:
            business_id: Business ObjectId or string
            
        Returns:
            Dict with customer segments
        """
        log_tag = f"[customer_report_service.py][CustomerReportService][generate_customer_segmentation_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Get all customer purchase data
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "customer_id": {"$exists": True, "$ne": None},
                        "status": "Completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$customer_id",
                        "purchase_count": {"$sum": 1},
                        "total_spent": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Define segments
            segments = {
                "VIP": {"min_ltv": 10000, "customers": [], "revenue": 0},
                "Regular": {"min_purchases": 5, "max_ltv": 10000, "customers": [], "revenue": 0},
                "Occasional": {"min_purchases": 2, "max_purchases": 4, "customers": [], "revenue": 0},
                "One-Time": {"max_purchases": 1, "customers": [], "revenue": 0}
            }
            
            total_customers = len(results)
            total_revenue = 0.0
            
            for item in results:
                purchase_count = int(item["purchase_count"])
                total_spent = float(item["total_spent"])
                total_revenue += total_spent
                
                # Categorize
                if total_spent >= 10000:
                    segment = "VIP"
                elif purchase_count >= 5 and total_spent < 10000:
                    segment = "Regular"
                elif 2 <= purchase_count <= 4:
                    segment = "Occasional"
                else:
                    segment = "One-Time"
                
                segments[segment]["customers"].append(item)
                segments[segment]["revenue"] += total_spent
            
            # Format segments
            formatted_segments = []
            
            for segment_name, segment_data in segments.items():
                customer_count = len(segment_data["customers"])
                revenue = segment_data["revenue"]
                
                # Calculate averages
                avg_ltv = revenue / customer_count if customer_count > 0 else 0
                avg_frequency = sum(c["purchase_count"] for c in segment_data["customers"]) / customer_count if customer_count > 0 else 0
                
                formatted_segments.append({
                    "segment": segment_name,
                    "customer_count": customer_count,
                    "percentage": round((customer_count / total_customers * 100) if total_customers > 0 else 0, 2),
                    "total_revenue": round(revenue, 2),
                    "revenue_percentage": round((revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "average_ltv": round(avg_ltv, 2),
                    "average_purchase_frequency": round(avg_frequency, 2)
                })
            
            # Sort by revenue
            formatted_segments.sort(key=lambda x: x["total_revenue"], reverse=True)
            
            Log.info(f"{log_tag} Generated segmentation for {total_customers} customers")
            
            return {
                "segments": formatted_segments,
                "summary": {
                    "total_customers": total_customers,
                    "total_revenue": round(total_revenue, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_customer_retention_report(business_id):
        """
        Generate customer retention and churn analysis.
        
        Args:
            business_id: Business ObjectId or string
            
        Returns:
            Dict with retention metrics
        """
        log_tag = f"[customer_report_service.py][CustomerReportService][generate_customer_retention_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Get customer last purchase dates
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "customer_id": {"$exists": True, "$ne": None},
                        "status": "Completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$customer_id",
                        "last_purchase": {"$max": "$created_at"},
                        "purchase_count": {"$sum": 1},
                        "total_spent": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Define thresholds (days)
            active_threshold = 30
            at_risk_threshold = 60
            churned_threshold = 90
            
            now = datetime.utcnow()
            
            active_customers = []
            at_risk_customers = []
            churned_customers = []
            
            for item in results:
                last_purchase = item["last_purchase"]
                days_since = (now - last_purchase).days
                
                customer_data = {
                    "customer_id": str(item["_id"]),
                    "days_since_last_purchase": days_since,
                    "purchase_count": int(item["purchase_count"]),
                    "total_spent": round(float(item["total_spent"]), 2)
                }
                
                if days_since <= active_threshold:
                    active_customers.append(customer_data)
                elif days_since <= at_risk_threshold:
                    at_risk_customers.append(customer_data)
                    customer_data["risk_level"] = "MEDIUM"
                elif days_since <= churned_threshold:
                    at_risk_customers.append(customer_data)
                    customer_data["risk_level"] = "HIGH"
                else:
                    churned_customers.append(customer_data)
            
            total_customers = len(results)
            
            # Calculate retention rate
            retention_rate = (len(active_customers) / total_customers * 100) if total_customers > 0 else 0
            churn_rate = (len(churned_customers) / total_customers * 100) if total_customers > 0 else 0
            
            # Sort at-risk by days since last purchase
            at_risk_customers.sort(key=lambda x: x["days_since_last_purchase"], reverse=True)
            
            Log.info(f"{log_tag} Generated retention report")
            
            return {
                "current_metrics": {
                    "total_customers": total_customers,
                    "active_customers": len(active_customers),
                    "at_risk_customers": len(at_risk_customers),
                    "churned_customers": len(churned_customers),
                    "retention_rate": round(retention_rate, 2),
                    "churn_rate": round(churn_rate, 2)
                },
                "at_risk_customers": at_risk_customers[:50]  # Top 50
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_new_vs_returning_report(business_id, start_date, end_date):
        """
        Generate new vs returning customers analysis.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            
        Returns:
            Dict with new vs returning metrics
        """
        log_tag = f"[customer_report_service.py][CustomerReportService][generate_new_vs_returning_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Get all sales in period with customer
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "customer_id": {"$exists": True, "$ne": None},
                        "created_at": {
                            "$gte": start_date,
                            "$lte": end_date
                        },
                        "status": "Completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$customer_id",
                        "purchases_in_period": {"$sum": 1},
                        "revenue_in_period": {"$sum": "$cart.totals.grand_total"},
                        "first_purchase_in_period": {"$min": "$created_at"}
                    }
                }
            ]
            
            period_results = list(collection.aggregate(pipeline))
            
            # For each customer, check if they had purchases before period
            new_customers = []
            returning_customers = []
            
            for item in period_results:
                customer_id = item["_id"]
                
                # Check for purchases before period
                prior_purchases = collection.count_documents({
                    "business_id": business_id,
                    "customer_id": customer_id,
                    "created_at": {"$lt": start_date},
                    "status": "Completed"
                })
                
                customer_data = {
                    "customer_id": str(customer_id),
                    "purchases": int(item["purchases_in_period"]),
                    "revenue": round(float(item["revenue_in_period"]), 2)
                }
                
                if prior_purchases == 0:
                    new_customers.append(customer_data)
                else:
                    returning_customers.append(customer_data)
            
            # Calculate totals
            new_revenue = sum(c["revenue"] for c in new_customers)
            returning_revenue = sum(c["revenue"] for c in returning_customers)
            total_revenue = new_revenue + returning_revenue
            
            Log.info(f"{log_tag} Generated new vs returning report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "new_customers": {
                    "count": len(new_customers),
                    "revenue": round(new_revenue, 2),
                    "percentage_of_revenue": round((new_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "average_revenue": round(new_revenue / len(new_customers) if len(new_customers) > 0 else 0, 2)
                },
                "returning_customers": {
                    "count": len(returning_customers),
                    "revenue": round(returning_revenue, 2),
                    "percentage_of_revenue": round((returning_revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "average_revenue": round(returning_revenue / len(returning_customers) if len(returning_customers) > 0 else 0, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None