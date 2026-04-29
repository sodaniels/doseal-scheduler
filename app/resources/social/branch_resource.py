# resources/church/branch_resource.py

import time
from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from pymongo.errors import DuplicateKeyError

from ..doseal.admin.admin_business_resource import token_required
from ...decorators.subscription_decorator import require_active_subscription
from ...decorators.permission_decorator import require_permission
from ...models.social.branch_model import Branch
from ...schemas.social.branch_schema import (
    BranchCreateSchema,
    BranchUpdateSchema,
    BranchIdQuerySchema,
    BranchListQuerySchema,
    BranchSearchQuerySchema,
    BranchArchiveSchema,
)
from ...utils.error_handlers import _rethrow_permission_or_500
from ...utils.json_response import prepared_response
from ...utils.helpers import make_log_tag, _resolve_business_id
from ...utils.logger import Log
from ...constants.service_code import SYSTEM_USERS

from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.feature_gate import check_feature

blp_branch = Blueprint("branches", __name__, description="Church branch / campus / parish management")


# ═════════════════════════════════════════════════════════════════════
# SINGLE BRANCH CRUD  –  /branch  (POST, GET, PATCH, DELETE)
# ═════════════════════════════════════════════════════════════════════

@blp_branch.route("/branch", methods=["POST", "GET", "PATCH", "DELETE"])
class BranchResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "create")
    @blp_branch.arguments(BranchCreateSchema, location="json")
    @blp_branch.response(201, BranchCreateSchema)
    @blp_branch.doc(
        summary="Create a new branch / campus / parish",
        description="""
            Create a branch record under a church organisation.

            • SYSTEM_OWNER / SUPER_ADMIN may supply business_id to target any church.
            • BUSINESS_OWNER creates within own church.
            • Other roles: requires branch management permission.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        
        # ── 1. FEATURE GATE — is accounting enabled on this plan? ──
        check_feature(auth_business_id, "branch_management")

        log_tag = make_log_tag(
            "branch_resource.py",
            "BranchResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            
            Log.info(f"{log_tag} checking if branch name already exists")
            exists = Branch.check_multiple_item_exists(
                target_business_id,
                {"name": json_data.get("name")},
            )
            
            should_reserve_quota = False

            # ── 2. DUPLICATE CHECK ──
            if exists:
                Log.info(f"{log_tag} branch name already exists")
                return prepared_response(False, "CONFLICT", "A branch with this name already exists.")
            else:
                should_reserve_quota = True

            parent_branch_id = json_data.get("parent_branch_id")
            if parent_branch_id:
                parent = Branch.get_by_id(parent_branch_id, target_business_id, processing_callback=True)
                if not parent:
                    Log.info(f"{log_tag} parent branch not found: {parent_branch_id}")
                    return prepared_response(
                        False, "NOT_FOUND",
                        f"Parent branch '{parent_branch_id}' does not exist for this church.",
                    )

            pastor_id = json_data.get("pastor_id")
            if pastor_id:
                pastor = Member.get_by_id(pastor_id, target_business_id, processing_callback=True)
                if not pastor:
                    Log.info(f"{log_tag} pastor member not found: {pastor_id}")
                    return prepared_response(
                        False, "NOT_FOUND",
                        f"Pastor member '{pastor_id}' does not exist for this church.",
                    )

            if json_data.get("is_headquarters"):
                existing_hq = Branch.get_headquarters(target_business_id, processing_callback=True)
                if existing_hq:
                    Log.info(f"{log_tag} headquarters already exists: {existing_hq.get('_id')}")
                    return prepared_response(
                        False, "CONFLICT",
                        f"A headquarters branch already exists (ID: {existing_hq.get('_id')}). "
                        "Update the existing one or remove its headquarters flag first.",
                    )
                    
            # ── 3. QUOTA CHECK — max_branches limit ──
            enforcer = QuotaEnforcer(target_business_id)

            # ✅ Reserve quota ONLY if this is a brand new connection
            if should_reserve_quota:
                try:
                    enforcer.reserve(
                        counter_name="branches",
                        limit_key="max_branches",
                        qty=1,
                        period="billing",
                        reason="branches:create",
                    )
                except PlanLimitError as e:
                    Log.info(f"{log_tag} plan limit reached: {e.meta}")
                    return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)


            json_data["business_id"] = target_business_id
            json_data["user_id"] = user_info.get("user_id")
            json_data["user__id"] = auth_user__id

            Log.info(f"{log_tag} creating branch")
            start_time = time.time()

            branch = Branch(**json_data)
            branch_id = branch.save()

            duration = time.time() - start_time
            Log.info(f"{log_tag} branch.save() returned {branch_id} in {duration:.2f}s")

            if not branch_id:
                return prepared_response(False, "BAD_REQUEST", "Failed to create branch.")

            created = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
            return prepared_response(True, "CREATED", "Branch created successfully.", data=created)
        
        except DuplicateKeyError as e:
            # If it was a race and doc already exists, don't punish user
            Log.info(f"{log_tag} DuplicateKeyError (already exists): {e}")
            if should_reserve_quota:
                enforcer.release(counter_name="branches", qty=1, period="billing")
            return prepared_response(True, "OK", "Branch already created (no changes required).", data=created)

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An unexpected error occurred while creating the branch.")

    @token_required
    @require_active_subscription()
    @require_permission("branches", "read")
    @blp_branch.arguments(BranchIdQuerySchema, location="query")
    @blp_branch.response(200, BranchCreateSchema)
    @blp_branch.doc(
        summary="Retrieve a single branch by branch_id",
        security=[{"Bearer": []}],
    )
    def get(self, query_data):
        branch_id = query_data.get("branch_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, query_data.get("business_id"))

        log_tag = make_log_tag(
            "branch_resource.py", "BranchResource", "get",
            client_ip, auth_user__id, account_type,
            auth_business_id, target_business_id,
        )

        if not branch_id:
            return prepared_response(False, "BAD_REQUEST", "branch_id must be provided.")

        try:
            Log.info(f"{log_tag}[branch_id:{branch_id}] retrieving branch")
            start_time = time.time()
            branch = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
            duration = time.time() - start_time

            Log.info(f"{log_tag}[branch_id:{branch_id}] completed in {duration:.2f}s")

            if not branch:
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            member_count = Branch.get_member_count(branch_id, target_business_id, processing_callback=True)
            branch["member_count"] = member_count

            return prepared_response(True, "OK", "Branch retrieved successfully.", data=branch)

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An unexpected error occurred while retrieving the branch.")

    @token_required
    @require_active_subscription()
    @require_permission("branches", "update")
    @blp_branch.arguments(BranchUpdateSchema, location="json")
    @blp_branch.response(200, BranchUpdateSchema)
    @blp_branch.doc(
        summary="Update an existing branch (partial update)",
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        branch_id = item_data.get("branch_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, item_data.get("business_id"))

        log_tag = make_log_tag(
            "branch_resource.py", "BranchResource", "patch",
            client_ip, auth_user__id, account_type,
            auth_business_id, target_business_id,
        )

        if not branch_id:
            return prepared_response(False, "BAD_REQUEST", "branch_id must be provided.")

        try:
            existing = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            new_parent = item_data.get("parent_branch_id")
            if new_parent:
                if new_parent == branch_id:
                    return prepared_response(False, "BAD_REQUEST", "A branch cannot be its own parent.")

                parent = Branch.get_by_id(new_parent, target_business_id, processing_callback=True)
                if not parent:
                    return prepared_response(
                        False, "NOT_FOUND",
                        f"Parent branch '{new_parent}' does not exist for this church.",
                    )

            new_pastor = item_data.get("pastor_id")
            if new_pastor:
                pastor = Member.get_by_id(new_pastor, target_business_id, processing_callback=True)
                if not pastor:
                    return prepared_response(
                        False, "NOT_FOUND",
                        f"Pastor member '{new_pastor}' does not exist for this church.",
                    )

            if item_data.get("is_headquarters") and not existing.get("is_headquarters"):
                existing_hq = Branch.get_headquarters(target_business_id, processing_callback=True)
                if existing_hq and existing_hq.get("_id") != branch_id:
                    return prepared_response(
                        False, "CONFLICT",
                        f"Another branch is already set as headquarters (ID: {existing_hq.get('_id')}).",
                    )

            item_data.pop("branch_id", None)
            item_data.pop("business_id", None)

            Log.info(f"{log_tag}[branch_id:{branch_id}] updating branch")
            start_time = time.time()

            update_ok = Branch.update(branch_id, target_business_id, processing_callback=True, **item_data)
            duration = time.time() - start_time

            if update_ok:
                Log.info(f"{log_tag}[branch_id:{branch_id}] updated in {duration:.2f}s")
                updated = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
                return prepared_response(True, "OK", "Branch updated successfully.", data=updated)

            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update branch.")

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An unexpected error occurred while updating the branch.")

    @token_required
    @require_active_subscription()
    @require_permission("branches", "delete")
    @blp_branch.arguments(BranchIdQuerySchema, location="query")
    @blp_branch.response(200)
    @blp_branch.doc(
        summary="Permanently delete a branch",
        description="Hard-delete. Use /branch/archive for soft-delete. Will fail if members are still assigned to this branch.",
        security=[{"Bearer": []}],
    )
    def delete(self, query_data):
        branch_id = query_data.get("branch_id")
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, query_data.get("business_id"))

        log_tag = make_log_tag(
            "branch_resource.py", "BranchResource", "delete",
            client_ip, auth_user__id, account_type,
            auth_business_id, target_business_id,
        )

        if not branch_id:
            return prepared_response(False, "BAD_REQUEST", "branch_id must be provided.")

        try:
            existing = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            member_count = Branch.get_member_count(branch_id, target_business_id, processing_callback=True)
            if member_count > 0:
                Log.info(f"{log_tag} cannot delete: {member_count} members still assigned")
                return prepared_response(
                    False, "CONFLICT",
                    f"Cannot delete branch: {member_count} member(s) are still assigned. Transfer or remove them first.",
                )

            children = Branch.get_children(target_business_id, branch_id, processing_callback=True)
            if children:
                Log.info(f"{log_tag} cannot delete: {len(children)} child branches exist")
                return prepared_response(
                    False, "CONFLICT",
                    f"Cannot delete branch: {len(children)} child branch(es) exist. Reassign or delete them first.",
                )

            result = Branch.delete(branch_id, target_business_id)
            if not result:
                return prepared_response(False, "BAD_REQUEST", "Failed to delete branch.")

            Log.info(f"{log_tag}[branch_id:{branch_id}] branch deleted")
            return prepared_response(True, "OK", "Branch deleted successfully.")

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An unexpected error occurred while deleting the branch.")


# ═════════════════════════════════════════════════════════════════════
# LIST BRANCHES  –  /branches  (GET)
# ═════════════════════════════════════════════════════════════════════

@blp_branch.route("/branches", methods=["GET"])
class BranchListResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "read")
    @blp_branch.arguments(BranchListQuerySchema, location="query")
    @blp_branch.response(200)
    @blp_branch.doc(
        summary="List branches with filters and pagination",
        description="""
            Filters: status, branch_type, parent_branch_id, region, district.
        """,
        security=[{"Bearer": []}],
    )
    def get(self, query_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, query_data.get("business_id"))

        log_tag = make_log_tag(
            "branch_resource.py", "BranchListResource", "get",
            client_ip, auth_user__id, account_type,
            auth_business_id, target_business_id,
        )

        page = query_data.get("page", 1)
        per_page = query_data.get("per_page", 50)
        include_archived = query_data.get("include_archived", False)

        try:
            status = query_data.get("status")
            branch_type = query_data.get("branch_type")
            parent_branch_id = query_data.get("parent_branch_id")
            region = query_data.get("region")
            district = query_data.get("district")

            result = None

            if parent_branch_id:
                Log.info(f"{log_tag} filtering by parent_branch_id={parent_branch_id}")
                children = Branch.get_children(target_business_id, parent_branch_id, processing_callback=True)
                result = {
                    "branches": children,
                    "total_count": len(children),
                    "total_pages": 1,
                    "current_page": 1,
                    "per_page": len(children),
                }

            elif region:
                Log.info(f"{log_tag} filtering by region={region}")
                result = Branch.get_by_region(target_business_id, region, page, per_page, processing_callback=True)

            elif district:
                Log.info(f"{log_tag} filtering by district={district}")
                result = Branch.get_by_district(target_business_id, district, page, per_page, processing_callback=True)

            elif branch_type:
                Log.info(f"{log_tag} filtering by branch_type={branch_type}")
                result = Branch.get_by_type(target_business_id, branch_type, page, per_page, processing_callback=True)

            elif status:
                Log.info(f"{log_tag} filtering by status={status}")
                result = Branch.get_by_status(target_business_id, status, page, per_page, processing_callback=True)

            else:
                Log.info(f"{log_tag} listing all branches")
                result = Branch.get_all_by_business(target_business_id, page, per_page, include_archived, processing_callback=True)

            if not result or not result.get("branches"):
                return prepared_response(False, "NOT_FOUND", "No branches found.")

            return prepared_response(True, "OK", "Branches retrieved successfully.", data=result)

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An unexpected error occurred while retrieving branches.")


# ═════════════════════════════════════════════════════════════════════
# SEARCH BRANCHES  –  /branches/search  (GET)
# ═════════════════════════════════════════════════════════════════════

@blp_branch.route("/branches/search", methods=["GET"])
class BranchSearchResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "read")
    @blp_branch.arguments(BranchSearchQuerySchema, location="query")
    @blp_branch.response(200)
    @blp_branch.doc(
        summary="Search branches by name, code, or city",
        security=[{"Bearer": []}],
    )
    def get(self, query_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type")
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))

        target_business_id = _resolve_business_id(user_info, query_data.get("business_id"))

        log_tag = make_log_tag(
            "branch_resource.py", "BranchSearchResource", "get",
            client_ip, auth_user__id, account_type,
            auth_business_id, target_business_id,
        )

        search_term = query_data.get("search")
        page = query_data.get("page", 1)
        per_page = query_data.get("per_page", 50)

        try:
            Log.info(f"{log_tag} searching branches")
            result = Branch.search(target_business_id, search_term, page, per_page, processing_callback=True)

            if not result or not result.get("branches"):
                return prepared_response(False, "NOT_FOUND", "No matching branches found.")

            return prepared_response(True, "OK", "Search results retrieved.", data=result)

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred during search.")


# ═════════════════════════════════════════════════════════════════════
# BRANCH SUMMARY  –  /branches/summary  (GET)
# ═════════════════════════════════════════════════════════════════════

@blp_branch.route("/branches/summary", methods=["GET"])
class BranchSummaryResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "read")
    @blp_branch.response(200)
    @blp_branch.doc(
        summary="Get a summary of all branches (counts by type, status, region, district)",
        description="Useful for diocese/HQ dashboards.",
        security=[{"Bearer": []}],
    )
    def get(self):
        user_info = g.get("current_user", {}) or {}
        target_business_id = _resolve_business_id(user_info, request.args.get("business_id"))

        try:
            summary = Branch.get_summary(target_business_id, processing_callback=True)
            return prepared_response(True, "OK", "Branch summary retrieved.", data=summary)

        except Exception as e:
            Log.error(f"[BranchSummary] error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred while generating the branch summary.")


# ═════════════════════════════════════════════════════════════════════
# ARCHIVE / RESTORE  –  /branch/archive, /branch/restore  (POST)
# ═════════════════════════════════════════════════════════════════════

@blp_branch.route("/branch/archive", methods=["POST"])
class BranchArchiveResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "delete")
    @blp_branch.arguments(BranchArchiveSchema, location="json")
    @blp_branch.response(200)
    @blp_branch.doc(summary="Soft-delete (archive) a branch", security=[{"Bearer": []}])
    def post(self, json_data):
        user_info = g.get("current_user", {}) or {}
        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        branch_id = json_data.get("branch_id")

        log_tag = f"[BranchArchive][branch_id:{branch_id}]"

        try:
            member_count = Branch.get_member_count(branch_id, target_business_id, processing_callback=True)
            if member_count > 0:
                Log.info(f"{log_tag} cannot archive: {member_count} members still assigned")
                return prepared_response(
                    False, "CONFLICT",
                    f"Cannot archive branch: {member_count} member(s) are still assigned. Transfer or remove them first.",
                )

            success = Branch.archive(branch_id, target_business_id, processing_callback=True)
            if success:
                return prepared_response(True, "OK", "Branch archived successfully.")
            return prepared_response(False, "NOT_FOUND", "Branch not found or already archived.")

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred while archiving the branch.")


@blp_branch.route("/branch/restore", methods=["POST"])
class BranchRestoreResource(MethodView):

    @token_required
    @require_active_subscription()
    @require_permission("branches", "update")
    @blp_branch.arguments(BranchArchiveSchema, location="json")
    @blp_branch.response(200)
    @blp_branch.doc(summary="Restore an archived branch", security=[{"Bearer": []}])
    def post(self, json_data):
        user_info = g.get("current_user", {}) or {}
        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        branch_id = json_data.get("branch_id")

        try:
            success = Branch.restore(branch_id, target_business_id, processing_callback=True)
            if success:
                return prepared_response(True, "OK", "Branch restored successfully.")
            return prepared_response(False, "NOT_FOUND", "Branch not found or not archived.")

        except Exception as e:
            Log.error(f"[BranchRestore] error: {e}")
            return _rethrow_permission_or_500(e, "An error occurred while restoring the branch.")