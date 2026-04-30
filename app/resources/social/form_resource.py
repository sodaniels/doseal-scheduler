# resources/social/form_resource.py

import time
from datetime import datetime
from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from pymongo.errors import PyMongoError

from ..doseal.admin.admin_business_resource import token_required
from ...decorators.subscription_decorator import require_active_subscription
from ...decorators.permission_decorator import require_permission
from ...models.social.form_model import Form, FormSubmission, StorageQuota
from ...models.social.branch_model import Branch
from ...schemas.social.form_schema import (
    FormCreateSchema, FormUpdateSchema, FormIdQuerySchema, FormSlugQuerySchema, FormListQuerySchema,
    FormSubmitSchema, SubmissionIdQuerySchema, SubmissionListQuerySchema,
    FormAnalyticsQuerySchema,
    StorageQuotaQuerySchema, StorageQuotaUpdateSchema,
    FileUploadQuerySchema,
)
from ...utils.error_handlers import _rethrow_permission_or_500
from ...utils.json_response import prepared_response
from ...utils.helpers import make_log_tag, _resolve_business_id
from ...utils.logger import Log
from ...constants.storage_addon_pricing import STORAGE_ADDON_PRICING

from pymongo.errors import DuplicateKeyError
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.feature_gate import check_feature

blp_form = Blueprint("forms", __name__, description="Custom forms, data collection, file uploads, and storage quotas")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB default



def _validate_branch(branch_id, target_business_id, log_tag=None):
    try:
        branch = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
        if not branch:
            if log_tag:
                Log.info(f"{log_tag} branch not found: {branch_id}")
            return None
        return branch
    except Exception as e:
        if log_tag:
            Log.error(f"{log_tag} branch validation error: {e}")
        return None



# ════════════════════════════ STORAGE QUOTA ════════════════════════════

@blp_form.route("/storage/quota", methods=["GET"])
class StorageQuotaResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("storage", "read")
    @blp_form.arguments(StorageQuotaQuerySchema, location="query")
    @blp_form.response(200)
    @blp_form.doc(summary="Get business storage quota and usage", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, qd.get("business_id"))

            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            quota = StorageQuota.get_or_create(target_business_id, processing_callback=True)
            if not quota:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to load storage quota.")
            return prepared_response(True, "OK", "Storage quota.", data=quota)

        except Exception as e:
            Log.error(f"[StorageQuotaGet] error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred.")


@blp_form.route("/storage/quota/upgrade", methods=["POST"])
class StorageQuotaUpgradeResource(MethodView):
    @token_required
    # @require_permission("storage", "read")
    @blp_form.arguments(StorageQuotaUpdateSchema, location="json")
    @blp_form.response(200)
    @blp_form.doc(summary="Upgrade/change storage package for a business", security=[{"Bearer": []}])
    def post(self, d):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, d.get("business_id"))

            if not _validate_branch(d["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            ok = StorageQuota.update_package(target_business_id, d["package"], processing_callback=True)
            if ok:
                quota = StorageQuota.get_or_create(target_business_id, processing_callback=True)
                return prepared_response(True, "OK", f"Package updated to '{d['package']}'.", data=quota)
            return prepared_response(False, "BAD_REQUEST", "Invalid package or failed to update.")

        except Exception as e:
            Log.error(f"[StorageQuotaUpgrade] error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred.")


@blp_form.route("/storage/quota/options", methods=["GET"])

class StorageQuotaOptionsResource(MethodView):

    @token_required
    @require_active_subscription(allow_read=True)
    # @require_permission("storage", "read")
    @blp_form.arguments(StorageQuotaQuerySchema, location="query")
    @blp_form.response(200)
    @blp_form.doc(summary="Get available storage addon options", security=[{"Bearer": []}])
    def get(self, qd):

        try:

            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, qd.get("business_id"))
            if not _validate_branch(qd.get("branch_id"), target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            quota = StorageQuota.get_or_create(target_business_id, processing_callback=True)

            if not quota:

                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to load storage quota.")
            current_total_gb = quota.get("total_limit_gb", 0)
            current_used_gb = quota.get("storage_used_gb", 0)
            is_unlimited = quota.get("is_unlimited", False)
            options = []
            for size_gb, pricing in STORAGE_ADDON_PRICING.items():

                monthly_price = pricing.get("monthly", 0)

                yearly_price = pricing.get("yearly", 0)

                options.append({

                    "addon_gb": size_gb,

                    "label": pricing.get("label", f"{size_gb} GB Addon"),

                    "description": pricing.get("description", f"Adds {size_gb} GB extra storage to your account."),

                    "pricing": {

                        "monthly": monthly_price,

                        "yearly": yearly_price,

                        "currency": "USD",

                    },

                    "projected_total_storage_gb": -1 if is_unlimited else round(current_total_gb + size_gb, 2),

                })

            data = {

                "current_quota": {

                    "storage_limit_gb": quota.get("storage_limit_gb", 0),

                    "addon_storage_gb": quota.get("addon_storage_gb", 0),

                    "total_limit_gb": current_total_gb,

                    "storage_used_gb": current_used_gb,

                    "storage_remaining_gb": quota.get("storage_remaining_gb", 0),

                    "usage_pct": quota.get("usage_pct", 0),

                    "is_unlimited": is_unlimited,

                },

                "available_addons": options,

            }

            return prepared_response(True, "OK", "Storage addon options retrieved.", data=data)

        except Exception as e:

            Log.error(f"[StorageQuotaOptionsResource][get] error: {e}")

            return _rethrow_permission_or_500(e, "An error occurred.")
