# resources/reports_resource.py
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from bson import ObjectId
from datetime import datetime, timedelta


from ..admin_business_resource import token_required
from .....utils.rate_limits import crud_read_limiter
from .....schemas.report_schemas import (
    SalesReportQuerySchema, InventoryReportQuerySchema,
    TopCustomersQuerySchema, CustomerReportQuerySchema,
    CustomerPurchaseHistoryQuerySchema,  CustomerSegmentationQuerySchema,
    CustomerRetentionQuerySchema, NewVsReturningQuerySchema,
    OperationalReportQuerySchema, PerformanceReportQuerySchema,
    InventoryOptimizationReportQuerySchema
)
#services
from .....services.pos.reports.operational_report_service import OperationalReportService
from .....services.pos.sale.sales_report_service import SalesReportService
from .....services.pos.reports.inventory_report_service import InventoryReportService
from .....services.pos.reports.customer_report_service import CustomerReportService
from .....services.pos.reports.performance_analytics_service import PerformanceAnalyticsService
from .....services.pos.reports.inventory_optimization_service import InventoryOptimizationService

from .....utils.json_response import prepared_response
from .....constants.service_code import (
    HTTP_STATUS_CODES,SYSTEM_USERS
)
from .....utils.crypt import decrypt_data
from .....utils.helpers import make_log_tag
from .....utils.logger import Log


blp_reports = Blueprint("Reports",  __name__, description="Reporting and analytics operations")
blp_sales_reports = Blueprint("Sales Reports",  __name__, description="Sales Reporting and analytics operations")
blp_stock_reports = Blueprint("Stock/Inventory Reports",  __name__, description="Stock Reporting and analytics operations")
blp_customer_reports = Blueprint("Customer Reports",  __name__, description="Customer Reporting and analytics operations")
blp_operational = Blueprint("Operational Report",  __name__, description="Operational Report Management")
blp_performance = Blueprint("Performance Report",  __name__, description="Performance Report Management")
blp_inventory_optimisation = Blueprint("Inventory Optimisation Report",  __name__, description="Inventory Optimisation Report Management")

# ==================== SALES REPORTS ====================

@blp_sales_reports.route("/reports/sales/summary")
class SalesSummaryReport(MethodView):
    """Sales summary report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="sales_summary_report")
    @blp_sales_reports.arguments(SalesReportQuerySchema, location="query")
    @blp_sales_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate sales summary report."""
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
        
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        outlet_id = query_args.get("outlet_id")
        user_id = query_args.get("user_id")
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "SalesSummaryReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
            start_date=start_date,
            end_date=end_date,
        )
        
        try:
            if not start_date or not end_date:
                Log.error(f"{log_tag} Missing required dates")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="start_date and end_date are required"
                )
            
            Log.info(f"{log_tag} Generating sales summary report")
            
            report = SalesReportService.generate_sales_summary(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
                user_id=user_id
            )
            
            if not report:
                Log.error(f"{log_tag} Report generation failed")
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            Log.info(f"{log_tag} Report generated successfully")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sales summary report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


@blp_sales_reports.route("/reports/sales/by-product")
class SalesByProductReport(MethodView):
    """Sales by product report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="sales_by_product_report")
    @blp_sales_reports.arguments(SalesReportQuerySchema, location="query")
    @blp_sales_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate sales by product report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        outlet_id = query_args.get("outlet_id")
        limit = query_args.get("limit", 50)
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "SalesByProductReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
            start_date=start_date,
            end_date=end_date,
        )
        
        try:
            report = SalesReportService.generate_sales_by_product(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
                limit=limit
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sales by product report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


@blp_sales_reports.route("/reports/sales/by-cashier")
class SalesByCashierReport(MethodView):
    """Sales by cashier report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="sales_by_cashier_report")
    @blp_sales_reports.arguments(SalesReportQuerySchema, location="query")
    @blp_sales_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate sales by cashier report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        outlet_id = query_args.get("outlet_id")
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "SalesByCashierReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
            start_date=start_date,
            end_date=end_date,
        )
        
        try:
            report = SalesReportService.generate_sales_by_cashier(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sales by cashier report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


# ==================== INVENTORY REPORTS ====================

@blp_stock_reports.route("/reports/inventory/current")
class CurrentStockReport(MethodView):
    """Current stock report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="current_stock_report")
    @blp_stock_reports.arguments(InventoryReportQuerySchema, location="query")
    @blp_stock_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate current stock report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        include_zero_stock = query_args.get("include_zero_stock", False)
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "CurrentStockReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
        )
        
        try:
            if not outlet_id:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="outlet_id is required"
                )
            
            report = InventoryReportService.generate_current_stock_report(
                business_id=business_id,
                outlet_id=outlet_id,
                include_zero_stock=include_zero_stock
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Current stock report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


@blp_stock_reports.route("/reports/inventory/movements")
class StockMovementReport(MethodView):
    """Stock movement report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="stock_movement_report")
    @blp_stock_reports.arguments(InventoryReportQuerySchema, location="query")
    @blp_stock_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate stock movement report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "StockMovementReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
        )
        
        try:
            report = InventoryReportService.generate_stock_movement_report(
                business_id=business_id,
                outlet_id=outlet_id,
                start_date=start_date,
                end_date=end_date
            )
            
            if not report:
                Log.info(f"{log_tag} Failed to generate report")
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            Log.info(f"{log_tag} Stock movement report generated successfully")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock movement report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


