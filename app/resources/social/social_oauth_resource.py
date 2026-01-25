# app/resources/social/social_oauth_resource.py
import secrets
from flask import request, g
from flask.views import MethodView
from flask_smorest import Blueprint
from ...utils.json_response import prepared_response
from ...utils.logger import Log
from ...services.social.registry import get_publisher
# from ...models.social_connected_account import SocialConnectedAccount
from ...extensions.db import db
from bson.objectid import ObjectId

from ...resources.doseal.admin.admin_business_resource import token_required

blp_social_oauth = Blueprint("Social OAuth", __name__, description="Social OAuth")

@blp_social_oauth.route("/social/oauth/<platform>/start", methods=["GET"])
class SocialOAuthStart(MethodView):
    @token_required
    def get(self, platform):
        user = g.get("current_user", {})
        business_id = str(user.get("business_id"))
        user__id = str(user.get("_id"))
        client_ip = request.remote_addr

        try:
            publisher = get_publisher(platform)

            # store state in DB or redis to validate callback
            state = secrets.token_urlsafe(24)

            # Option A: store state in redis with expiry 10 mins (recommended)
            # redis.setex(f"oauth_state:{state}", 600, f"{business_id}:{user__id}:{platform}")

            auth_url = publisher.authorize_url(state=state)

            Log.info(f"[social_oauth_start][{client_ip}] platform={platform} state created")
            return {
                "success": True,
                "data": {"auth_url": auth_url, "state": state}
            }, 200

        except Exception as e:
            Log.error(f"[social_oauth_start] error={str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to start OAuth.")


@blp_social_oauth.route("/social/oauth/<platform>/callback", methods=["GET"])
class SocialOAuthCallback(MethodView):
    def get(self, platform):
        """
        This endpoint is called by the platform redirect.
        You will pass your frontend redirect URL to show "connected successfully".
        """
        client_ip = request.remote_addr
        code = request.args.get("code")
        state = request.args.get("state")

        if not code or not state:
            return prepared_response(False, "BAD_REQUEST", "Missing code/state")

        try:
            publisher = get_publisher(platform)

            # Validate state (recommended: read from redis)
            # raw = redis.get(f"oauth_state:{state}")
            # if not raw: return prepared_response(False,"BAD_REQUEST","Invalid/expired state")
            # business_id,user__id,platform_from_state = raw.decode().split(":")
            # if platform_from_state != platform: ...

            # If you can't do redis validation immediately:
            # include business_id & user__id encoded inside state (signed JWT) (recommended)
            # For now we assume you redirect with ?business_id=&user__id= from your UI
            business_id = request.args.get("business_id")
            user__id = request.args.get("user__id")

            token_payload = publisher.exchange_code(code=code)

            access_token = token_payload.get("access_token")
            refresh_token = token_payload.get("refresh_token")
            expires_at = token_payload.get("expires_at")
            scopes = token_payload.get("scopes", [])

            destinations = publisher.list_destinations(access_token)

            connected = SocialConnectedAccount(
                business_id=business_id,
                user__id=user__id,
                platform=platform,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scopes=scopes,
                destinations=destinations,
                status=SocialConnectedAccount.STATUS_ACTIVE,
            )
            connected_id = connected.save(processing_callback=True)

            Log.info(f"[social_oauth_callback][{client_ip}] connected_id={connected_id} platform={platform}")

            return {
                "success": True,
                "message": "Account connected successfully",
                "data": {"connected_account_id": connected_id}
            }, 200

        except Exception as e:
            Log.error(f"[social_oauth_callback][{client_ip}] error={str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "OAuth callback failed.")