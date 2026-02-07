# app/resources/social/social_dashboard_resource.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from flask import g, jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ....constants.service_code import HTTP_STATUS_CODES
from ....utils.logger import Log
from ...doseal.admin.admin_business_resource import token_required
from ....services.social.aggregator import SocialAggregator


blp_social_dashboard = Blueprint("social_dashboard", __name__)


def _parse_ymd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _default_range(days: int = 30):
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    return _fmt_ymd(since), _fmt_ymd(until)


@blp_social_dashboard.route("/social/dashboard/overview", methods=["GET"])
class SocialDashboardOverviewResource(MethodView):
    """
    Combined analytics for all connected social accounts.

    Query:
      - since=YYYY-MM-DD (optional)
      - until=YYYY-MM-DD (optional)
      - days=30 (optional alternative)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[social_dashboard_resource.py][SocialDashboardOverviewResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        days = (request.args.get("days") or "").strip() or None

        if (since and not _parse_ymd(since)) or (until and not _parse_ymd(until)):
            return jsonify({"success": False, "message": "Invalid date format. Use YYYY-MM-DD"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        if not since or not until:
            if days:
                try:
                    d = max(1, min(int(days), 365))
                except ValueError:
                    d = 30
                since, until = _default_range(d)
            else:
                since, until = _default_range(30)

        if _parse_ymd(since) > _parse_ymd(until):
            return jsonify({"success": False, "message": "'since' must be <= 'until'"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            agg = SocialAggregator()
            data = agg.build_overview(
                business_id=business_id,
                user__id=user__id,
                since_ymd=since,
                until_ymd=until,
            )
            return jsonify({"success": True, "data": data}), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]