@blp_stock_reports.route("/reports/inventory/valuation")
class StockValuationReport(MethodView):
    """Stock valuation report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="stock_valuation_report")
    @blp_stock_reports.arguments(InventoryReportQuerySchema, location="query")
    @blp_stock_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate stock valuation report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "StockValuationReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
        )
        
        try:
            report = InventoryReportService.generate_stock_valuation_report(
                business_id=business_id,
                outlet_id=outlet_id
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Stock valuation report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )


@blp_stock_reports.route("/reports/inventory/reorder")
class ReorderReport(MethodView):
    """Reorder report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="reorder_report")
    @blp_stock_reports.arguments(InventoryReportQuerySchema, location="query")
    @blp_stock_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """Generate reorder report."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "ReorderReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            outlet_id=outlet_id,
        )
        
        try:
            report = InventoryReportService.generate_reorder_report(
                business_id=business_id,
                outlet_id=outlet_id
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Reorder report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating report",
                errors=[str(e)]
            )

# ==================== CUSTOMER REPORT REPORTS ====================

@blp_customer_reports.route("/reports/customers/top")
class TopCustomersReport(MethodView):
    """Top customers by revenue report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="top_customers_report")
    @blp_customer_reports.arguments(TopCustomersQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate top customers by revenue report.
        
        Returns a ranked list of customers by total spending with detailed metrics.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        # Date range handling
        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=90))
        limit = query_args.get("limit", 50)
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "TopCustomersReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating top customers report for period {start_date} to {end_date}")
            
            report = CustomerReportService.generate_top_customers_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate top customers report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Top customers report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating top customers report",
                errors=[str(e)]
            )


@blp_customer_reports.route("/reports/customers/<string:customer_id>/purchase-history")
class CustomerPurchaseHistoryReport(MethodView):
    """Customer purchase history report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="customer_purchase_history_report")
    @blp_customer_reports.arguments(CustomerReportQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args, customer_id):
        """
        Generate detailed purchase history for a specific customer.
        
        Returns complete transaction history with items, amounts, and summary statistics.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
            
        
        # Optional date range
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        limit = query_args.get("limit", 100)
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "CustomerPurchaseHistoryReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
            customer_id=customer_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating purchase history for customer {customer_id}")
            
            report = CustomerReportService.generate_customer_purchase_history(
                business_id=business_id,
                customer_id=customer_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate customer purchase history. Customer may not exist."
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Customer purchase history generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating customer purchase history",
                errors=[str(e)]
            )

