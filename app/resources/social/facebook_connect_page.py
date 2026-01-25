from flask_smorest import Blueprint
from flask.views import MethodView
from flask import request, jsonify, g

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
            return jsonify({"success": False, "message": "user_access_token and page_id required"}), 400

        pages = FacebookAdapter.list_pages(user_access_token)

        chosen = next((p for p in pages if p.get("id") == page_id), None)
        if not chosen:
            return jsonify({"success": False, "message": "Page not found for this user"}), 404

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
        }), 200