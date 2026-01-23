# services/sales_report_service.py
from datetime import datetime, timedelta
from bson import ObjectId
from app import db
from ....models.admin.sale import Sale
from ....utils.logger import Log


class SalesReportService:
    """Service for generating sales reports with MongoDB aggregations."""
    
    @staticmethod
    def generate_sales_summary(business_id, start_date, end_date, outlet_id=None, user_id=None):
        """
        Generate comprehensive sales summary report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            user_id: Optional cashier filter
            
        Returns:
            Dict with sales metrics
        """
        log_tag = f"[sales_report_service.py][SalesReportService][generate_sales_summary][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            if user_id:
                match_query["user_id"] = user_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Main aggregation pipeline
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "total_sales": {
                            "$sum": {
                                "$cond": [
                                    {"$ne": ["$status", "Voided"]},
                                    "$cart.totals.grand_total",
                                    0
                                ]
                            }
                        },
                        "gross_sales": {
                            "$sum": {
                                "$cond": [
                                    {"$ne": ["$status", "Voided"]},
                                    "$cart.totals.subtotal",
                                    0
                                ]
                            }
                        },
                        "total_discount": {
                            "$sum": {
                                "$cond": [
                                    {"$ne": ["$status", "Voided"]},
                                    "$cart.totals.total_discount",
                                    0
                                ]
                            }
                        },
                        "total_tax": {
                            "$sum": {
                                "$cond": [
                                    {"$ne": ["$status", "Voided"]},
                                    "$cart.totals.total_tax",
                                    0
                                ]
                            }
                        },
                        "sales_count": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Completed"]},
                                    1,
                                    0
                                ]
                            }
                        },
                        "voided_count": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Voided"]},
                                    1,
                                    0
                                ]
                            }
                        },
                        "return_count": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", ["Refunded", "Partially_Refunded"]]},
                                    1,
                                    0
                                ]
                            }
                        },
                        "max_sale": {"$max": "$cart.totals.grand_total"},
                        "min_sale": {"$min": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            result = list(collection.aggregate(pipeline))
            
            if not result or len(result) == 0:
                Log.info(f"{log_tag} No sales data found")
                return {
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "days": (end_date - start_date).days + 1
                    },
                    "sales_metrics": {
                        "total_sales": 0.0,
                        "gross_sales": 0.0,
                        "net_sales": 0.0,
                        "total_discount": 0.0,
                        "total_tax": 0.0,
                        "sales_count": 0,
                        "return_count": 0,
                        "voided_count": 0,
                        "average_sale_value": 0.0,
                        "largest_sale": 0.0,
                        "smallest_sale": 0.0
                    }
                }
            
            data = result[0]
            
            # Calculate derived metrics
            total_sales = float(data.get("total_sales", 0))
            gross_sales = float(data.get("gross_sales", 0))
            total_discount = float(data.get("total_discount", 0))
            total_tax = float(data.get("total_tax", 0))
            sales_count = int(data.get("sales_count", 0))
            
            net_sales = gross_sales - total_discount
            average_sale = total_sales / sales_count if sales_count > 0 else 0.0
            
            # Get payment breakdown
            payment_breakdown = SalesReportService._get_payment_breakdown(
                collection, match_query
            )
            
            # Get daily breakdown for trends
            daily_sales = SalesReportService._get_daily_sales(
                collection, match_query
            )
            
            report = {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": (end_date - start_date).days + 1
                },
                "sales_metrics": {
                    "total_sales": round(total_sales, 2),
                    "gross_sales": round(gross_sales, 2),
                    "net_sales": round(net_sales, 2),
                    "total_discount": round(total_discount, 2),
                    "total_tax": round(total_tax, 2),
                    "sales_count": sales_count,
                    "return_count": int(data.get("return_count", 0)),
                    "voided_count": int(data.get("voided_count", 0)),
                    "average_sale_value": round(average_sale, 2),
                    "largest_sale": round(float(data.get("max_sale", 0)), 2),
                    "smallest_sale": round(float(data.get("min_sale", 0)), 2)
                },
                "payment_breakdown": payment_breakdown,
                "daily_sales": daily_sales
            }
            
            Log.info(f"{log_tag} Report generated successfully")
            return report
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def _get_payment_breakdown(collection, base_match):
        """Get sales breakdown by payment method."""
        pipeline = [
            {"$match": {**base_match, "status": {"$ne": "Voided"}}},
            {
                "$group": {
                    "_id": "$payment_method",
                    "amount": {"$sum": "$cart.totals.grand_total"},
                    "count": {"$sum": 1}
                }
            }
        ]
        
        results = list(collection.aggregate(pipeline))
        
        breakdown = {}
        for item in results:
            method = item["_id"]
            breakdown[method] = {
                "amount": round(float(item["amount"]), 2),
                "count": int(item["count"])
            }
        
        return breakdown
    
    @staticmethod
    def _get_daily_sales(collection, base_match):
        """Get daily sales breakdown."""
        pipeline = [
            {"$match": {**base_match, "status": {"$ne": "Voided"}}},
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$created_at"
                        }
                    },
                    "sales": {"$sum": "$cart.totals.grand_total"},
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        
        results = list(collection.aggregate(pipeline))
        
        daily = []
        for item in results:
            daily.append({
                "date": item["_id"],
                "sales": round(float(item["sales"]), 2),
                "transaction_count": int(item["count"])
            })
        
        return daily
    
    @staticmethod
    def generate_sales_by_product(business_id, start_date, end_date, outlet_id=None, limit=50):
        """
        Generate sales by product report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            limit: Max number of products to return
            
        Returns:
            Dict with product sales data
        """
        log_tag = f"[sales_report_service.py][SalesReportService][generate_sales_by_product][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
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
            
            collection = db.get_collection(Sale.collection_name)
            
            pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {
                    "$group": {
                        "_id": "$cart.lines.product_id",
                        "product_name": {"$first": "$cart.lines.product_name"},
                        "quantity_sold": {"$sum": "$cart.lines.quantity"},
                        "revenue": {"$sum": "$cart.lines.line_total"},
                        "discount_given": {"$sum": "$cart.lines.discount_amount"},
                        "tax_collected": {"$sum": "$cart.lines.tax_amount"},
                        "sales_count": {"$sum": 1}
                    }
                },
                {
                    "$addFields": {
                        "average_price": {
                            "$divide": ["$revenue", "$quantity_sold"]
                        }
                    }
                },
                {"$sort": {"revenue": -1}},
                {"$limit": limit}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Calculate total for percentages
            total_revenue = sum(float(item["revenue"]) for item in results)
            
            products = []
            for item in results:
                revenue = float(item["revenue"])
                products.append({
                    "product_id": item["_id"],
                    "product_name": item["product_name"],
                    "quantity_sold": float(item["quantity_sold"]),
                    "revenue": round(revenue, 2),
                    "discount_given": round(float(item["discount_given"]), 2),
                    "tax_collected": round(float(item["tax_collected"]), 2),
                    "sales_count": int(item["sales_count"]),
                    "average_price": round(float(item["average_price"]), 2),
                    "contribution_percentage": round((revenue / total_revenue * 100) if total_revenue > 0 else 0, 2)
                })
            
            summary = {
                "total_products": len(products),
                "total_quantity": sum(p["quantity_sold"] for p in products),
                "total_revenue": round(total_revenue, 2)
            }
            
            Log.info(f"{log_tag} Generated report for {len(products)} products")
            
            return {
                "products": products,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_sales_by_cashier(business_id, start_date, end_date, outlet_id=None):
        """
        Generate sales by cashier performance report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with cashier performance data
        """
        log_tag = f"[sales_report_service.py][SalesReportService][generate_sales_by_cashier][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": {"$ne": "Voided"}
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            collection = db.get_collection(Sale.collection_name)
            
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": "$user_id",
                        "user__id": {"$first": "$user__id"},
                        "sales_count": {"$sum": 1},
                        "revenue": {"$sum": "$cart.totals.grand_total"},
                        "discount_given": {"$sum": "$cart.totals.total_discount"},
                        "voided": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Voided"]},
                                    1,
                                    0
                                ]
                            }
                        }
                    }
                },
                {
                    "$addFields": {
                        "average_sale": {
                            "$divide": ["$revenue", "$sales_count"]
                        }
                    }
                },
                {"$sort": {"revenue": -1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            cashiers = []
            for item in results:
                cashiers.append({
                    "user_id": item["_id"],
                    "user__id": str(item["user__id"]),
                    "sales_count": int(item["sales_count"]),
                    "revenue": round(float(item["revenue"]), 2),
                    "average_sale": round(float(item["average_sale"]), 2),
                    "discount_given": round(float(item["discount_given"]), 2),
                    "voids_processed": int(item["voided"])
                })
            
            summary = {
                "total_cashiers": len(cashiers),
                "total_sales": sum(c["sales_count"] for c in cashiers),
                "total_revenue": sum(c["revenue"] for c in cashiers)
            }
            
            Log.info(f"{log_tag} Generated report for {len(cashiers)} cashiers")
            
            return {
                "cashiers": cashiers,
                "summary": summary
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None