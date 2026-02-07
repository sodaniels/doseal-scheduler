# app/resources/admin/business_suspension_resource.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from flask import jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate, ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...extensions import db as db_ext
from ...utils.logger import Log
from ..doseal.admin.admin_business_resource import token_required


blp_business_suspension = Blueprint(
    "business_suspension",
    __name__,
    description="Admin business publishing suspension",
)


# -----------------------------
# Helpers
# -----------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _oid(s: str) -> ObjectId:
    return ObjectId(str(s))


def _to_str_oid(v) -> Optional[str]:
    try:
        return str(v) if v else None
    except Exception:
        return None


def _suspensions_col():
    return db_ext.get_collection("business_suspensions")


def _get_active_suspension_doc(business_id: str) -> Optional[Dict[str, Any]]:
    col = _suspensions_col()
    return col.find_one(
        {"business_id": _oid(business_id), "is_active": True},
        sort=[("suspended_at", -1)],
    )


def _serialize_suspension(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not doc:
        return {"is_suspended": False}

    return {
        "is_suspended": True,
        "business_id": _to_str_oid(doc.get("business_id")),
        "reason": doc.get("reason"),
        "scope": doc.get("scope") or "all",
        "platforms": doc.get("platforms"),
        "destinations": doc.get("destinations"),
        "suspended_at": doc.get("suspended_at").isoformat() if doc.get("suspended_at") else None,
        "suspended_by": _to_str_oid(doc.get("suspended_by")),
        "resumed_at": doc.get("resumed_at").isoformat() if doc.get("resumed_at") else None,
        "resumed_by": _to_str_oid(doc.get("resumed_by")),
        "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
    }


# -----------------------------
# Schemas
# -----------------------------
class SuspendBusinessSchema(Schema):
    reason = fields.String(required=True, validate=validate.Length(min=2, max=500))
    scope = fields.String(
        required=False,
        validate=validate.OneOf(["all", "platforms", "destinations"]),
        load_default="all",
    )
    platforms = fields.List(fields.String(), required=False, allow_none=True)
    destinations = fields.List(fields.Dict(), required=False, allow_none=True)


class ResumeBusinessSchema(Schema):
    reason = fields.String(required=False, allow_none=True, validate=validate.Length(min=0, max=500))


# -----------------------------
# Endpoints
# -----------------------------

@blp_business_suspension.route("/businesses/<business_id>/suspend", methods=["POST"])
class AdminSuspendBusinessResource(MethodView):
    """
    POST /businesses/{id}/suspend

    Body:
      {
        "reason": "string (required)",
        "scope": "all|platforms|destinations" (optional),
        "platforms": ["facebook","instagram"] (optional),
        "destinations": [{"platform":"instagram","destination_id":"..."}] (optional)
      }
    """

    @token_required
    def post(self, business_id: str):
        client_ip = request.remote_addr
        log_tag = f"[business_suspension_resource.py][AdminSuspendBusinessResource][post][{client_ip}]"

        # NOTE: token_required likely sets g.current_user, but we don't rely on it heavily here.
        # We just record "suspended_by" if present.
        from flask import g
        admin = g.get("current_user") or {}
        admin_id = admin.get("_id")

        # Validate business_id
        try:
            _ = _oid(business_id)
        except Exception:
            return jsonify({"success": False, "message": "Invalid business id"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        body = request.get_json(silent=True) or {}
        try:
            payload = SuspendBusinessSchema().load(body)
        except ValidationError as err:
            return jsonify({"success": False, "message": "Validation failed", "errors": err.messages}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Enforce scope rules
        scope = (payload.get("scope") or "all").strip().lower()
        platforms = payload.get("platforms")
        destinations = payload.get("destinations")

        if scope == "platforms" and not platforms:
            return jsonify({"success": False, "message": "platforms is required when scope=platforms"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if scope == "destinations" and not destinations:
            return jsonify({"success": False, "message": "destinations is required when scope=destinations"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        col = _suspensions_col()
        now = _utc_now()

        try:
            # Ensure only one active doc:
            # If already suspended, just update reason/scope (idempotent-ish).
            active = _get_active_suspension_doc(business_id)

            if active:
                res = col.update_one(
                    {"_id": active["_id"]},
                    {"$set": {
                        "reason": payload["reason"],
                        "scope": scope,
                        "platforms": platforms if scope == "platforms" else None,
                        "destinations": destinations if scope == "destinations" else None,
                        "updated_at": now,
                    }},
                )
                # re-fetch for response
                active2 = _get_active_suspension_doc(business_id)
                return jsonify({
                    "success": True,
                    "message": "Business already suspended (updated)",
                    "data": _serialize_suspension(active2),
                }), HTTP_STATUS_CODES["OK"]

            doc = {
                "business_id": _oid(business_id),
                "is_active": True,
                "reason": payload["reason"],
                "scope": scope,
                "platforms": platforms if scope == "platforms" else None,
                "destinations": destinations if scope == "destinations" else None,
                "suspended_at": now,
                "suspended_by": _oid(str(admin_id)) if admin_id else None,
                "resumed_at": None,
                "resumed_by": None,
                "updated_at": now,
            }

            col.insert_one(doc)

            # Return active
            active3 = _get_active_suspension_doc(business_id)
            return jsonify({
                "success": True,
                "message": "Business suspended",
                "data": _serialize_suspension(active3),
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_business_suspension.route("/businesses/<business_id>/resume", methods=["POST"])
class AdminResumeBusinessResource(MethodView):
    """
    POST /admin/businesses/{id}/resume

    Body (optional):
      { "reason": "optional note" }
    """

    @token_required
    def post(self, business_id: str):
        client_ip = request.remote_addr
        log_tag = f"[business_suspension_resource.py][AdminResumeBusinessResource][post][{client_ip}]"

        from flask import g
        admin = g.get("current_user") or {}
        admin_id = admin.get("_id")

        try:
            _ = _oid(business_id)
        except Exception:
            return jsonify({"success": False, "message": "Invalid business id"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        body = request.get_json(silent=True) or {}
        try:
            payload = ResumeBusinessSchema().load(body)
        except ValidationError as err:
            return jsonify({"success": False, "message": "Validation failed", "errors": err.messages}), HTTP_STATUS_CODES["BAD_REQUEST"]

        col = _suspensions_col()
        now = _utc_now()

        try:
            active = _get_active_suspension_doc(business_id)
            if not active:
                return jsonify({
                    "success": True,
                    "message": "Business is not suspended",
                    "data": {"is_suspended": False},
                }), HTTP_STATUS_CODES["OK"]

            updates = {
                "is_active": False,
                "resumed_at": now,
                "resumed_by": _oid(str(admin_id)) if admin_id else None,
                "updated_at": now,
            }

            # store optional resume note without overwriting original suspend reason
            resume_reason = (payload.get("reason") or "").strip()
            if resume_reason:
                updates["resume_reason"] = resume_reason

            col.update_one({"_id": active["_id"]}, {"$set": updates})

            return jsonify({
                "success": True,
                "message": "Business resumed",
                "data": {"is_suspended": False},
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_business_suspension.route("/businesses/<business_id>/suspension-status", methods=["GET"])
class AdminBusinessSuspensionStatusResource(MethodView):
    """
    GET /admin/businesses/{id}/suspension-status
    """

    @token_required
    def get(self, business_id: str):
        client_ip = request.remote_addr
        log_tag = f"[business_suspension_resource.py][AdminBusinessSuspensionStatusResource][get][{client_ip}]"

        try:
            _ = _oid(business_id)
        except Exception:
            return jsonify({"success": False, "message": "Invalid business id"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            active = _get_active_suspension_doc(business_id)
            return jsonify({
                "success": True,
                "data": _serialize_suspension(active),
            }), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]