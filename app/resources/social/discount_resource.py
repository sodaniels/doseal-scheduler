# resources/admin/discount_resource.py

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ..doseal.admin.admin_business_resource import token_required
from ...models.social.discount_model import Discount
from ...models.admin.package_model import Package
from ...schemas.social.discount_schema import (
    DiscountCreateSchema, DiscountUpdateSchema,
    DiscountQuerySchema, DiscountApplySchema,
)
from ...utils.json_response import prepared_response
from ...utils.helpers import (
    _resolve_business_id, _require_system_owner
)
from ...utils.logger import Log
from ...utils.error_handlers import _rethrow_permission_or_500

blp_admin_discount = Blueprint("discounts", __name__, description="Discount code management and validation")


# ════════════════════════════ CREATE DISCOUNT ════════════════════════════

@blp_admin_discount.route("/admin/discount", methods=["POST"])
class DiscountCreateResource(MethodView):
    @token_required
    @blp_admin_discount.arguments(DiscountCreateSchema, location="json")
    @blp_admin_discount.response(201)
    @blp_admin_discount.doc(summary="Create a discount code (SYSTEM_OWNER only)", security=[{"Bearer": []}])
    def post(self, json_data):
        auth_check = _require_system_owner()
        if auth_check:
            return auth_check

        user_info = g.get("current_user", {}) or {}

        try:
            # Check for duplicate code
            existing = Discount.get_by_code(json_data["code"])
            if existing:
                return prepared_response(False, "CONFLICT", f"Discount code '{json_data['code'].upper()}' already exists.")

            # Validate percentage <= 100
            if json_data["discount_type"] == "percentage" and json_data["value"] > 100:
                return prepared_response(False, "BAD_REQUEST", "Percentage discount cannot exceed 100%.")

            # Build creator name
            creator_name = None
            fn = user_info.get("first_name") or ""
            ln = user_info.get("last_name") or ""
            if fn and len(fn) > 30:
                try:
                    from ...utils.crypt import decrypt_data
                    fn = decrypt_data(fn) or ""
                except Exception:
                    fn = ""
            if ln and len(ln) > 30:
                try:
                    from ...utils.crypt import decrypt_data
                    ln = decrypt_data(ln) or ""
                except Exception:
                    ln = ""
            creator_name = f"{fn} {ln}".strip() or None

            json_data["created_by_name"] = creator_name
            json_data["user_id"] = user_info.get("user_id")
            json_data["user__id"] = str(user_info.get("_id"))

            discount = Discount(**json_data)
            discount_id = discount.save(processing_callback=True)

            if not discount_id:
                return prepared_response(False, "BAD_REQUEST", "Failed to create discount code.")

            created = Discount.get_by_id(discount_id)
            Log.info(f"[DiscountCreate] created: {discount_id} code={json_data['code'].upper()}")

            return prepared_response(True, "CREATED", "Discount code created.", data=created)

        except Exception as e:
            Log.error(f"[DiscountCreate] error: {e}")
            return _rethrow_permission_or_500(e)


# ════════════════════════════ LIST DISCOUNTS ════════════════════════════

@blp_admin_discount.route("/admin/discounts", methods=["GET"])
class DiscountListResource(MethodView):
    @token_required
    @blp_admin_discount.response(200)
    @blp_admin_discount.doc(summary="List all discount codes (SYSTEM_OWNER only)", security=[{"Bearer": []}])
    def get(self):
        auth_check = _require_system_owner()
        if auth_check:
            return auth_check

        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        status = request.args.get("status")

        result = Discount.get_all(status=status, page=page, per_page=per_page)
        return prepared_response(True, "OK", f"{result['total_count']} discount(s).", data=result)


# ════════════════════════════ GET SINGLE DISCOUNT ════════════════════════════

@blp_admin_discount.route("/admin/discount/detail", methods=["GET"])
class DiscountDetailResource(MethodView):
    @token_required
    @blp_admin_discount.arguments(DiscountQuerySchema, location="query")
    @blp_admin_discount.response(200)
    @blp_admin_discount.doc(summary="Get a single discount code with stats (SYSTEM_OWNER only)", security=[{"Bearer": []}])
    def get(self, qd):
        auth_check = _require_system_owner()
        if auth_check:
            return auth_check

        discount = Discount.get_by_id(qd["discount_id"])
        if not discount:
            return prepared_response(False, "NOT_FOUND", "Discount code not found.")

        stats = Discount.get_redemption_stats(qd["discount_id"])

        return prepared_response(True, "OK", "Discount details.", data={
            "discount": discount,
            "stats": stats,
        })


# ════════════════════════════ UPDATE DISCOUNT ════════════════════════════

