# app/resources/notifications/notification_settings_resource.py

from __future__ import annotations

from flask import g, jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ..doseal.admin.admin_business_resource import token_required

from ...models.notifications.notification_settings import NotificationSettings
from ...schemas.notifications.notification_settings_schema import (
    NotificationSettingsPatchSchema,
)

from ...services.notifications.notification_config import NOTIFICATION_CONFIG


blp_notifications = Blueprint("notifications", __name__)


def _auth_ctx():
    user = g.get("current_user") or {}
    business_id = str(user.get("business_id") or "")
    user__id = str(user.get("_id") or "")
    return user, business_id, user__id


@blp_notifications.route("/notifications/config", methods=["GET"])
class NotificationsConfigResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[notification_settings_resource.py][GET][{client_ip}]"
        Log.info(f"{log_tag} Listing available notifications")
        return jsonify({"success": True, "data": NOTIFICATION_CONFIG}), HTTP_STATUS_CODES["OK"]


@blp_notifications.route("/notifications/settings", methods=["GET"])
class NotificationSettingsGetResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[notification_settings_resource.py][GET][{client_ip}]"
        
        Log.info(f"{log_tag} request to notifications/settings")

        _, business_id, user__id = _auth_ctx()
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        try:
            doc = NotificationSettings.get_or_create_defaults(business_id=business_id, user__id=user__id)
            return jsonify({"success": True, "data": doc}), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_notifications.route("/notifications/settings", methods=["PUT"])
class NotificationSettingsPatchResource(MethodView):
    @token_required
    def put(self):
        client_ip = request.remote_addr
        log_tag = f"[notification_settings_resource.py][PUT][{client_ip}]"
        
        Log.info(f"{log_tag} request to notifications/settings")

        _, business_id, user__id = _auth_ctx()
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        body = request.get_json(silent=True) or {}

        try:
            patch = NotificationSettingsPatchSchema().load(body)
        except ValidationError as err:
            return jsonify({
                "success": False,
                "message": "Validation failed",
                "errors": err.messages,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            doc = NotificationSettings.patch_settings(
                business_id=business_id,
                user__id=user__id,
                patch=patch,
            )
            return jsonify({"success": True, "data": doc}), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]