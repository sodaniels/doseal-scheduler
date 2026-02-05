# app/resources/social/schwriter_resource.py

from __future__ import annotations

from typing import Any, Dict, List

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from marshmallow import ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ...utils.helpers import make_log_tag
from ..doseal.admin.admin_business_resource import token_required

from ...schemas.social.schwriter_schema import SchWriterRequestSchema
from ...services.social.llm.schwriter_service import SchWriterService, SchWriterRequest
from ...schemas.social.scheduled_posts_schema import PLATFORM_RULES


blp_schwriter = Blueprint("schwriter", __name__, description="SchWriter AI enhancements")


def _as_platform_list(p) -> List[str]:
    if isinstance(p, str):
        return [(p or "").lower().strip()] if (p or "").strip() else []
    if isinstance(p, list):
        return [(x or "").lower().strip() for x in p if isinstance(x, str) and x.strip()]
    return []


@blp_schwriter.route("/social/ai/schwriter/enhance", methods=["POST"])
class SchWriterEnhanceResource(MethodView):
    """
    ✅ platform can be:
      - "facebook"
      - ["facebook","instagram","linkedin"]
    """

    @token_required
    @blp_schwriter.arguments(SchWriterRequestSchema)
    def post(self, payload):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        account_type = user_info.get("account_type")
        business_id = str(user_info.get("business_id"))

        log_tag = make_log_tag(
            "schwriter_resource.py",
            "SchWriterEnhanceResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            business_id,
            business_id,
        )

        platforms = _as_platform_list(payload.get("platform"))
        action = (payload.get("action") or "full").lower().strip()
        content = payload.get("content") or {}
        brand = payload.get("brand") or {}
        preferences = payload.get("preferences") or {}

        if not platforms:
            return jsonify({
                "success": False,
                "message": "platform must be a string or array of strings",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        results: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}

        for p in platforms:
            try:
                r = SchWriterService.enhance(SchWriterRequest(
                    platform=p,
                    action=action,
                    content=content,
                    brand=brand,
                    preferences=preferences,
                    platform_rules=PLATFORM_RULES.get(p, {}),
                ))
                results.append(r)
            except Exception as e:
                Log.info(f"{log_tag} schwriter failed platform={p}: {e}")
                errors[p] = str(e)

        return jsonify({
            "success": True,
            "message": "ok",
            "data": {
                "results": results,
                "errors": errors or None,
            }
        }), HTTP_STATUS_CODES["OK"]