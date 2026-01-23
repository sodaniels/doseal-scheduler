# services/reports/performance_analytics_service.py
from datetime import datetime, timedelta
from bson import ObjectId
from ....models.admin.sale import Sale
from ....models.product_model import Product
from app import db
from ....utils.logger import Log
from collections import defaultdict
from itertools import combinations


class PerformanceAnalyticsService:
    """Service for generating performance and analytics reports."""
    
    @staticmethod
    def generate_outlet_performance_report(business_id, start_date, end_date):
        """
        Generate outlet performance comparison report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            
        Returns:
            Dict with outlet performance data
        """
        log_tag = f"[performance_analytics_service.py][PerformanceAnalyticsService][generate_outlet_performance_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Aggregate by outlet
            pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "created_at": {
                            "$gte": start_date,
                            "$lte": end_date
                        },
                        "status": "Completed"
                    }
                },
                {
                    "$group": {
                        "_id": "$outlet_id",
                        "transaction_count": {"$sum": 1},
                        "total_revenue": {"$sum": "$cart.totals.grand_total"},
                        "total_discount": {"$sum": "$cart.totals.total_discount"},
                        "total_tax": {"$sum": "$cart.totals.total_tax"},
                        "items_sold": {"$sum": {"$size": "$cart.lines"}}
                    }
                },
                {"$sort": {"total_revenue": -1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Calculate totals
            total_revenue = sum(float(r["total_revenue"]) for r in results)
            total_transactions = sum(r["transaction_count"] for r in results)
            
            # Format outlet data
            outlets = []
            for rank, item in enumerate(results, 1):
                revenue = float(item["total_revenue"])
                transactions = int(item["transaction_count"])
                
                outlets.append({
                    "rank": rank,
                    "outlet_id": str(item["_id"]),
                    "transaction_count": transactions,
                    "total_revenue": round(revenue, 2),
                    "average_transaction_value": round(revenue / transactions if transactions > 0 else 0, 2),
                    "total_discount": round(float(item["total_discount"]), 2),
                    "total_tax": round(float(item["total_tax"]), 2),
                    "items_sold": int(item["items_sold"]),
                    "items_per_transaction": round(item["items_sold"] / transactions if transactions > 0 else 0, 2),
                    "revenue_percentage": round((revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "transaction_percentage": round((transactions / total_transactions * 100) if total_transactions > 0 else 0, 2)
                })
            
            Log.info(f"{log_tag} Generated outlet performance report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "outlets": outlets,
                "summary": {
                    "total_outlets": len(outlets),
                    "total_revenue": round(total_revenue, 2),
                    "total_transactions": total_transactions,
                    "average_revenue_per_outlet": round(total_revenue / len(outlets) if outlets else 0, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_time_based_analysis(business_id, start_date, end_date, outlet_id=None):
        """
        Generate time-based sales analysis.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with time-based patterns
        """
        log_tag = f"[performance_analytics_service.py][PerformanceAnalyticsService][generate_time_based_analysis][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
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
            
            # Get all sales
            sales = list(collection.find(match_query))
            
            # Analyze by hour
            by_hour = defaultdict(lambda: {"count": 0, "revenue": 0.0})
            by_day_of_week = defaultdict(lambda: {"count": 0, "revenue": 0.0})
            by_date = defaultdict(lambda: {"count": 0, "revenue": 0.0})
            
            for sale in sales:
                created_at = sale.get("created_at")
                revenue = float(sale.get("cart", {}).get("totals", {}).get("grand_total", 0))
                
                if created_at:
                    # By hour
                    hour = created_at.hour
                    by_hour[hour]["count"] += 1
                    by_hour[hour]["revenue"] += revenue
                    
                    # By day of week (0=Monday, 6=Sunday)
                    day_of_week = created_at.weekday()
                    by_day_of_week[day_of_week]["count"] += 1
                    by_day_of_week[day_of_week]["revenue"] += revenue
                    
                    # By date
                    date_str = created_at.strftime("%Y-%m-%d")
                    by_date[date_str]["count"] += 1
                    by_date[date_str]["revenue"] += revenue
            
            # Format hourly data
            hourly_data = [
                {
                    "hour": hour,
                    "transaction_count": data["count"],
                    "total_revenue": round(data["revenue"], 2),
                    "average_transaction": round(data["revenue"] / data["count"] if data["count"] > 0 else 0, 2)
                }
                for hour, data in sorted(by_hour.items())
            ]
            
            # Format daily data
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            daily_data = [
                {
                    "day_of_week": day_names[day],
                    "transaction_count": data["count"],
                    "total_revenue": round(data["revenue"], 2),
                    "average_transaction": round(data["revenue"] / data["count"] if data["count"] > 0 else 0, 2)
                }
                for day, data in sorted(by_day_of_week.items())
            ]
            
            # Format date trend
            date_trend = [
                {
                    "date": date,
                    "transaction_count": data["count"],
                    "total_revenue": round(data["revenue"], 2)
                }
                for date, data in sorted(by_date.items())
            ]
            
            # Identify peak hours and slow periods
            sorted_hours = sorted(by_hour.items(), key=lambda x: x[1]["revenue"], reverse=True)
            peak_hours = [{"hour": h, "revenue": round(d["revenue"], 2)} for h, d in sorted_hours[:3]]
            slow_hours = [{"hour": h, "revenue": round(d["revenue"], 2)} for h, d in sorted_hours[-3:]]
            
            Log.info(f"{log_tag} Generated time-based analysis")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "by_hour": hourly_data,
                "by_day_of_week": daily_data,
                "date_trend": date_trend,
                "insights": {
                    "peak_hours": peak_hours,
                    "slow_hours": slow_hours
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_category_performance(business_id, start_date, end_date, outlet_id=None):
        """
        Generate category performance report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with category performance data
        """
        log_tag = f"[performance_analytics_service.py][PerformanceAnalyticsService][generate_category_performance][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
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
            
            # Aggregate by category
            pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {
                    "$group": {
                        "_id": "$cart.lines.category",
                        "units_sold": {"$sum": "$cart.lines.quantity"},
                        "revenue": {"$sum": "$cart.lines.line_total"},
                        "cost": {"$sum": {"$multiply": ["$cart.lines.quantity", "$cart.lines.cost_price"]}}
                    }
                },
                {"$sort": {"revenue": -1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Calculate totals
            total_revenue = sum(float(r["revenue"]) for r in results)
            total_units = sum(float(r["units_sold"]) for r in results)
            
            # Format category data
            categories = []
            for rank, item in enumerate(results, 1):
                revenue = float(item["revenue"])
                cost = float(item["cost"])
                units = float(item["units_sold"])
                profit = revenue - cost
                margin = (profit / revenue * 100) if revenue > 0 else 0
                
                categories.append({
                    "rank": rank,
                    "category": item["_id"] or "Uncategorized",
                    "units_sold": int(units),
                    "revenue": round(revenue, 2),
                    "cost": round(cost, 2),
                    "profit": round(profit, 2),
                    "margin_percentage": round(margin, 2),
                    "revenue_percentage": round((revenue / total_revenue * 100) if total_revenue > 0 else 0, 2),
                    "units_percentage": round((units / total_units * 100) if total_units > 0 else 0, 2)
                })
            
            Log.info(f"{log_tag} Generated category performance report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "categories": categories,
                "summary": {
                    "total_categories": len(categories),
                    "total_revenue": round(total_revenue, 2),
                    "total_units": int(total_units)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_discount_analysis(business_id, start_date, end_date, outlet_id=None):
        """
        Generate discount and promotion analysis.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with discount analysis data
        """
        log_tag = f"[performance_analytics_service.py][PerformanceAnalyticsService][generate_discount_analysis][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
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
            
            # Get all sales
            all_sales_pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "total_sales": {"$sum": 1},
                        "total_revenue": {"$sum": "$cart.totals.grand_total"},
                        "total_discount": {"$sum": "$cart.totals.total_discount"}
                    }
                }
            ]
            
            all_sales = list(collection.aggregate(all_sales_pipeline))
            
            if not all_sales:
                return None
            
            total_sales = int(all_sales[0]["total_sales"])
            total_revenue = float(all_sales[0]["total_revenue"])
            total_discount = float(all_sales[0]["total_discount"])
            
            # Sales with discounts
            discount_sales_pipeline = [
                {
                    "$match": {
                        **match_query,
                        "cart.totals.total_discount": {"$gt": 0}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "discount_sales_count": {"$sum": 1},
                        "discount_revenue": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            discount_sales = list(collection.aggregate(discount_sales_pipeline))
            discount_sales_count = int(discount_sales[0]["discount_sales_count"]) if discount_sales else 0
            discount_revenue = float(discount_sales[0]["discount_revenue"]) if discount_sales else 0.0
            
            # Discount by type (if tracked)
            # This would require storing discount types in sales
            by_type = []  # TODO: Implement if discount types are stored
            
            # Top discounted products
            product_pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {
                    "$match": {
                        "cart.lines.discount": {"$gt": 0}
                    }
                },
                {
                    "$group": {
                        "_id": "$cart.lines.product_id",
                        "product_name": {"$first": "$cart.lines.product_name"},
                        "discount_count": {"$sum": 1},
                        "total_discount": {"$sum": "$cart.lines.discount"}
                    }
                },
                {"$sort": {"total_discount": -1}},
                {"$limit": 20}
            ]
            
            product_results = list(collection.aggregate(product_pipeline))
            
            top_discounted_products = [
                {
                    "product_id": str(item["_id"]),
                    "product_name": item["product_name"],
                    "discount_count": int(item["discount_count"]),
                    "total_discount": round(float(item["total_discount"]), 2)
                }
                for item in product_results
            ]
            
            Log.info(f"{log_tag} Generated discount analysis")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "total_discount_given": round(total_discount, 2),
                    "discount_percentage_of_revenue": round((total_discount / (total_revenue + total_discount) * 100) if (total_revenue + total_discount) > 0 else 0, 2),
                    "sales_with_discount": discount_sales_count,
                    "sales_with_discount_percentage": round((discount_sales_count / total_sales * 100) if total_sales > 0 else 0, 2),
                    "average_discount_per_sale": round(total_discount / discount_sales_count if discount_sales_count > 0 else 0, 2)
                },
                "by_type": by_type,
                "top_discounted_products": top_discounted_products
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_product_affinity_report(business_id, start_date, end_date, min_support=0.01):
        """
        Generate product affinity (bought together) analysis.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            min_support: Minimum support threshold
            
        Returns:
            Dict with product affinity data
        """
        log_tag = f"[performance_analytics_service.py][PerformanceAnalyticsService][generate_product_affinity_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": "Completed"
            }
            
            # Get all sales with multiple items
            sales = list(collection.find(match_query))
            
            total_transactions = len(sales)
            product_counts = defaultdict(int)
            pair_counts = defaultdict(int)
            
            # Count individual products and pairs
            for sale in sales:
                lines = sale.get("cart", {}).get("lines", [])
                
                if len(lines) < 2:
                    continue
                
                products = [line.get("product_id") for line in lines if line.get("product_id")]
                
                # Count individual products
                for product_id in products:
                    product_counts[product_id] += 1
                
                # Count pairs
                for product_a, product_b in combinations(set(products), 2):
                    pair = tuple(sorted([str(product_a), str(product_b)]))
                    pair_counts[pair] += 1
            
            # Calculate metrics for top pairs
            affinity_pairs = []
            
            for pair, count in pair_counts.items():
                support = count / total_transactions
                
                if support < min_support:
                    continue
                
                product_a_id, product_b_id = pair
                
                # Calculate confidence
                product_a_count = product_counts[ObjectId(product_a_id)]
                product_b_count = product_counts[ObjectId(product_b_id)]
                
                confidence_a_to_b = count / product_a_count if product_a_count > 0 else 0
                confidence_b_to_a = count / product_b_count if product_b_count > 0 else 0
                
                # Calculate lift
                expected_together = (product_a_count / total_transactions) * (product_b_count / total_transactions)
                lift = support / expected_together if expected_together > 0 else 0
                
                # Get product names
                products_collection = db.get_collection(Product.collection_name)
                product_a = products_collection.find_one({"_id": ObjectId(product_a_id)})
                product_b = products_collection.find_one({"_id": ObjectId(product_b_id)})
                
                if product_a and product_b:
                    affinity_pairs.append({
                        "product_a_id": product_a_id,
                        "product_a_name": product_a.get("name"),
                        "product_b_id": product_b_id,
                        "product_b_name": product_b.get("name"),
                        "times_bought_together": count,
                        "support": round(support, 4),
                        "confidence_a_to_b": round(confidence_a_to_b, 4),
                        "confidence_b_to_a": round(confidence_b_to_a, 4),
                        "lift": round(lift, 2)
                    })
            
            # Sort by lift (strongest associations first)
            affinity_pairs.sort(key=lambda x: x["lift"], reverse=True)
            
            Log.info(f"{log_tag} Generated product affinity report with {len(affinity_pairs)} pairs")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "total_transactions": total_transactions,
                    "affinity_pairs_found": len(affinity_pairs),
                    "min_support_threshold": min_support
                },
                "affinity_pairs": affinity_pairs[:50]  # Top 50
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None