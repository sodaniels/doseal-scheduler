# resources/reports/financial_reports_resource.py

from datetime import datetime, timedelta
from flask_smorest import Blueprint
from flask import request, g, jsonify
from flask.views import MethodView
from marshmallow import Schema, fields

from ..admin_business_resource import token_required
from .....utils.crypt import decrypt_data
from .....utils.helpers import make_log_tag
from .....utils.json_response import prepared_response
from .....utils.rate_limits import crud_read_limiter
from .....utils.logger import Log
from .....constants.service_code import (
    HTTP_STATUS_CODES,SYSTEM_USERS
)

from .....services.pos.reports.financial_report_service import FinancialReportService
from .....schemas.finance_report_schema import (
   FinancialReportBaseQuerySchema,
   CashFlowReportQuerySchema,
   ZReportQuerySchema,
   FinancialAnalyticsDashboardQuerySchema
)

blp_financial_reports = Blueprint("Finance Report",  __name__, description="Finance Report and analytics operations")

# ====================== PAYMENT METHODS REPORT ======================

@blp_financial_reports.route("/reports/financial/payment-methods")
class PaymentMethodsReportResource(MethodView):
    """Payment methods analysis report."""

    @token_required
    @crud_read_limiter(entity_name="financial_payment_methods_report")
    @blp_financial_reports.arguments(FinancialReportBaseQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate payment methods analysis report.

        • SYSTEM_OWNER / SUPER_ADMIN:
            - may submit business_id in the query to target any business
            - if omitted, defaults to their own business_id

        • Other roles:
            - always restricted to their own business_id.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = (
            FinancialReportService.account_type_enc
            if account_type_enc
            else None
        ) if hasattr(FinancialReportService, "decrypt_data") else (
            None if not account_type_enc else None
        )
        # If you already import decrypt_data globally, replace above with:

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")

        # Date range defaults – last 30 days
        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))

        # Role-aware business selection
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "PaymentMethodsReportResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating payment methods report "
                f"period={start_date.isoformat()}..{end_date.isoformat()} "
                f"outlet_id={outlet_id}"
            )

            report = FinancialReportService.generate_payment_methods_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate payment methods report",
                )

            return prepared_response(
                status=True,
                status_code="OK",
                message="Payment methods report generated successfully",
                data=report,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating payment methods report",
                errors=[str(e)],
            )


# ====================== CASH FLOW REPORT ======================

@blp_financial_reports.route("/reports/financial/cash-flow")
class CashFlowReportResource(MethodView):
    """Daily cash flow report."""

    @token_required
    @crud_read_limiter(entity_name="financial_cash_flow_report")
    @blp_financial_reports.arguments(CashFlowReportQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate daily cash flow report.

        • SYSTEM_OWNER / SUPER_ADMIN:
            - may submit business_id in the query to target any business
            - if omitted, defaults to their own business_id

        • Other roles:
            - always restricted to their own business_id.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")
        date = query_args.get("date") or datetime.utcnow()

        # Role-aware business selection
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "CashFlowReportResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating cash flow report date={date.date().isoformat()} "
                f"outlet_id={outlet_id}"
            )

            report = FinancialReportService.generate_cash_flow_report(
                business_id=business_id,
                date=date,
                outlet_id=outlet_id,
            )

            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate cash flow report",
                )

            return prepared_response(
                status=True,
                status_code="OK",
                message="Cash flow report generated successfully",
                data=report,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating cash flow report",
                errors=[str(e)],
            )


# ====================== TAX REPORT ======================

@blp_financial_reports.route("/reports/financial/tax")
class TaxReportResource(MethodView):
    """Tax collection report."""

    @token_required
    @crud_read_limiter(entity_name="financial_tax_report")
    @blp_financial_reports.arguments(FinancialReportBaseQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate tax collection report.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")

        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "TaxReportResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating tax report "
                f"period={start_date.isoformat()}..{end_date.isoformat()} "
                f"outlet_id={outlet_id}"
            )

            report = FinancialReportService.generate_tax_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate tax report",
                )

            return prepared_response(
                status=True,
                status_code="OK",
                message="Tax report generated successfully",
                data=report,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating tax report",
                errors=[str(e)],
            )


# ====================== PROFIT & LOSS REPORT ======================

