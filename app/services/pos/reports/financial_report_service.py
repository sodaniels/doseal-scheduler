# services/reports/financial_report_service.py
from datetime import datetime, timedelta
from bson import ObjectId
from ....models.admin.sale import Sale
from app import db
from ....utils.logger import Log


class FinancialReportService:
    """Service for generating financial reports and analytics."""
    
    @staticmethod
    def generate_payment_methods_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate payment methods analysis report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with payment methods data
        """
        log_tag = f"[financial_report_service.py][FinancialReportService][generate_payment_methods_report][{business_id}]"
        
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
                "status": {"$in": ["Completed", "Partially_Refunded"]}
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Aggregate by payment method
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": "$payment_method",
                        "transaction_count": {"$sum": 1},
                        "total_amount": {"$sum": "$cart.totals.grand_total"},
                        "average_transaction": {"$avg": "$cart.totals.grand_total"}
                    }
                },
                {"$sort": {"total_amount": -1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Calculate totals
            total_transactions = sum(item["transaction_count"] for item in results)
            total_amount = sum(float(item["total_amount"]) for item in results)
            
            # Format results
            payment_methods = []
            for item in results:
                method = item["_id"] or "Unknown"
                count = int(item["transaction_count"])
                amount = float(item["total_amount"])
                
                payment_methods.append({
                    "payment_method": method,
                    "transaction_count": count,
                    "transaction_percentage": round((count / total_transactions * 100) if total_transactions > 0 else 0, 2),
                    "total_amount": round(amount, 2),
                    "amount_percentage": round((amount / total_amount * 100) if total_amount > 0 else 0, 2),
                    "average_transaction": round(float(item["average_transaction"]), 2)
                })
            
            # Get failed transactions (if tracked)
            failed_match = match_query.copy()
            failed_match["status"] = "Failed"
            failed_count = collection.count_documents(failed_match)
            
            Log.info(f"{log_tag} Generated payment methods report with {len(payment_methods)} methods")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "payment_methods": payment_methods,
                "summary": {
                    "total_transactions": total_transactions,
                    "total_amount": round(total_amount, 2),
                    "failed_transactions": failed_count,
                    "success_rate": round(((total_transactions / (total_transactions + failed_count)) * 100) if (total_transactions + failed_count) > 0 else 0, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_cash_flow_report(business_id, date, outlet_id=None):
        """
        Generate daily cash flow report.
        
        Args:
            business_id: Business ObjectId or string
            date: datetime - specific date
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with cash flow data
        """
        log_tag = f"[financial_report_service.py][FinancialReportService][generate_cash_flow_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # Get start and end of day
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            collection = db.get_collection(Sale.collection_name)
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "created_at": {
                    "$gte": start_of_day,
                    "$lte": end_of_day
                },
                "payment_method": "cash"
            }
            
            if outlet_id:
                match_query["outlet_id"] = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get cash sales
            sales_pipeline = [
                {"$match": {**match_query, "status": "Completed"}},
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": "$cart.totals.grand_total"},
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            sales_result = list(collection.aggregate(sales_pipeline))
            cash_sales = float(sales_result[0]["total"]) if sales_result else 0.0
            sales_count = sales_result[0]["count"] if sales_result else 0
            
            # Get cash refunds
            refunds_pipeline = [
                {"$match": {**match_query, "status": {"$in": ["Refunded", "Partially_Refunded"]}}},
                {
                    "$group": {
                        "_id": None,
                        "total": {"$sum": "$cart.totals.grand_total"},
                        "count": {"$sum": 1}
                    }
                }
            ]
            
            refunds_result = list(collection.aggregate(refunds_pipeline))
            cash_refunds = float(refunds_result[0]["total"]) if refunds_result else 0.0
            refunds_count = refunds_result[0]["count"] if refunds_result else 0
            
            # TODO: Get opening balance from previous day's closing
            # This should be stored in a separate cash_register or shift collection
            opening_balance = 0.0  # Placeholder
            
            # TODO: Get deposits/withdrawals from cash_transactions collection
            deposits = 0.0  # Placeholder
            withdrawals = 0.0  # Placeholder
            
            # Calculate closing balance
            closing_balance = opening_balance + cash_sales - cash_refunds + deposits - withdrawals
            
            # Calculate expected vs actual (for reconciliation)
            expected_balance = closing_balance
            actual_balance = 0.0  # This should come from physical count
            variance = actual_balance - expected_balance
            
            Log.info(f"{log_tag} Generated cash flow report for {date.date()}")
            
            return {
                "date": date.date().isoformat(),
                "outlet_id": str(outlet_id) if outlet_id else None,
                "cash_flow": {
                    "opening_balance": round(opening_balance, 2),
                    "cash_sales": round(cash_sales, 2),
                    "cash_refunds": round(cash_refunds, 2),
                    "deposits": round(deposits, 2),
                    "withdrawals": round(withdrawals, 2),
                    "closing_balance": round(closing_balance, 2)
                },
                "transactions": {
                    "sales_count": sales_count,
                    "refunds_count": refunds_count
                },
                "reconciliation": {
                    "expected_balance": round(expected_balance, 2),
                    "actual_balance": round(actual_balance, 2),
                    "variance": round(variance, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_tax_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate tax collection report.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with tax data
        """
        log_tag = f"[financial_report_service.py][FinancialReportService][generate_tax_report][{business_id}]"
        
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
            
            # Aggregate tax by rate
            pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {
                    "$group": {
                        "_id": "$cart.lines.tax_rate",
                        "taxable_amount": {"$sum": "$cart.lines.subtotal"},
                        "tax_collected": {"$sum": "$cart.lines.tax_amount"},
                        "transaction_count": {"$sum": 1}
                    }
                },
                {"$sort": {"_id": 1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            # Format results
            tax_rates = []
            total_tax = 0.0
            total_taxable = 0.0
            
            for item in results:
                rate = float(item["_id"] or 0)
                taxable = float(item["taxable_amount"])
                tax = float(item["tax_collected"])
                
                total_tax += tax
                total_taxable += taxable
                
                tax_rates.append({
                    "tax_rate": round(rate, 2),
                    "taxable_amount": round(taxable, 2),
                    "tax_collected": round(tax, 2),
                    "transaction_count": int(item["transaction_count"])
                })
            
            # Get tax-exempt sales
            exempt_pipeline = [
                {"$match": match_query},
                {"$unwind": "$cart.lines"},
                {"$match": {"cart.lines.tax_rate": {"$eq": 0}}},
                {
                    "$group": {
                        "_id": None,
                        "exempt_amount": {"$sum": "$cart.lines.subtotal"}
                    }
                }
            ]
            
            exempt_result = list(collection.aggregate(exempt_pipeline))
            exempt_amount = float(exempt_result[0]["exempt_amount"]) if exempt_result else 0.0
            
            Log.info(f"{log_tag} Generated tax report for {len(tax_rates)} tax rates")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "tax_rates": tax_rates,
                "summary": {
                    "total_tax_collected": round(total_tax, 2),
                    "total_taxable_sales": round(total_taxable, 2),
                    "tax_exempt_sales": round(exempt_amount, 2),
                    "total_sales": round(total_taxable + exempt_amount, 2),
                    "effective_tax_rate": round((total_tax / total_taxable * 100) if total_taxable > 0 else 0, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_profit_loss_report(business_id, start_date, end_date, outlet_id=None):
        """
        Generate profit and loss statement.
        
        Args:
            business_id: Business ObjectId or string
            start_date: datetime - period start
            end_date: datetime - period end
            outlet_id: Optional outlet filter
            
        Returns:
            Dict with P&L data
        """
        log_tag = f"[financial_report_service.py][FinancialReportService][generate_profit_loss_report][{business_id}]"
        
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
            
            # Get revenue and cost data
            pipeline = [
                {"$match": match_query},
                {
                    "$group": {
                        "_id": None,
                        "gross_sales": {"$sum": "$cart.totals.subtotal"},
                        "discounts": {"$sum": "$cart.totals.total_discount"},
                        "net_sales": {"$sum": "$cart.totals.grand_total"},
                        "tax": {"$sum": "$cart.totals.total_tax"},
                        "cogs": {"$sum": "$cart.totals.total_cost"}  # Assuming cost is tracked
                    }
                }
            ]
            
            result = list(collection.aggregate(pipeline))
            
            if not result:
                return {
                    "period": {
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat()
                    },
                    "revenue": {},
                    "costs": {},
                    "profitability": {}
                }
            
            data = result[0]
            
            # Revenue calculations
            gross_sales = float(data.get("gross_sales", 0))
            discounts = float(data.get("discounts", 0))
            net_sales = float(data.get("net_sales", 0))
            tax = float(data.get("tax", 0))
            
            # Cost calculations
            cogs = float(data.get("cogs", 0))
            
            # TODO: Get operating expenses from expenses collection
            operating_expenses = 0.0  # Placeholder
            
            # Profit calculations
            gross_profit = net_sales - cogs
            operating_profit = gross_profit - operating_expenses
            net_profit = operating_profit  # Before interest and taxes
            
            # Margin calculations
            gross_margin = (gross_profit / net_sales * 100) if net_sales > 0 else 0
            operating_margin = (operating_profit / net_sales * 100) if net_sales > 0 else 0
            net_margin = (net_profit / net_sales * 100) if net_sales > 0 else 0
            
            Log.info(f"{log_tag} Generated P&L report")
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                },
                "revenue": {
                    "gross_sales": round(gross_sales, 2),
                    "discounts": round(discounts, 2),
                    "net_sales": round(net_sales, 2),
                    "tax_collected": round(tax, 2)
                },
                "costs": {
                    "cost_of_goods_sold": round(cogs, 2),
                    "operating_expenses": round(operating_expenses, 2),
                    "total_costs": round(cogs + operating_expenses, 2)
                },
                "profitability": {
                    "gross_profit": round(gross_profit, 2),
                    "gross_margin_percentage": round(gross_margin, 2),
                    "operating_profit": round(operating_profit, 2),
                    "operating_margin_percentage": round(operating_margin, 2),
                    "net_profit": round(net_profit, 2),
                    "net_margin_percentage": round(net_margin, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def generate_z_report(business_id, date, outlet_id, cashier_id=None):
        """
        Generate end-of-day Z-report (daily sales summary).
        
        Args:
            business_id: Business ObjectId or string
            date: datetime - specific date
            outlet_id: Outlet ObjectId or string
            cashier_id: Optional cashier filter
            
        Returns:
            Dict with Z-report data
        """
        log_tag = f"[financial_report_service.py][FinancialReportService][generate_z_report][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            # Get start and end of day
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            collection = db.get_collection(Sale.collection_name)
            
            # Build match query
            match_query = {
                "business_id": business_id,
                "outlet_id": outlet_id,
                "created_at": {
                    "$gte": start_of_day,
                    "$lte": end_of_day
                }
            }
            
            if cashier_id:
                match_query["cashier_id"] = ObjectId(cashier_id) if not isinstance(cashier_id, ObjectId) else cashier_id
            
            # Get completed sales
            completed_pipeline = [
                {"$match": {**match_query, "status": "Completed"}},
                {
                    "$group": {
                        "_id": None,
                        "count": {"$sum": 1},
                        "gross_sales": {"$sum": "$cart.totals.subtotal"},
                        "discounts": {"$sum": "$cart.totals.total_discount"},
                        "tax": {"$sum": "$cart.totals.total_tax"},
                        "net_sales": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            completed = list(collection.aggregate(completed_pipeline))
            completed_data = completed[0] if completed else {}
            
            # Get refunds
            refunds_pipeline = [
                {"$match": {**match_query, "status": {"$in": ["Refunded", "Partially_Refunded"]}}},
                {
                    "$group": {
                        "_id": None,
                        "count": {"$sum": 1},
                        "amount": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            refunds = list(collection.aggregate(refunds_pipeline))
            refunds_data = refunds[0] if refunds else {}
            
            # Get voids
            voids_pipeline = [
                {"$match": {**match_query, "status": "Voided"}},
                {
                    "$group": {
                        "_id": None,
                        "count": {"$sum": 1},
                        "amount": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            voids = list(collection.aggregate(voids_pipeline))
            voids_data = voids[0] if voids else {}
            
            # Get payment methods breakdown
            payment_pipeline = [
                {"$match": {**match_query, "status": "Completed"}},
                {
                    "$group": {
                        "_id": "$payment_method",
                        "count": {"$sum": 1},
                        "amount": {"$sum": "$cart.totals.grand_total"}
                    }
                }
            ]
            
            payments = list(collection.aggregate(payment_pipeline))
            payment_methods = [
                {
                    "method": item["_id"] or "Unknown",
                    "count": int(item["count"]),
                    "amount": round(float(item["amount"]), 2)
                }
                for item in payments
            ]
            
            # Calculate totals
            gross_sales = float(completed_data.get("gross_sales", 0))
            discounts = float(completed_data.get("discounts", 0))
            tax = float(completed_data.get("tax", 0))
            net_sales = float(completed_data.get("net_sales", 0))
            refunds_amount = float(refunds_data.get("amount", 0))
            voids_amount = float(voids_data.get("amount", 0))
            
            final_net = net_sales - refunds_amount
            
            Log.info(f"{log_tag} Generated Z-report for {date.date()}")
            
            return {
                "report_info": {
                    "report_type": "Z_REPORT",
                    "date": date.date().isoformat(),
                    "outlet_id": str(outlet_id),
                    "cashier_id": str(cashier_id) if cashier_id else None,
                    "generated_at": datetime.utcnow().isoformat()
                },
                "sales_summary": {
                    "transaction_count": int(completed_data.get("count", 0)),
                    "gross_sales": round(gross_sales, 2),
                    "total_discounts": round(discounts, 2),
                    "total_tax": round(tax, 2),
                    "net_sales": round(net_sales, 2),
                    "average_transaction": round(net_sales / completed_data.get("count", 1), 2) if completed_data.get("count", 0) > 0 else 0
                },
                "adjustments": {
                    "refunds_count": int(refunds_data.get("count", 0)),
                    "refunds_amount": round(refunds_amount, 2),
                    "voids_count": int(voids_data.get("count", 0)),
                    "voids_amount": round(voids_amount, 2)
                },
                "payment_methods": payment_methods,
                "final_totals": {
                    "total_transactions": int(completed_data.get("count", 0)) + int(refunds_data.get("count", 0)),
                    "final_net_sales": round(final_net, 2)
                }
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None