from flask.views import MethodView
from flask import request, jsonify, g
from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ...models.social.social_account import SocialAccount
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log
from ...utils.helpers import resolve_target_business_id_from_payload
from ...schemas.social.scheduled_posts_schema import ListScheduledPostsQuerySchema
from ..doseal.admin.admin_business_resource import token_required
from ...utils.json_response import prepared_response
from ...utils.helpers import make_log_tag
from flask_smorest import Blueprint

blp_social_posts = Blueprint("social_posts", __name__)

# -------------------------------------------------------------------
# GET /social/accounts
# -------------------------------------------------------------------
@blp_social_posts.route("/social/accounts", methods=["GET"])
class SocialPostsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_business_id = str(user.get("business_id") or "")
        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")

        if not auth_business_id or not auth_user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # NOTE:
        # GET should typically use query params, but if your UI sends JSON, keep this.
        # We'll merge both safely so SYSTEM_OWNER can override either way.
        body = request.get_json(silent=True) or {}
        query_payload = request.args.to_dict(flat=True) or {}

        # Merge: body overrides query (you can flip if you prefer)
        payload = {**query_payload, **body}

        target_business_id = resolve_target_business_id_from_payload(payload)

        log_tag = make_log_tag(
            "social_posts_resource.py",
            "SocialPostsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            # 1) Load ALL social accounts for this business
            accounts = SocialAccount.get_all_by_business_id(target_business_id)

            if not accounts:
                Log.info(f"{log_tag} No connected social accounts for this business.")
                return prepared_response(False, "BAD_REQUEST", "No connected social accounts for this business.")

            # 2) Optional filter: platform=facebook/instagram/x/tiktok...
            platform = (payload.get("platform") or "").strip().lower()
            if platform:
                accounts = [a for a in accounts if (a.get("platform") or "").lower() == platform]

            if not accounts:
                Log.info(f"{log_tag} No connected social accounts match your filter.")
                return prepared_response(False, "BAD_REQUEST", "No connected social accounts match your filter.")

            safe_accounts = []
            for a in accounts:
                safe_accounts.append({
                    "id": a.get("_id"),
                    "platform": a.get("platform"),
                    "destination_id": a.get("destination_id"),
                    "destination_type": a.get("destination_type"),
                    "destination_name": a.get("destination_name"),
                    "platform_username": a.get("platform_username"),
                    "created_at": a.get("created_at"),
                })

            return jsonify({
                "success": True,
                "message": "Social accounts loaded successfully",
                "data": {"business_id": target_business_id, "accounts": safe_accounts},
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to load social accounts",
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -------------------------------------------------------------------
# GET /social/accounts/<account_id>
# -------------------------------------------------------------------
@blp_social_posts.route("/social/accounts/<account_id>", methods=["GET"])
class SocialAccountResource(MethodView):
    @token_required
    def get(self, account_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_business_id = str(user.get("business_id") or "")
        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")

        if not auth_business_id or not auth_user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        body = request.get_json(silent=True) or {}
        query_payload = request.args.to_dict(flat=True) or {}
        payload = {**query_payload, **body}

        target_business_id = resolve_target_business_id_from_payload(payload)

        log_tag = make_log_tag(
            "social_posts_resource.py",
            "SocialAccountResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            # Validate account_id format
            if not account_id or not account_id.strip():
                Log.info(f"{log_tag} Missing account_id in request.")
                return prepared_response(False, "BAD_REQUEST", "Account ID is required.")

            # Fetch single account by ID and business ID
            account = SocialAccount.get_by_id_and_business_id(account_id.strip(), target_business_id)

            if not account:
                Log.info(f"{log_tag} Social account not found: {account_id}")
                return prepared_response(False, "NOT_FOUND", "Social account not found.")

            safe_account = {
                "id": account.get("_id"),
                "platform": account.get("platform"),
                "destination_id": account.get("destination_id"),
                "destination_type": account.get("destination_type"),
                "destination_name": account.get("destination_name"),
                "platform_username": account.get("platform_username"),
                "created_at": account.get("created_at"),
            }

            return jsonify({
                "success": True,
                "message": "Social account loaded successfully",
                "data": {"business_id": target_business_id, "account": safe_account},
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to load social account",
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
# -------------------------------------------------------------------
# GET /socials/scheduled_posts
# -------------------------------------------------------------------
@blp_social_posts.route("/social/scheduled-posts", methods=["GET"])
class ListScheduledPostsResource(MethodView):

    @token_required
    @blp_social_posts.arguments(ListScheduledPostsQuerySchema, location="query")
    @blp_social_posts.doc(
        summary="List scheduled posts for a business",
        description="""
            This endpoint returns **scheduled posts** for the authenticated user's business (tenant).
            The request requires an `Authorization` header with a Bearer token.

            - **GET**: Fetch scheduled posts created under a business.
            - Supports **pagination** (`page`, `per_page`)
            - Supports optional filters:
              - `status` (e.g. scheduled, published, failed)
              - `platform` (provider filter e.g. facebook, instagram, x, tiktok)
              - `date_from`, `date_to` (filter scheduled time range)

            **Business override (Admin only):**
            - If the logged-in user is `SYSTEM_OWNER` or `SUPER_ADMIN`, they may pass `business_id`
              to view posts for another business.
        """,
        parameters=[
            {
                "in": "query",
                "name": "business_id",
                "required": False,
                "schema": {"type": "string"},
                "description": "Optional. Only SYSTEM_OWNER / SUPER_ADMIN may specify this to target another business.",
                "example": "697a1786179f5da15d50d7c6",
            },
            {
                "in": "query",
                "name": "page",
                "required": False,
                "schema": {"type": "integer", "default": 1, "minimum": 1},
                "description": "Page number (default: 1).",
                "example": 1,
            },
            {
                "in": "query",
                "name": "per_page",
                "required": False,
                "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                "description": "Number of items per page (default: 20, max: 100).",
                "example": 20,
            },
            {
                "in": "query",
                "name": "status",
                "required": False,
                "schema": {"type": "string"},
                "description": "Filter by post status (draft, scheduled, enqueued, publishing, published, failed, partial, cancelled).",
                "example": "published",
            },
            {
                "in": "query",
                "name": "platform",
                "required": False,
                "schema": {"type": "string"},
                "description": "Filter posts by provider/platform (facebook, instagram, x, tiktok).",
                "example": "facebook",
            },
            {
                "in": "query",
                "name": "date_from",
                "required": False,
                "schema": {"type": "string", "format": "date-time"},
                "description": "Filter posts whose scheduled_at_utc is >= this value (ISO8601).",
                "example": "2026-01-01T00:00:00Z",
            },
            {
                "in": "query",
                "name": "date_to",
                "required": False,
                "schema": {"type": "string", "format": "date-time"},
                "description": "Filter posts whose scheduled_at_utc is <= this value (ISO8601).",
                "example": "2026-01-31T23:59:59Z",
            },
        ],
        responses={
            200: {
                "description": "Scheduled posts retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Scheduled posts retrieved successfully.",
                            "data": {
                                "items": [
                                    {
                                        "_id": "697de14ce00813087204f596",
                                        "business_id": "697a1786179f5da15d50d7c6",
                                        "user__id": "697a1786179f5da15d50d7c8",
                                        "platform": "multi",
                                        "status": "published",
                                        "scheduled_at_utc": "2026-01-31T11:03:00+00:00",
                                        "destinations": [
                                            {
                                                "platform": "facebook",
                                                "destination_type": "page",
                                                "destination_id": "107689318338584",
                                                "placement": "feed"
                                            }
                                        ],
                                        "content": {
                                            "text": "We have stood the test of time🚀",
                                            "link": "https://fucah.org",
                                            "media": [
                                                {
                                                    "asset_type": "video",
                                                    "url": "https://res.cloudinary.com/.../video.mp4",
                                                    "bytes": 26851560
                                                }
                                            ]
                                        },
                                        "created_at": "2026-01-31T11:02:36.947+00:00",
                                        "updated_at": "2026-01-31T11:03:51.757+00:00"
                                    }
                                ],
                                "total_count": 1,
                                "total_pages": 1,
                                "current_page": 1,
                                "per_page": 20,
                            }
                        }
                    }
                }
            },
            404: {
                "description": "No scheduled posts found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "No scheduled posts found for this business."
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Unauthorized"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "Failed to load scheduled posts.",
                            "errors": ["Detailed error message here"]
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],
    )
    def get(self, args):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")

        from ...utils.helpers import resolve_target_business_id_from_payload
        target_business_id = resolve_target_business_id_from_payload(args)

        log_tag = make_log_tag(
            "social_posts_resource.py",
            "ListScheduledPostsResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            target_business_id,
            target_business_id,
        )

        try:
            page = args.get("page", 1)
            per_page = args.get("per_page", 20)
            status = args.get("status")
            platforms = args.get("platform")
            date_from = args.get("date_from")
            date_to = args.get("date_to")

            result = ScheduledPost.list_by_business_id(
                business_id=target_business_id,
                page=page,
                per_page=per_page,
                status=status,
                platform=platforms,
                date_from=date_from,
                date_to=date_to,
            )

            if not result.get("items"):
                return prepared_response(False, "NOT_FOUND", "No scheduled posts found for this business.")

            return prepared_response(True, "OK", "Scheduled posts retrieved successfully.", data=result)

        except Exception as e:
            Log.error(f"{log_tag} ERROR: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to load scheduled posts.",
                errors=[str(e)],
            )

# -------------------------------------------------------------------
# POST /social/account-disconnect
# -------------------------------------------------------------------
@blp_social_posts.route("/social/account-disconnect", methods=["POST"])
class SocialAccountDisconnectResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        auth_business_id = str(user.get("business_id") or "")
        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")

        if not auth_business_id or not auth_user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        body = request.get_json(silent=True) or {}
        query_payload = request.args.to_dict(flat=True) or {}
        payload = {**query_payload, **body}

        target_business_id = resolve_target_business_id_from_payload(payload)

        log_tag = make_log_tag(
            "social_posts_resource.py",
            "SocialAccountDisconnectResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        try:
            # Validate account_id from payload
            account_id = (payload.get("account_id") or "").strip()
            if not account_id:
                Log.info(f"{log_tag} Missing account_id in request.")
                return prepared_response(False, "BAD_REQUEST", "Account ID is required.")

            # Check if account exists and belongs to this business
            account = SocialAccount.get_by_id_and_business_id(account_id, target_business_id)

            if not account:
                Log.info(f"{log_tag} Social account not found: {account_id}")
                return prepared_response(False, "NOT_FOUND", "Social account not found.")

            # Disconnect (delete) the account
            deleted = SocialAccount.disconnect_by_id_and_business_id(account_id, target_business_id)

            if not deleted:
                Log.info(f"{log_tag} Failed to disconnect social account: {account_id}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to disconnect social account.")

            Log.info(f"{log_tag} Social account disconnected successfully: {account_id}")

            return jsonify({
                "success": True,
                "message": "Social account disconnected successfully",
                "data": {
                    "business_id": target_business_id,
                    "account_id": account_id,
                    "platform": account.get("platform"),
                    "destination_name": account.get("destination_name"),
                },
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to disconnect social account",
                "error": str(e),
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]



























