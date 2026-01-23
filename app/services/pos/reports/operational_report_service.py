# services/reports/operational_report_service.py
from datetime import datetime, timedelta
from ....utils.crypt import decrypt_data
from bson import ObjectId
from ....models.admin.sale import Sale
from ....models.user_model import User
from app import db
from ....utils.logger import Log


class OperationalReportService:
    """Service for generating operational reports and analytics."""
    
    @staticmethod
    def generate_refunds_returns_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate refunds and returns report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with refunds and returns data
        """
        log_tag = f"[operational_report_service.py][OperationalReportService][generate_refunds_returns_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": {"$in": ["Refunded", "Partially_Refunded"]}
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get refund details
            refunds = list(collection.find(match_query).sort("created_at", -1))
            
            # Get total sales for rate calculation
            total_sales_pipeline = [
                {
                    "$match": {
                        "business_id": business_id,
                        "created_at": {
                            "$gte": start_date,
                            "$lte": end_date
                        },
                        "status": {"$in": ["Completed", "Refunded", "Partially_Refunded"]}
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "total_count": {"$sum": 1},
                        "total_value": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            total_sales_result = list(collection.aggregate(total_sales_pipeline))
            total_sales_count = int(total_sales_result[0]["total_count"]) if total_sales_result else 0
            total_sales_value = float(total_sales_result[0]["total_value"]) if total_sales_result else 0.0
            
            # Process refunds
            refund_list = []
            total_refund_value = 0.0
            refunds_by_reason = {}
            refunds_by_product = {}
            refunds_by_cashier = {}
            
            for sale in refunds:
                refund_amount = float(sale.get("cart", {}).get("totals", {}).get("grand_total", 0))
                total_refund_value += refund_amount
                
                # Reason tracking (if available in metadata)
                reason = sale.get("refund_reason", "Not Specified")
                refunds_by_reason[reason] = refunds_by_reason.get(reason, 0) + 1
                
                # Cashier tracking
                cashier_id = str(sale.get("cashier_id", "Unknown"))
                if cashier_id not in refunds_by_cashier:
                    refunds_by_cashier[cashier_id] = {"count": 0, "amount": 0.0}
                refunds_by_cashier[cashier_id]["count"] += 1
                refunds_by_cashier[cashier_id]["amount"] += refund_amount
                
                # Product tracking
                for line in sale.get("cart", {}).get("lines", []):
                    product_name = line.get("product_name")
                    if product_name not in refunds_by_product:
                        refunds_by_product[product_name] = {
                            "count": 0,
                            "quantity": 0,
                            "amount": 0.0
                        }
                    refunds_by_product[product_name]["count"] += 1
                    refunds_by_product[product_name]["quantity"] += float(line.get("quantity", 0))
                    refunds_by_product[product_name]["amount"] += float(line.get("line_total", 0))
                
                # Add to list
                refund_list.append({
                    "sale_id": str(sale["_id"]),
                    "original_sale_id": str(sale.get("original_sale_id", "")),
                    "date": sale.get("created_at").isoformat() if sale.get("created_at") else None,
                    "outlet_id": str(sale.get("outlet_id")),
                    "cashier_id": cashier_id,
                    "customer_id": str(sale.get("customer_id")) if sale.get("customer_id") else None,
                    "amount": round(refund_amount, 2),
                    "reason": reason,
                    "status": sale.get("status"),
                    "items": [
                        {
                            "product_name": line.get("product_name"),
                            "quantity": float(line.get("quantity", 0)),
                            "amount": round(float(line.get("line_total", 0)), 2)
                        }
                        for line in sale.get("cart", {}).get("lines", [])
                    ]
                })
            
            # Format by-reason breakdown
            reasons_breakdown = [
                {
                    "reason": reason,
                    "count": count,
                    "percentage": round((count / len(refunds) * 100) if len(refunds) > 0 else 0, 2)
                }
                for reason, count in sorted(refunds_by_reason.items(), key=lambda x: x[1], reverse=True)
            ]
            
            # Format by-product breakdown
            products_breakdown = [
                {
                    "product_name": product,
                    "refund_count": data["count"],
                    "quantity_returned": int(data["quantity"]),
                    "total_amount": round(data["amount"], 2)
                }
                for product, data in sorted(refunds_by_product.items(), key=lambda x: x[1]["amount"], reverse=True)
            ][:20]  # Top 20
            
            # Calculate rates
            refund_rate = (len(refunds) / total_sales_count * 100) if total_sales_count > 0 else 0
            refund_value_rate = (total_refund_value / total_sales_value * 100) if total_sales_value > 0 else 0
            
            Log.info(f"{log_tag} Generated refunds report with {len(refunds)} refunds")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "total_refunds": len(refunds),
                    "total_refund_value": round(total_refund_value, 2),
                    "refund_rate": round(refund_rate, 2),
                    "refund_value_rate": round(refund_value_rate, 2),
                    "average_refund_value": round(total_refund_value / len(refunds) if len(refunds) > 0 else 0, 2),
                    "total_sales_count": total_sales_count,
                    "total_sales_value": round(total_sales_value, 2)
                },
                "refunds": refund_list[:100],  # Limit to 100 most recent
                "by_reason": reasons_breakdown,
                "by_product": products_breakdown
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_voids_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate voided transactions report.
        
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with voided transactions data
        """
        log_tag = f"[operational_report_service.py][OperationalReportService][generate_voids_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_date,
                    "$lte": end_date
                },
                "status": "Voided"
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get voided transactions
            voids = list(collection.find(match_query).sort("created_at", -1))
            
            # Process voids
            void_list = []
            total_void_value = 0.0
            voids_by_cashier = {}
            voids_by_hour = {}
            voids_by_reason = {}
            
            for sale in voids:
                void_amount = float(sale.get("cart", {}).get("totals", {}).get("grand_total", 0))
                total_void_value += void_amount
                
                cashier_id = str(sale.get("cashier_id", "Unknown"))
                if cashier_id not in voids_by_cashier:
                    voids_by_cashier[cashier_id] = {"count": 0, "amount": 0.0}
                voids_by_cashier[cashier_id]["count"] += 1
                voids_by_cashier[cashier_id]["amount"] += void_amount
                
                # Hour tracking
                created_at = sale.get("created_at")
                if created_at:
                    hour = created_at.hour
                    voids_by_hour[hour] = voids_by_hour.get(hour, 0) + 1
                
                # Reason tracking
                reason = sale.get("void_reason", "Not Specified")
                voids_by_reason[reason] = voids_by_reason.get(reason, 0) + 1
                
                void_list.append({
                    "sale_id": str(sale["_id"]),
                    "date": created_at.isoformat() if created_at else None,
                    "outlet_id": str(sale.get("outlet_id")),
                    "cashier_id": cashier_id,
                    "amount": round(void_amount, 2),
                    "reason": reason,
                    "authorized_by": str(sale.get("void_authorized_by")) if sale.get("void_authorized_by") else None,
                    "items_count": len(sale.get("cart", {}).get("lines", []))
                })
            
            # Format cashier breakdown
            cashier_breakdown = [
                {
                    "cashier_id": cashier_id,
                    "void_count": data["count"],
                    "total_amount": round(data["amount"], 2),
                    "percentage": round((data["count"] / len(voids) * 100) if len(voids) > 0 else 0, 2)
                }
                for cashier_id, data in sorted(voids_by_cashier.items(), key=lambda x: x[1]["count"], reverse=True)
            ]
            
            # Format time pattern
            time_pattern = [
                {
                    "hour": hour,
                    "count": count
                }
                for hour, count in sorted(voids_by_hour.items())
            ]
            
            # Format reasons
            reasons_breakdown = [
                {
                    "reason": reason,
                    "count": count,
                    "percentage": round((count / len(voids) * 100) if len(voids) > 0 else 0, 2)
                }
                for reason, count in sorted(voids_by_reason.items(), key=lambda x: x[1], reverse=True)
            ]
            
            Log.info(f"{log_tag} Generated voids report with {len(voids)} voids")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "summary": {
                    "total_voids": len(voids),
                    "total_void_value": round(total_void_value, 2),
                    "average_void_value": round(total_void_value / len(voids) if len(voids) > 0 else 0, 2)
                },
                "voids": void_list[:100],  # Limit to 100 most recent
                "by_cashier": cashier_breakdown,
                "by_time": time_pattern,
                "by_reason": reasons_breakdown
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_atv_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate Average Transaction Value report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with ATV metrics
        """
        log_tag = f"[operational_report_service.py][OperationalReportService][generate_atv_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
            # Build match query
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
            
            # Overall ATV
            overall_pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "transaction_count": {"$sum": 1},
                        "total_revenue": {"$sum": "$cart.totals.grand_total"},
                        "total_items": {"$sum": {"$size": "$cart.lines"}}
                    }
                }
            ]
            
            overall_result = list(collection.aggregate(overall_pipeline))
            
            if not overall_result:
                return None
            
            overall = overall_result[0]
            transaction_count = int(overall["transaction_count"])
            total_revenue = float(overall["total_revenue"])
            total_items = int(overall["total_items"])
            
            overall_atv = total_revenue / transaction_count if transaction_count > 0 else 0
            items_per_transaction = total_items / transaction_count if transaction_count > 0 else 0
            
            # ATV by outlet (if not filtered)
            atv_by_outlet = []
            if not outlet_id:
                outlet_pipeline = [
                    {"$match": match_query},
                    {
                        "$group": {
                            "_id": "$outlet_id",
                            "transaction_count": {"$sum": 1},
                            "total_revenue": {"$sum": "$cart.totals.grand_total"},
                            "avg_transaction": {"$avg": "$cart.totals.grand_total"}
                        }
                    },
                    {"$sort": {"avg_transaction": -1}}
                ]
                
                outlet_results = list(collection.aggregate(outlet_pipeline))
                
                atv_by_outlet = [
                    {
                        "outlet_id": str(item["_id"]),
                        "transaction_count": int(item["transaction_count"]),
                        "total_revenue": round(float(item["total_revenue"]), 2),
                        "average_transaction_value": round(float(item["avg_transaction"]), 2)
                    }
                    for item in outlet_results
                ]
            
            # ATV by cashier
            cashier_pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": "$cashier_id",
                        "transaction_count": {"$sum": 1},
                        "total_revenue": {"$sum": "$cart.totals.grand_total"},
                        "avg_transaction": {"$avg": "$cart.totals.grand_total"}
                    }
                },
                {"$sort": {"avg_transaction": -1}}
            ]
            
            cashier_results = list(collection.aggregate(cashier_pipeline))
            
            atv_by_cashier = [
                {
                    "cashier_id": str(item["_id"]),
                    "transaction_count": int(item["transaction_count"]),
                    "total_revenue": round(float(item["total_revenue"]), 2),
                    "average_transaction_value": round(float(item["avg_transaction"]), 2)
                }
                for item in cashier_results
            ]
            
            # ATV trend by day
            daily_pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$created_at"
                            }
                        },
                        "transaction_count": {"$sum": 1},
                        "total_revenue": {"$sum": "$cart.totals.grand_total"},
                        "avg_transaction": {"$avg": "$cart.totals.grand_total"}
                    }
                },
                {"$sort": {"_id": 1}}
            ]
            
            daily_results = list(collection.aggregate(daily_pipeline))
            
            atv_trend = [
                {
                    "date": item["_id"],
                    "transaction_count": int(item["transaction_count"]),
                    "total_revenue": round(float(item["total_revenue"]), 2),
                    "average_transaction_value": round(float(item["avg_transaction"]), 2)
                }
                for item in daily_results
            ]
            
            Log.info(f"{log_tag} Generated ATV report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "overall": {
                    "average_transaction_value": round(overall_atv, 2),
                    "transaction_count": transaction_count,
                    "total_revenue": round(total_revenue, 2),
                    "average_items_per_transaction": round(items_per_transaction, 2)
                },
                "by_outlet": atv_by_outlet,
                "by_cashier": atv_by_cashier[:20],  # Top 20
                "trend": atv_trend
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_enhanced_cashier_performance(business_id, start_date, end_date, outlet_id=None):
        """
        Generate enhanced cashier performance report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with detailed cashier performance metrics
        """
        log_tag = f"[operational_report_service.py][OperationalReportService][generate_enhanced_cashier_performance][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(Sale.collection_name)
            
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
            
            # Aggregate cashier performance
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": "$cashier_id",
                        "completed_sales": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "Completed"]}, 1, 0]
                            }
                        },
                        "completed_revenue": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Completed"]},
                                    "$cart.totals.grand_total",
                                    0
                                ]
                            }
                        },
                        "voids": {
                            "$sum": {
                                "$cond": [{"$eq": ["$status", "Voided"]}, 1, 0]
                            }
                        },
                        "void_value": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Voided"]},
                                    "$cart.totals.grand_total",
                                    0
                                ]
                            }
                        },
                        "refunds": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", ["Refunded", "Partially_Refunded"]]},
                                    1,
                                    0
                                ]
                            }
                        },
                        "refund_value": {
                            "$sum": {
                                "$cond": [
                                    {"$in": ["$status", ["Refunded", "Partially_Refunded"]]},
                                    "$cart.totals.grand_total",
                                    0
                                ]
                            }
                        },
                        "total_discounts": {"$sum": "$cart.totals.total_discount"},
                        "total_items_sold": {
                            "$sum": {
                                "$cond": [
                                    {"$eq": ["$status", "Completed"]},
                                    {"$size": "$cart.lines"},
                                    0
                                ]
                            }
                        }
                    }
                },
                {"$sort": {"completed_revenue": -1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Format results
            cashier_performance = []
            for item in results:
                cashier_id = str(item["_id"])
                completed_sales = int(item["completed_sales"])
                completed_revenue = float(item["completed_revenue"])
                voids = int(item["voids"])
                refunds = int(item["refunds"])
                
                total_transactions = completed_sales + voids + refunds
                
                # Get cashier details
                cashier = User.get_by_id(cashier_id, str(business_id))
                if cashier:
                    fullname = cashier.get("fullname", "")
                    cashier_name = decrypt_data(fullname)
                else:
                    cashier_name = "Unknown"
                
                cashier_performance.append({
                    "cashier_id": cashier_id,
                    "cashier_name": cashier_name,
                    "completed_sales": completed_sales,
                    "completed_revenue": round(completed_revenue, 2),
                    "average_transaction_value": round(completed_revenue / completed_sales if completed_sales > 0 else 0, 2),
                    "total_items_sold": int(item["total_items_sold"]),
                    "items_per_transaction": round(item["total_items_sold"] / completed_sales if completed_sales > 0 else 0, 2),
                    "voids": {
                        "count": voids,
                        "value": round(float(item["void_value"]), 2),
                        "rate": round((voids / total_transactions * 100) if total_transactions > 0 else 0, 2)
                    },
                    "refunds": {
                        "count": refunds,
                        "value": round(float(item["refund_value"]), 2),
                        "rate": round((refunds / total_transactions * 100) if total_transactions > 0 else 0, 2)
                    },
                    "discounts_given": round(float(item["total_discounts"]), 2),
                    "discount_rate": round((item["total_discounts"] / completed_revenue * 100) if completed_revenue > 0 else 0, 2)
                })
            
            # Calculate summary
            total_sales = sum(c["completed_sales"] for c in cashier_performance)
            total_revenue = sum(c["completed_revenue"] for c in cashier_performance)
            
            Log.info(f"{log_tag} Generated enhanced cashier performance report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "cashiers": cashier_performance,
                "summary": {
                    "total_cashiers": len(cashier_performance),
                    "total_sales": total_sales,
                    "total_revenue": round(total_revenue, 2),
                    "average_revenue_per_cashier": round(total_revenue / len(cashier_performance) if len(cashier_performance) > 0 else 0, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None