@blp_financial_reports.route("/reports/financial/profit-loss")
class ProfitLossReportResource(MethodView):
    """Profit & Loss report."""

    @token_required
    @crud_read_limiter(entity_name="financial_profit_loss_report")
    @blp_financial_reports.arguments(FinancialReportBaseQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate profit and loss statement.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")

        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "ProfitLossReportResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating P&L report "
                f"period={start_date.isoformat()}..{end_date.isoformat()} "
                f"outlet_id={outlet_id}"
            )

            report = FinancialReportService.generate_profit_loss_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate profit and loss report",
                )

            return prepared_response(
                status=True,
                status_code="OK",
                message="Profit and loss report generated successfully",
                data=report,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating profit and loss report",
                errors=[str(e)],
            )


# ====================== Z REPORT (END OF DAY) ======================

@blp_financial_reports.route("/reports/financial/z-report")
class ZReportResource(MethodView):
    """End-of-day Z-report (daily sales summary)."""

    @token_required
    @crud_read_limiter(entity_name="financial_z_report")
    @blp_financial_reports.arguments(ZReportQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate end-of-day Z-report (daily sales summary).

        outlet_id is required.
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")
        cashier_id = query_args.get("cashier_id")
        date = query_args.get("date") or datetime.utcnow()

        if not outlet_id:
            return prepared_response(
                status=False,
                status_code="BAD_REQUEST",
                message="outlet_id must be provided.",
            )

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "ZReportResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating Z-report "
                f"date={date.date().isoformat()} outlet_id={outlet_id} cashier_id={cashier_id}"
            )

            report = FinancialReportService.generate_z_report(
                business_id=business_id,
                date=date,
                outlet_id=outlet_id,
                cashier_id=cashier_id,
            )

            if not report:
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate Z-report",
                )

            return prepared_response(
                status=True,
                status_code="OK",
                message="Z-report generated successfully",
                data=report,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating Z-report",
                errors=[str(e)],
            )


# ====================== COMBINED FINANCIAL ANALYTICS DASHBOARD ======================

@blp_financial_reports.route("/reports/financial/analytics")
class FinancialAnalyticsDashboard(MethodView):
    """Combined financial analytics dashboard endpoint."""

    @token_required
    @crud_read_limiter(entity_name="financial_analytics_dashboard")
    @blp_financial_reports.arguments(FinancialAnalyticsDashboardQuerySchema, location="query")
    @blp_financial_reports.response(HTTP_STATUS_CODES["OK"])
    def get(self, query_args):
        """
        Generate comprehensive financial analytics dashboard.

        Combines:
            - Profit & Loss
            - Payment Methods
            - Tax Report
            - Today Cash Flow
        """
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        query_business_id = query_args.get("business_id")
        outlet_id = query_args.get("outlet_id")

        end_date = query_args.get("end_date") or datetime.utcnow()
        start_date = query_args.get("start_date") or (end_date - timedelta(days=30))

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id

        log_tag = make_log_tag(
            "financial_reports_resource.py",
            "FinancialAnalyticsDashboard",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id,
        )

        try:
            Log.info(
                f"{log_tag} Generating financial analytics dashboard "
                f"period={start_date.isoformat()}..{end_date.isoformat()} outlet_id={outlet_id}"
            )

            pnl = FinancialReportService.generate_profit_loss_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            payment_methods = FinancialReportService.generate_payment_methods_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            tax = FinancialReportService.generate_tax_report(
                business_id=business_id,
                start_date=start_date,
                end_date=end_date,
                outlet_id=outlet_id,
            )

            today = datetime.utcnow()
            cash_flow_today = FinancialReportService.generate_cash_flow_report(
                business_id=business_id,
                date=today,
                outlet_id=outlet_id,
            )

            if not all([pnl, payment_methods, tax]):
                return prepared_response(
                    status=False,
                    status_code="REPORT_GENERATION_FAILED",
                    message="Failed to generate one or more financial dashboard components",
                )

            dashboard_data = {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                "profit_and_loss": pnl,
                "payment_methods": payment_methods,
                "tax": tax,
                "today_cash_flow": cash_flow_today,
            }

            return prepared_response(
                status=True,
                status_code="OK",
                message="Financial analytics dashboard generated successfully",
                data=dashboard_data,
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error generating financial analytics dashboard",
                errors=[str(e)],
            )