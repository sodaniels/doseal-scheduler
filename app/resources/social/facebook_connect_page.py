import json
import os
from flask import request, jsonify, g
from flask_smorest import Blueprint
from flask.views import MethodView
from flask import request, jsonify, g

from build.lib.app.utils.json_response import prepared_response
from ...utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)
from ...constants.service_code import (
    HTTP_STATUS_CODES,
)
from ...resources.doseal.admin.admin_business_resource import token_required
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...models.social.social_account import SocialAccount
from ...utils.logger import Log

blp_fb_connect = Blueprint("Facebook Connect", __name__, description="Connect a Facebook Page")

@blp_fb_connect.route("/social/facebook/connect-page", methods=["POST"])
class FacebookConnectPageResource(MethodView):
    @token_required
    def post(self):
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user__id = str(user_info.get("_id"))

        body = request.get_json() or {}
        user_access_token = body.get("user_access_token")
        page_id = body.get("page_id")

        if not user_access_token or not page_id:
            return jsonify({"success": False, "message": "user_access_token and page_id required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        pages = FacebookAdapter.list_pages(user_access_token)

        chosen = next((p for p in pages if p.get("id") == page_id), None)
        if not chosen:
            return jsonify({"success": False, "message": "Page not found for this user"}), HTTP_STATUS_CODES["NOT_FOUND"]

        # ✅ THIS is where upsert_destination is called
        SocialAccount.upsert_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=chosen["id"],
            destination_type="page",
            destination_name=chosen.get("name"),
            access_token_plain=chosen.get("access_token"),   # PAGE TOKEN
            meta={
                "category": chosen.get("category"),
                "tasks": chosen.get("tasks", [])
            }
        )

        return jsonify({
            "success": True,
            "message": "Facebook Page connected",
            "data": {
                "destination_id": chosen["id"],
                "destination_name": chosen.get("name"),
                "platform": "facebook",
                "destination_type": "page"
            }
        }), HTTP_STATUS_CODES["OK"]
        
@blp_fb_connect.route("/social/facebook/pages", methods=["GET"])
class FacebookPagesResource(MethodView):
    @token_required
    def get(self):
        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redis_key = f"fb_pages:{selection_key}"
        raw = get_redis(redis_key)
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        pages = json.loads(raw)

        # Return only what UI needs (no page access tokens)
        safe_pages = [{"page_id": p["id"], "name": p.get("name")} for p in pages]

        return jsonify({"success": True, "pages": safe_pages}), HTTP_STATUS_CODES["OK"]
    

@blp_fb_connect.route("/social/connect/facebook", methods=["GET"])
class ConnectFacebookResource(MethodView):
    @token_required
    def get(self):
        """
        Called after OAuth callback redirect:
          /connect/facebook?selection_key=...

        Returns list of pages WITHOUT access tokens.
        """
        client_ip = request.remote_addr
        log_tag = f"[connect_facebook.py][ConnectFacebookResource][GET][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return prepared_response(False, "BAD_REQUEST", "selection_key is required.")

        redis_key = f"fb_pages:{selection_key}"

        try:
            raw = get_redis(redis_key)
            if not raw:
                Log.info(f"{log_tag} selection_key expired or not found: {selection_key}")
                return prepared_response(False, "BAD_REQUEST", "Selection expired. Please reconnect Facebook.")

            pages = json.loads(raw)

            # IMPORTANT: return SAFE fields only
            safe_pages = []
            for p in pages:
                safe_pages.append({
                    "page_id": p.get("id"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                })

            Log.info(f"{log_tag} returning {len(safe_pages)} pages")
            return jsonify({
                "success": True,
                "message": "Facebook pages fetched",
                "data": {
                    "selection_key": selection_key,
                    "pages": safe_pages
                }
            }), 200

        except Exception as e:
            Log.error(f"{log_tag} error: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Could not load facebook pages.")