@blp_customer_reports.route("/reports/customers/segmentation")
class CustomerSegmentationReport(MethodView):
    """Customer segmentation analysis report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="customer_segmentation_report")
    @blp_customer_reports.arguments(CustomerSegmentationQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate customer segmentation analysis.
        
        Categorizes customers into segments (VIP, Regular, Occasional, One-Time)
        based on purchase behavior and lifetime value.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "CustomerSegmentationReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating customer segmentation report")
            
            report = CustomerReportService.generate_customer_segmentation_report(
                business_id=business_id
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate customer segmentation report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Customer segmentation report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating customer segmentation report",
                errors=[str(e)]
            )


@blp_customer_reports.route("/reports/customers/retention")
class CustomerRetentionReport(MethodView):
    """Customer retention and churn analysis report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="customer_retention_report")
    @blp_customer_reports.arguments(CustomerRetentionQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate customer retention and churn analysis.
        
        Analyzes customer activity patterns to identify active, at-risk, and churned customers.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        log_tag = make_log_tag(
            "customer_reports_resource.py",
            "CustomerRetentionReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating customer retention report")
            
            report = CustomerReportService.generate_customer_retention_report(
                business_id=business_id
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate customer retention report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Customer retention report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating customer retention report",
                errors=[str(e)]
            )


@blp_customer_reports.route("/reports/customers/new-vs-returning")
class NewVsReturningCustomersReport(MethodView):
    """New vs returning customers analysis report endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="new_vs_returning_report")
    @blp_customer_reports.arguments(NewVsReturningQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate new vs returning customers analysis.
        
        Compares revenue and customer counts between new and returning customers
        for a specified period.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        # Date range handling
        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))
        
        log_tag = make_log_tag(
            "customer_reports_resource.py",
            "NewVsReturningCustomersReport",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating new vs returning customers report for period {start_date} to {end_date}")
            
            report = CustomerReportService.generate_new_vs_returning_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date
            )
            
            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate new vs returning customers report"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="New vs returning customers report generated successfully",
                data=report
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating new vs returning customers report",
                errors=[str(e)]
            )

#===================== COMBINED ANALYTICS ENDPOINT =====================

@blp_customer_reports.route("/reports/customers/analytics")
class CustomerAnalyticsDashboard(MethodView):
    """Combined customer analytics dashboard endpoint."""
    
    @token_required
    @crud_read_limiter(entity_name="customer_analytics_dashboard")
    @blp_customer_reports.arguments(CustomerReportQuerySchema, location="query")
    @blp_customer_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate comprehensive customer analytics dashboard.
        
        Returns a combination of key customer metrics including segmentation,
        retention, and new vs returning analysis in a single response.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        # Date range for period-based reports
        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))
        
        log_tag = make_log_tag(
            "customer_reports_resource.py",
            "CustomerAnalyticsDashboard",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )
        
        try:
            Log.info(f"{log_tag} Generating customer analytics dashboard")
            
            # Generate all reports
            segmentation = CustomerReportService.generate_customer_segmentation_report(
                business_id=business_id
            )
            
            retention = CustomerReportService.generate_customer_retention_report(
                business_id=business_id
            )
            
            new_vs_returning = CustomerReportService.generate_new_vs_returning_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date
            )
            
            top_customers = CustomerReportService.generate_top_customers_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                limit=10  # Top 10 for dashboard
            )
            
            # Check if any report failed
            if not all([segmentation, retention, new_vs_returning, top_customers]):
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate one or more dashboard components"
                )
            
            dashboard_data = {
                "segmentation": segmentation,
                "retention": retention,
                "new_vs_returning": new_vs_returning,
                "top_customers": top_customers.get("customers", []),
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                }
            }
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Customer analytics dashboard generated successfully",
                data=dashboard_data
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating customer analytics dashboard",
                errors=[str(e)]
            )


# ==================== OPERATIONAL REPORTS ====================


@blp_operational.route("/operational/reports/operational", methods=["GET"])
class OperationalReportsResource(MethodView):
    """
    Operational reports endpoint (refunds, voids, ATV, cashier performance).

    report_type:
      - refunds_returns
      - voids
      - atv
      - cashier_performance
    """

    @token_required
    @crud_read_limiter("operational_reports")
    @blp_operational.arguments(OperationalReportQuerySchema, location="query")
    @blp_operational.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        # Auth fields
        auth_business_obj = user_info.get("business_id")
        auth_business_id = str(auth_business_obj) if auth_business_obj else None
        auth_user__id = str(user_info.get("_id")) if user_info.get("_id") else None

        account_type_enc = user_info.get("account_type")
        account_type = (
            decrypt_data(account_type_enc) if account_type_enc else None
        )

        # Query params
        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")
        report_type = query_args.get("report_type")
        start_date_str = query_args.get("start_date")
        end_date_str = query_args.get("end_date")

        # Role-aware business selection
        if account_type in (
            SYSTEM_USERS["SYSTEM_OWNER"],
            SYSTEM_USERS["SUPER_ADMIN"],
        ):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "OperationalReportsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
            report_type=report_type,
        )

        # Basic validation on business_id
        if not target_business_id:
            Log.error(f"{log_tag} BUSINESS_ID_MISSING")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="business_id could not be resolved for the current user.",
                errors=["business_id is required or must be resolvable from token"],
            )

        # validte dates
        try:
            start_date = datetime.fromisoformat(start_date_str)
            end_date = datetime.fromisoformat(end_date_str)
        except Exception:
            Log.error(f"{log_tag} INVALID_DATE_FORMAT")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="Invalid date format: use YYYY-MM-DD",
                errors=["Invalid start_date or end_date"],
            )

        if end_date < start_date:
            Log.error(f"{log_tag} INVALID_DATE_RANGE end_date < start_date")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="end_date must be greater than or equal to start_date.",
                errors=["Invalid date range"],
            )

        try:
            # Route to correct service method
            if report_type == "refunds_returns":
                report = OperationalReportService.generate_refunds_returns_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            elif report_type == "voids":
                report = OperationalReportService.generate_voids_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            elif report_type == "atv":
                report = OperationalReportService.generate_atv_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            elif report_type == "cashier_performance":
                report = OperationalReportService.generate_enhanced_cashier_performance(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            else:
                Log.error(f"{log_tag} UNKNOWN_REPORT_TYPE {report_type}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Unknown report_type '{report_type}'.",
                    errors=["Invalid report_type"],
                )

            if report is None:
                Log.info(f"{log_tag} NO_DATA_FOR_PERIOD")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No data found for the specified period and filters.",
                )

            Log.info(f"{log_tag} REPORT_GENERATED")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Operational report generated successfully.",
                data={
                    "report_type": report_type,
                    "report": report,
                },
            )

        except Exception as e:
            Log.error(f"{log_tag} INTERNAL_ERROR {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while generating the operational report.",
                errors=[str(e)],
            )

# ==================== OPERATIONAL REPORTS ====================

@blp_performance.route("/performance/reports/performance", methods=["GET"])
class PerformanceReportsResource(MethodView):
    """Generate performance reports for business analytics."""

    @token_required
    @crud_read_limiter("performance_report")
    @blp_performance.arguments(PerformanceReportQuerySchema, location="query")
    @blp_performance.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate outlet performance comparison or time-based analytics.
        
        Query Options:
        - report_type: "outlet", "time", "category", "discount", "affinity"
        - start_date, end_date (ISO-8601: YYYY-MM-DD)
        - outlet_id (optional)
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        account_type = user_info.get("account_type")
        account_type = account_type if account_type else "Unknown"
        token_business_id = str(user_info.get("business_id"))
        user_id = str(user_info.get("user_id"))
        user__id = str(user_info.get("_id"))

        # Args
        start_date = query_args.get("start_date")
        end_date = query_args.get("end_date")
        outlet_id = query_args.get("outlet_id")
        report_type = query_args.get("report_type")

        # Role-aware business resolution
        requested_business_id = query_args.get("business_id")
        business_id = (
            requested_business_id
            if account_type in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"]]
            else token_business_id
        )

        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "PerformanceReportsResource",
            "get",
            client_ip,
            user_id,
            account_type,
            token_business_id,
            business_id,
        )

        # Validate dates
        try:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
        except Exception:
            Log.error(f"{log_tag} INVALID_DATE_FORMAT")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="Invalid date format: use YYYY-MM-DD",
                errors=["Invalid start_date or end_date"],
            )

        if not report_type:
            Log.error(f"{log_tag} REPORT_TYPE_REQUIRED")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="report_type is required",
                errors=["report_type is required"],
            )

        Log.info(f"{log_tag} Running performance report type={report_type}")

        try:
            if report_type == "outlet":
                data = PerformanceAnalyticsService.generate_outlet_performance_report(
                    business_id, start, end
                )

            elif report_type == "time":
                data = PerformanceAnalyticsService.generate_time_based_analysis(
                    business_id, start, end, outlet_id
                )

            elif report_type == "category":
                data = PerformanceAnalyticsService.generate_category_performance(
                    business_id, start, end, outlet_id
                )

            elif report_type == "discount":
                data = PerformanceAnalyticsService.generate_discount_analysis(
                    business_id, start, end, outlet_id
                )

            elif report_type == "affinity":
                data = PerformanceAnalyticsService.generate_product_affinity_report(
                    business_id, start, end
                )

            else:
                Log.error(f"{log_tag} UNSUPPORTED_REPORT_TYPE")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Unsupported report_type value",
                    errors=["Supported: outlet, time, category, discount, affinity"],
                )

            if not data:
                Log.error(f"{log_tag} NO_DATA_FOUND")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No performance data found for period",
                )

            Log.info(f"{log_tag} Report generated successfully")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Performance report generated successfully",
                data=data,
            )

        except Exception as e:
            Log.error(f"{log_tag} INTERNAL_SERVER_ERROR: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating performance report",
                errors=[str(e)],
            )

# ==================== INVENTORY OPTIMISATION REPORTS ====================

@blp_inventory_optimisation.route("/reports/inventory-optimization", methods=["GET"])
class InventoryOptimizationReportsResource(MethodView):
    """
    Inventory optimization reports endpoint.

    report_type values:
      - dead_stock        → uses business_id + optional days_threshold (+ outlet_id)
      - stock_turnover    → uses business_id + start/end date (+ outlet_id)
      - stockout          → uses business_id + start/end date (+ outlet_id)
      - abc_analysis      → uses business_id + start/end date (+ outlet_id)
    """

    @token_required
    @crud_read_limiter("inventory_optimization_reports")
    @blp_inventory_optimisation.arguments(InventoryOptimizationReportQuerySchema, location="query")
    @blp_inventory_optimisation.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        # Auth context
        auth_business_obj = user_info.get("business_id")
        auth_business_id = str(auth_business_obj) if auth_business_obj else None
        auth_user__id = str(user_info.get("_id")) if user_info.get("_id") else None

        account_type_enc = user_info.get("account_type")
        account_type = (
            decrypt_data(account_type_enc) if account_type_enc else None
        )

        # Query params
        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")
        report_type = query_args.get("report_type")

        start_date_str = query_args.get("start_date")
        end_date_str = query_args.get("end_date")
        days_threshold = query_args.get("days_threshold") or 60  # default 60

        # Role-aware business selection
        if account_type in (
            SYSTEM_USERS["SYSTEM_OWNER"],
            SYSTEM_USERS["SUPER_ADMIN"],
        ):
            target_business_id = query_business_id or auth_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "admin_reports_resource.py",
            "InventoryOptimizationReportsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
            report_type=report_type,
        )

        # Validate business_id
        if not target_business_id:
            Log.error(f"{log_tag} BUSINESS_ID_MISSING")
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="business_id could not be resolved for the current user.",
                errors=["business_id is required or must be resolvable from token"],
            )

        # For reports that require dates
        needs_dates = report_type in ("stock_turnover", "stockout", "abc_analysis")

        start_date = end_date = None
        if needs_dates:
            if not start_date_str or not end_date_str:
                Log.error(f"{log_tag} MISSING_DATES_FOR_REPORT")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="start_date and end_date are required for this report_type.",
                    errors=["start_date and end_date are mandatory for stock_turnover, stockout, and abc_analysis"],
                )
            
            try:
                start_date = datetime.fromisoformat(start_date_str)
                end_date = datetime.fromisoformat(end_date_str)
            except Exception:
                Log.error(f"{log_tag} INVALID_DATE_FORMAT")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Invalid date format: use YYYY-MM-DD",
                    errors=["Invalid start_date or end_date"],
                )

            if end_date < start_date:
                Log.error(f"{log_tag} INVALID_DATE_RANGE end_date < start_date")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="end_date must be greater than or equal to start_date.",
                    errors=["Invalid date range"],
                )

        try:
            # Route to correct service method
            if report_type == "dead_stock":
                report = InventoryOptimizationService.generate_dead_stock_report(
                    business_id=target_business_id,
                    days_threshold=int(days_threshold),
                    outlet_id=outlet_id,
                )
            elif report_type == "stock_turnover":
                report = InventoryOptimizationService.generate_stock_turnover_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            elif report_type == "stockout":
                report = InventoryOptimizationService.generate_stockout_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            elif report_type == "abc_analysis":
                report = InventoryOptimizationService.generate_abc_analysis_report(
                    business_id=target_business_id,
                    start_date=start_date,
                    end_date=end_date,
                    outlet_id=outlet_id,
                )
            else:
                Log.error(f"{log_tag} UNKNOWN_REPORT_TYPE {report_type}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Unknown report_type '{report_type}'.",
                    errors=["Invalid report_type"],
                )

            if report is None:
                Log.info(f"{log_tag} NO_DATA_FOR_REPORT")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No data found for the specified parameters.",
                )

            Log.info(f"{log_tag} REPORT_GENERATED")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Inventory optimization report generated successfully.",
                data={
                    "report_type": report_type,
                    "report": report,
                },
            )

        except Exception as e:
            Log.error(f"{log_tag} INTERNAL_ERROR {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred while generating the inventory optimization report.",
                errors=[str(e)],
            )





























