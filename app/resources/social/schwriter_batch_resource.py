# app/resources/social/schwriter_batch_resource.py

from __future__ import annotations

from typing import Any, Dict, List

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate, ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ...utils.helpers import make_log_tag
from ..doseal.admin.admin_business_resource import token_required

from ...services.social.llm.schwriter_service import SchWriterService, SchWriterRequest
from ...schemas.social.scheduled_posts_schema import PLATFORM_RULES


blp_schwriter_batch = Blueprint("schwriter_batch", __name__, description="SchWriter AI batch enhancements")


class SchWriterBatchSchema(Schema):
    platforms = fields.List(fields.Str(), required=True)
    action = fields.Str(
        required=False,
        load_default="full",
        validate=validate.OneOf([
            "fix_grammar",
            "optimize_length",
            "adjust_tone",
            "inspire_engagement",
            "full",
        ])
    )
    content = fields.Dict(required=True)
    brand = fields.Dict(required=False, allow_none=True)
    preferences = fields.Dict(required=False, allow_none=True)


@blp_schwriter_batch.route("/social/ai/schwriter/enhance/batch", methods=["POST"])
class SchWriterEnhanceBatchResource(MethodView):
    """
    Batch per-platform results (like OwlyWriter panel but for multiple platforms).

    Request:
      {
        "platforms": ["facebook", "instagram", "linkedin"],
        "action": "full",
        "content": {"text":"...", "link":"...", "media":[...]},
        "brand": {...},
        "preferences": {...}
      }

    Response:
      data = {
        "results": [
          {"platform":"facebook", ...},
          {"platform":"instagram", ...},
        ]
      }
    """

    @token_required
    @blp_schwriter_batch.arguments(SchWriterBatchSchema)
    def post(self, payload):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        account_type = user_info.get("account_type")
        business_id = str(user_info.get("business_id"))

        log_tag = make_log_tag(
            "schwriter_batch_resource.py",
            "SchWriterEnhanceBatchResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            business_id,
            business_id,
        )

        platforms = [(p or "").lower().strip() for p in (payload.get("platforms") or []) if p]
        action = (payload.get("action") or "full").lower().strip()
        content = payload.get("content") or {}
        brand = payload.get("brand") or {}
        preferences = payload.get("preferences") or {}

        if not platforms:
            return jsonify({
                "success": False,
                "message": "platforms is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        results: List[Dict[str, Any]] = []
        errors: Dict[str, Any] = {}

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
                errors[p] = str(e)

        return jsonify({
            "success": True,
            "message": "ok",
            "data": {
                "results": results,
                "errors": errors or None,
            }
        }), HTTP_STATUS_CODES["OK"]