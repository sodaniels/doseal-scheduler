from flask.views import MethodView
from flask import request, jsonify, g
from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ...models.social.social_account import SocialAccount
from ...utils.logger import Log
from ..doseal.admin.admin_business_resource import token_required
from build.lib.app.utils.json_response import prepared_response
from ...utils.helpers import make_log_tag
from flask_smorest import Blueprint

blp_social_posts = Blueprint("social_posts", __name__)

@blp_social_posts.route("/social/accounts", methods=["GET"])
class SocialPostsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_business_id = str(user.get("business_id") or "")
        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")

        if not auth_business_id or not auth_user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        body = request.get_json(silent=True) or {}

        # Optional: allow SYSTEM_OWNER / SUPER_ADMIN to act on another business
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = str(form_business_id)
        else:
            target_business_id = auth_business_id

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
            
        log_tag = make_log_tag(
            "social_posts_resource.py",
            "SocialPostsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        try:
            # 1) Load ALL social accounts for this business
            accounts = SocialAccount.get_all_by_business_id(target_business_id)

            if not accounts:
                Log.info(f"{log_tag} No connected social accounts for this business.")
                return prepared_response(False, "BAD_REQUEST", f"No connected social accounts for this business.")
            
            # 2) Optional filter (if your UI passes platform="facebook"/"instagram"/...)
            platform = (body.get("platform") or "").strip().lower()
            if platform:
                accounts = [a for a in accounts if (a.get("platform") or "").lower() == platform]

            if not accounts:
                Log.info(f"{log_tag} No connected social accounts match your filter.")
                return prepared_response(False, "BAD_REQUEST", f"No connected social accounts match your filter.")

            # ✅ Now you have all accounts in `accounts`
            # You can either:
            # - return them
            # - or create/publish posts against them

            safe_accounts = []
            for a in accounts:
                safe_accounts.append({
                    "id": a.get("_id"),
                    "platform": a.get("platform"),
                    "destination_id": a.get("destination_id"),
                    "destination_type": a.get("destination_type"),
                    "destination_name": a.get("destination_name"),
                    "platform_username": a.get("platform_username"),
                    "created_at": a.get("created_at"),
                })

            return jsonify({
                "success": True,
                "message": "Social accounts loaded successfully",
                "data": {
                    "business_id": target_business_id,
                    "accounts": safe_accounts
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to load social accounts",
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]