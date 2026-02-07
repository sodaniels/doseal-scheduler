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
from ....models.social.social_dashboard_summary import SocialDashboardSummary
from ....extensions.queue import enqueue


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


def _get_range_from_query():
    """
    Resolves (since, until) using query args:
      - since/until, or
      - days (default 30)
    Returns: (since_ymd, until_ymd, err_message|None)
    """
    since = (request.args.get("since") or "").strip() or None
    until = (request.args.get("until") or "").strip() or None
    days = (request.args.get("days") or "").strip() or None

    if (since and not _parse_ymd(since)) or (until and not _parse_ymd(until)):
        return None, None, "Invalid date format. Use YYYY-MM-DD"

    if not since or not until:
        if days:
            try:
                d = max(1, min(int(days), 365))
            except ValueError:
                d = 30
            since, until = _default_range(d)
        else:
            since, until = _default_range(30)

    if _parse_ymd(since) and _parse_ymd(until) and _parse_ymd(since) > _parse_ymd(until):
        return None, None, "'since' must be <= 'until'"

    return since, until, None


@blp_social_dashboard.route("/social/dashboard/overview", methods=["GET"])
class SocialDashboardOverviewResource(MethodView):
    """
    Combined analytics for all connected social accounts.

    Strategy:
      1) Try LIVE aggregation (and persist summary)
      2) If live fails (exception) OR you choose to treat live as unreliable, fallback to cached summary
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

        since, until, err = _get_range_from_query()
        if err:
            return jsonify({"success": False, "message": err}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # You can set this true if you want to fallback even when live returns with errors
        FALLBACK_IF_ANY_LIVE_ERROR = False

        # 1) Try LIVE
        try:
            agg = SocialAggregator()

            # and it stores SocialDashboardSummary for the range.
            data = agg.build_overview(
                business_id=business_id,
                user__id=user__id,
                since_ymd=since,
                until_ymd=until,
                persist=True,
            )

            # Optional strict rule: if ANY provider errors, fallback to cached
            if FALLBACK_IF_ANY_LIVE_ERROR and (data.get("errors") or []):
                raise Exception("LIVE_PARTIAL_FAILED")

            return jsonify({"success": True, "data": data, "source": "live"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} live failed: {e}")

            # 2) Fallback to CACHED SUMMARY
            cached = SocialDashboardSummary.get_summary(
                business_id=business_id,
                user__id=user__id,
                since_ymd=since,
                until_ymd=until,
            )

            if cached and cached.get("data"):
                return jsonify(
                    {
                        "success": True,
                        "data": cached["data"],
                        "source": "cached",
                        "cached_meta": {
                            "summary_id": cached.get("_id"),
                            "updated_at": cached.get("updated_at"),
                            "source": cached.get("source"),
                            "meta": cached.get("meta") or {},
                        },
                    }
                ), HTTP_STATUS_CODES["OK"]

            return jsonify(
                {
                    "success": False,
                    "message": "Live aggregation failed and no cached summary exists for this range.",
                }
            ), HTTP_STATUS_CODES["SERVICE_UNAVAILABLE"]


@blp_social_dashboard.route("/social/refresh-dashboard", methods=["POST"])
class SocialDashboardRefreshResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[social_dashboard_resource.py][SocialDashboardRefreshResource][post][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # enqueue per business, not all businesses
        try:
            enqueue(
                "app.services.social.jobs_snapshot.snapshot_daily_for_business",
                business_id,
                queue_name="publish",
                job_timeout=600,
            )
            return jsonify({"success": True, "message": "Snapshot job enqueued"}), 200
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return jsonify({"success": False, "message": "Internal error"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]