@blp_admin_discount.route("/admin/discount", methods=["PATCH"])
class DiscountUpdateResource(MethodView):
    @token_required
    @blp_admin_discount.arguments(DiscountUpdateSchema, location="json")
    @blp_admin_discount.response(200)
    @blp_admin_discount.doc(summary="Update a discount code (SYSTEM_OWNER only)", security=[{"Bearer": []}])
    def patch(self, json_data):
        auth_check = _require_system_owner()
        if auth_check:
            return auth_check

        discount_id = json_data.pop("discount_id")

        existing = Discount.get_by_id(discount_id)
        if not existing:
            return prepared_response(False, "NOT_FOUND", "Discount code not found.")

        # Validate percentage
        dtype = json_data.get("discount_type", existing.get("discount_type"))
        value = json_data.get("value", existing.get("value"))
        if dtype == "percentage" and value and value > 100:
            return prepared_response(False, "BAD_REQUEST", "Percentage discount cannot exceed 100%.")

        # Check for duplicate if code is changing
        if "code" in json_data and json_data["code"]:
            new_code = json_data["code"].strip().upper()
            if new_code != (existing.get("code") or "").upper():
                dupe = Discount.get_by_code(new_code)
                if dupe:
                    return prepared_response(False, "CONFLICT", f"Code '{new_code}' already exists.")

        ok = Discount.update_discount(discount_id, **json_data)
        if ok:
            updated = Discount.get_by_id(discount_id)
            return prepared_response(True, "OK", "Discount updated.", data=updated)
        return prepared_response(False, "BAD_REQUEST", "No changes applied.")


# ════════════════════════════ DELETE / DEACTIVATE ════════════════════════════

@blp_admin_discount.route("/admin/discount/deactivate", methods=["POST"])
class DiscountDeactivateResource(MethodView):
    @token_required
    @blp_admin_discount.arguments(DiscountQuerySchema, location="json")
    @blp_admin_discount.response(200)
    @blp_admin_discount.doc(summary="Deactivate a discount code (SYSTEM_OWNER only)", security=[{"Bearer": []}])
    def post(self, json_data):
        auth_check = _require_system_owner()
        if auth_check:
            return auth_check

        existing = Discount.get_by_id(json_data["discount_id"])
        if not existing:
            return prepared_response(False, "NOT_FOUND", "Discount code not found.")

        ok = Discount.deactivate(json_data["discount_id"])
        if ok:
            return prepared_response(True, "OK", "Discount code deactivated.")
        return prepared_response(False, "BAD_REQUEST", "Failed to deactivate.")


# ════════════════════════════ APPLY / VALIDATE CODE (USER-FACING) ════════════════════════════

@blp_admin_discount.route("/admin/discount/apply", methods=["POST"])
class DiscountApplyResource(MethodView):
    @token_required
    @blp_admin_discount.arguments(DiscountApplySchema, location="json")
    @blp_admin_discount.response(200)
    @blp_admin_discount.doc(
        summary="Validate and preview a discount code during checkout",
        description="""
            Call this when the user enters a discount code on the checkout page.
            Returns the original price, discount amount, and final price.
            Does NOT redeem the code — redemption happens when payment succeeds.
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        user_info = g.get("current_user", {}) or {}
        target_business_id = _resolve_business_id(user_info)

        code = json_data["code"]
        package_id = json_data["package_id"]
        billing_period = json_data["billing_period"]

        try:
            # Get package
            package = Package.get_by_id(package_id)
            if not package:
                return prepared_response(False, "NOT_FOUND", "Package not found.")

            # Determine price
            if billing_period == "monthly":
                original_amount = package.get("price", 0)
            elif billing_period == "annually":
                original_amount = package.get("annual_price") or (package.get("price", 0) * 12)
            else:
                return prepared_response(False, "BAD_REQUEST", "Invalid billing period.")

            if not original_amount or original_amount <= 0:
                return prepared_response(False, "BAD_REQUEST", "Package has no price configured.")

            package_tier = package.get("tier", "Free")

            # Validate code
            is_valid, result = Discount.validate_code(
                code=code,
                business_id=target_business_id,
                package_tier=package_tier,
                billing_period=billing_period,
                original_amount=original_amount,
            )

            if not is_valid:
                return prepared_response(False, "BAD_REQUEST", result)

            return prepared_response(True, "OK", "Discount code applied.", data={
                "discount": result,
                "package_name": package.get("name"),
                "package_tier": package_tier,
                "billing_period": billing_period,
                "currency": package.get("currency", "USD"),
            })

        except Exception as e:
            Log.error(f"[DiscountApply] error: {e}")
            return _rethrow_permission_or_500(e)
