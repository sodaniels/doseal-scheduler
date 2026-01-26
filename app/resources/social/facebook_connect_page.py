import json
import requests
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

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _safe_json_load(raw, default=None):
    try:
        if raw is None:
            return default
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except Exception:
        return default
# -------------------------------------------------------------------

blp_fb_connect = Blueprint("Facebook Connect", __name__, description="Connect a Facebook Page")


# -------------------------------------------------------------------
# 3) LIST PAGES (GET) - for testing now, React later
# GET /social/facebook/pages?selection_key=...
# Returns safe page fields (no tokens)
# -------------------------------------------------------------------

@blp_fb_connect.route("/social/facebook/pages", methods=["GET"])
class FacebookPagesResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook.py][FacebookPagesResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"fb_pages:{selection_key}")
        
    
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        pages = doc.get("pages") or []

        # Ensure the logged-in user matches the owner stored in Redis
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        safe_pages = []
        for p in pages:
            safe_pages.append({
                "page_id": p.get("id"),
                "name": p.get("name"),
                "category": p.get("category"),
                "tasks": p.get("tasks", []),
            })

        return jsonify({"success": True, "data": {"pages": safe_pages}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# 4) CONNECT PAGE (POST) - saves page token to DB via SocialAccount
# POST /social/facebook/connect-page
# body: { "selection_key": "...", "page_id": "..." }
# -------------------------------------------------------------------
@blp_fb_connect.route("/social/facebook/connect-page", methods=["POST"])
class FacebookConnectPageResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook.py][FacebookConnectPageResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        page_id = body.get("page_id")

        if not selection_key or not page_id:
            return jsonify({
                "success": False,
                "message": "selection_key and page_id are required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"fb_pages:{selection_key}")
        if not raw:
            return jsonify({
                "success": False,
                "message": "Selection expired. Please reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        pages = doc.get("pages") or []

        # Ensure logged-in user matches owner stored in Redis
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({
                "success": False,
                "message": "Not allowed for this selection_key"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Find selected page
        selected = next((p for p in pages if str(p.get("id")) == str(page_id)), None)
        if not selected:
            return jsonify({
                "success": False,
                "message": "Invalid page_id for this selection_key"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        page_access_token = selected.get("access_token")
        if not page_access_token:
            return jsonify({
                "success": False,
                "message": "Page token not found. Reconnect and try again."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = owner.get("business_id")
        user__id = owner.get("user__id")

        try:
            ok = SocialAccount.upsert_destination(
                business_id=business_id,
                user__id=user__id,
                platform="facebook",

                destination_id=str(page_id),
                destination_type="page",
                destination_name=selected.get("name"),

                access_token_plain=page_access_token,
                refresh_token_plain=None,
                token_expires_at=None,

                scopes=["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
                platform_user_id=str(page_id),
                platform_username=selected.get("name"),
                meta={
                    "page_id": str(page_id),
                    "category": selected.get("category"),
                    "tasks": selected.get("tasks", []),
                },
            )

            if not ok:
                Log.info(f"{log_tag} SocialAccount.upsert_destination returned not acknowledged")
                return jsonify({
                    "success": False,
                    "message": "Failed to connect page"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert SocialAccount destination: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect page"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # One-time selection key after success
        try:
            remove_redis(f"fb_pages:{selection_key}")
        except Exception:
            pass

        return jsonify({
            "success": True,
            "message": "Facebook Page connected successfully",
            "data": {
                "platform": "facebook",
                "destination_type": "page",
                "destination_id": str(page_id),
                "destination_name": selected.get("name"),
            }
        }), HTTP_STATUS_CODES["OK"]

# -------------------------------------------------------------------


@staticmethod
def publish_page_photo(page_id: str, page_access_token: str, image_url: str, caption: str = "") -> dict:
    url = f"{FacebookAdapter.GRAPH_BASE}/{page_id}/photos"
    payload = {
        "url": image_url,
        "caption": caption or "",
        "access_token": page_access_token,
        "published": "true",
    }
    resp = requests.post(url, data=payload, timeout=30)
    data = resp.json()
    if resp.status_code != HTTP_STATUS_CODES["OK"]:
        raise Exception(f"Facebook photo publish failed: {data}")
    return data