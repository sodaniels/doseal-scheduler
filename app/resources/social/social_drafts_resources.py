# -------------------------------------------------------------------
# DRAFT POSTS: CREATE / UPDATE (save and continue later)
# -------------------------------------------------------------------
# Assumptions:
# - You’ll store drafts in the SAME ScheduledPost collection.
# - status="draft" means it will NEVER be picked by your scheduler until user "publishes".
# - You can reuse CreateScheduledPostSchema to validate + normalize.
# - We use PATCH to update an existing draft.
#
# Add these statuses to your ScheduledPost model if not present:
#   STATUS_DRAFT = "draft"
#   STATUS_SCHEDULED = "scheduled"
#   STATUS_PENDING = "pending"
#   STATUS_FAILED = "failed"
#
# NOTE:
# - If you already have ScheduledPost.update_by_id(...) use it.
# - Otherwise, implement ScheduledPost.update_fields(post_id, business_id, updates)
# -------------------------------------------------------------------

from datetime import datetime, timezone
from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from typing import Any, Dict, Optional
from marshmallow import ValidationError

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ..doseal.admin.admin_business_resource import token_required
from ...models.social.scheduled_post import ScheduledPost
from ...extensions.queue import get_queue
from ...extensions.queue import publish_queue

def _utcnow():
    return datetime.now(timezone.utc)

def _as_dt(v):
    """
    Ensures scheduled_at_utc is a datetime.
    Accepts datetime or ISO string.
    """
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        # tolerate "Z"
        s = v.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None

def _as_dt_(value) -> Optional[datetime]:
    """
    Convert stored DB value into UTC datetime.

    Accepts:
      - datetime
      - ISO string
      - None

    Returns UTC-aware datetime or None.
    """

    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=timezone.utc)

    if isinstance(value, str):
        return _parse_iso8601_with_tz(value)

    return None

def _parse_iso8601_with_tz(value: str) -> Optional[datetime]:
    """
    Parse ISO-8601 string into UTC-aware datetime.

    Accepts:
      - 2026-02-05T11:55:00+00:00
      - 2026-02-05T11:55:00Z
      - 2026-02-05T11:55:00

    Returns UTC datetime.
    """

    if not value:
        return None

    s = str(value).strip()

    # Replace trailing Z with +00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ValueError(f"Invalid isoformat datetime: {value}")

    # Make UTC-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt

from ...schemas.social.scheduled_posts_schema import CreateScheduledPostSchema
from ...utils.social.publish_payload_utils import _ensure_content_shape

blp_drafts = Blueprint("draft_posts", __name__, description="Draft post management")


# ---------------------------------------------------------
# LIST DRAFT POSTS
# ---------------------------------------------------------
@blp_drafts.route("/social/drafts", methods=["POST"])
class CreateDraftPostResource(MethodView):
    """
    Create a draft that can be edited later.

    Request body:
      - Same shape as CreateScheduledPostResource expects
      - scheduled_at is OPTIONAL for drafts (user can add later)
    """

    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[social_drafts_resources.py][CreateDraftPostResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}

        # ---------------- AUTH CONTEXT ----------------
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ---------------- PRE-NORMALIZE ----------------
        body = _ensure_content_shape(body)

        # ---------------- VALIDATE + NORMALIZE ----------------
        # For drafts, we allow scheduled_at to be missing => schema should default to "now".
        # If you want drafts to store scheduled_at_utc=None until user sets it, see comment below.
        try:
            payload = CreateScheduledPostSchema().load(body)
        except ValidationError as err:
            return jsonify({
                "success": False,
                "message": "Validation failed",
                "errors": err.messages,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        scheduled_at_utc = payload.get("_scheduled_at_utc")  # datetime
        normalized_content = payload.get("_normalized_content") or {}
        normalized_media = normalized_content.get("media")

        # enforce canonical: list[dict] or None
        if isinstance(normalized_media, dict):
            normalized_media = [normalized_media]
        elif not isinstance(normalized_media, list):
            normalized_media = None

        destinations = payload.get("destinations") or []
        manual_required = payload.get("_manual_required") or []

        # ---------------- BUILD DRAFT DOC ----------------
        now = datetime.now(timezone.utc)

        # If you prefer drafts to not have scheduled_at_utc until user sets it,
        # you can store scheduled_at_utc=None and scheduled_at_utc in DB as None.
        # But your scheduler enqueue code expects a datetime; so keep it null for drafts.
        #
        # Here, we store BOTH:
        # - scheduled_at_utc: (may be None if user didn't provide scheduled_at)
        # - scheduled_at_provided: flag for UI
        scheduled_at_raw = (body.get("scheduled_at") or "").strip() or None
        scheduled_at_for_db = scheduled_at_utc if scheduled_at_raw else None

        post_doc = {
            "business_id": business_id,
            "user__id": user__id,

            "platform": "multi",
            "status": getattr(ScheduledPost, "STATUS_DRAFT", "draft"),

            "created_at": now,
            "updated_at": now,

            "scheduled_at_utc": scheduled_at_for_db,
            "scheduled_at": scheduled_at_for_db.isoformat() if scheduled_at_for_db else None,

            "destinations": destinations,

            "content": {
                "text": normalized_content.get("text"),
                "link": normalized_content.get("link"),
                "media": normalized_media,
            },

            "provider_results": [],
            "error": None,

            "manual_required": manual_required or None,

            "draft_meta": {
                "scheduled_at_provided": bool(scheduled_at_raw),
                "last_saved_at": now.isoformat(),
            },
        }

        try:
            created = ScheduledPost.create(post_doc)
        except Exception as e:
            Log.info(f"{log_tag} Failed to create draft: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to create draft",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        return jsonify({
            "success": True,
            "message": "draft_saved",
            "data": created,
        }), HTTP_STATUS_CODES["CREATED"]

# ---------------------------------------------------------
# LIST DRAFT POSTS
# ---------------------------------------------------------
@blp_drafts.route("/social/drafts", methods=["GET"])
class ListDraftsResource(MethodView):

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[social_drafts_resource.py][ListDraftsResource][get][{client_ip}]"

        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # --------------------------------------
        # QUERY PARAMS
        # --------------------------------------
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)

        platform = request.args.get("platform")  # instagram,facebook
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        # --------------------------------------
        # Call model helper
        # --------------------------------------
        try:
            result = ScheduledPost.list_by_business_id(
                business_id=business_id,
                page=page,
                per_page=per_page,
                status=getattr(ScheduledPost, "STATUS_DRAFT", "draft"),
                platform=platform,
                date_from=_parse_iso8601_with_tz(date_from) if date_from else None,
                date_to=_parse_iso8601_with_tz(date_to) if date_to else None,
            )

            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} failed to list drafts: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to list drafts"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
      
        
@blp_drafts.route("/social/drafts/<post_id>", methods=["PATCH"])
class UpdateDraftPostResource(MethodView):
    """
    Update an existing draft (edit and continue later).

    Rules:
      - Only drafts can be edited here (status must be "draft")
      - Same body shape as create/schedule endpoint (content + destinations + optional scheduled_at)
      - Does NOT enqueue publishing.
    """

    @token_required
    def patch(self, post_id):
        client_ip = request.remote_addr
        log_tag = f"[social_drafts_resources.py][UpdateDraftPostResource][patch][{client_ip}]"

        body = request.get_json(silent=True) or {}

        # ---------------- AUTH CONTEXT ----------------
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ---------------- LOAD EXISTING ----------------
        existing = ScheduledPost.get_by_id(post_id, business_id)
        if not existing:
            return jsonify({
                "success": False,
                "message": "Draft not found",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        if str(existing.get("user__id")) != str(user__id):
            return jsonify({
                "success": False,
                "message": "Not allowed",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        if existing.get("status") != getattr(ScheduledPost, "STATUS_DRAFT", "draft"):
            return jsonify({
                "success": False,
                "message": "Only drafts can be edited. This post is not a draft.",
                "code": "NOT_EDITABLE",
            }), HTTP_STATUS_CODES["CONFLICT"]

        # ---------------- PRE-NORMALIZE ----------------
        body = _ensure_content_shape(body)

        # ---------------- VALIDATE + NORMALIZE ----------------
        try:
            payload = CreateScheduledPostSchema().load(body)
        except ValidationError as err:
            return jsonify({
                "success": False,
                "message": "Validation failed",
                "errors": err.messages,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        scheduled_at_utc = payload.get("_scheduled_at_utc")
        normalized_content = payload.get("_normalized_content") or {}
        normalized_media = normalized_content.get("media")

        if isinstance(normalized_media, dict):
            normalized_media = [normalized_media]
        elif not isinstance(normalized_media, list):
            normalized_media = None

        destinations = payload.get("destinations") or []
        manual_required = payload.get("_manual_required") or []

        scheduled_at_raw = (body.get("scheduled_at") or "").strip() or None
        scheduled_at_for_db = scheduled_at_utc if scheduled_at_raw else None

        now = datetime.now(timezone.utc)

        updates = {
            "updated_at": now,
            "scheduled_at_utc": scheduled_at_for_db,
            "scheduled_at": scheduled_at_for_db.isoformat() if scheduled_at_for_db else None,
            "destinations": destinations,
            "content": {
                "text": normalized_content.get("text"),
                "link": normalized_content.get("link"),
                "media": normalized_media,
            },
            "manual_required": manual_required or None,
            "error": None,  # clear previous error on edit
            "draft_meta": {
                "scheduled_at_provided": bool(scheduled_at_raw),
                "last_saved_at": now.isoformat(),
            },
        }

        try:
            # Prefer: ScheduledPost.update_fields(post_id, business_id, updates)
            updated = ScheduledPost.update_fields(post_id, business_id, updates)
        except AttributeError:
            # If your model doesn't have update_fields, fallback to update_status-like method if available
            try:
                updated = ScheduledPost.update_by_id(post_id, business_id, updates)
            except Exception as e:
                Log.info(f"{log_tag} Failed to update draft: {e}")
                return jsonify({
                    "success": False,
                    "message": "Failed to update draft",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except Exception as e:
            Log.info(f"{log_tag} Failed to update draft: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to update draft",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Reload for response consistency (optional)
        final = ScheduledPost.get_by_id(post_id, business_id) or updated

        return jsonify({
            "success": True,
            "message": "draft_updated",
            "data": final,
        }), HTTP_STATUS_CODES["OK"]


@blp_drafts.route("/social/drafts/<post_id>/finalize", methods=["POST"])
class FinalizeDraftToScheduledResource(MethodView):
    """
    Converts draft -> scheduled/enqueued.

    Rules implemented:
      1) If publish_now=true => scheduled_at_utc = now
      2) Else if body.scheduled_at provided => scheduled_at_utc = parsed value
      3) Else use existing.scheduled_at_utc (must exist)
      4) If manual_required => mark scheduled, DO NOT enqueue
      5) If due now/past => mark enqueued and enqueue immediately (RQ)
      6) Else => mark scheduled and let enqueuer pick it up when due
    """

    @token_required
    def post(self, post_id):
        client_ip = request.remote_addr
        log_tag = f"[social_drafts_resources.py][FinalizeDraftToScheduledResource][post][{client_ip}]"

        body: Dict[str, Any] = request.get_json(silent=True) or {}

        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        existing = ScheduledPost.get_by_id(post_id, business_id)
        if not existing:
            return jsonify({"success": False, "message": "Draft not found"}), HTTP_STATUS_CODES["NOT_FOUND"]

        if str(existing.get("user__id")) != str(user__id):
            return jsonify({"success": False, "message": "Not allowed"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        if existing.get("status") != getattr(ScheduledPost, "STATUS_DRAFT", "draft"):
            return jsonify({"success": False, "message": "Not a draft"}), HTTP_STATUS_CODES["CONFLICT"]

        # ---------------------------------------------------
        # ✅ 1) Decide scheduled_at_utc from rules
        # ---------------------------------------------------
        now = _utcnow()
        publish_now = bool(body.get("publish_now", False))
        scheduled_at_raw = body.get("scheduled_at")

        if publish_now:
            scheduled_at_utc = now
        elif scheduled_at_raw:
            scheduled_at_utc = _as_dt(scheduled_at_raw)
            if not scheduled_at_utc:
                return jsonify({
                    "success": False,
                    "message": "Invalid scheduled_at. Use ISO8601 with timezone, e.g. 2026-02-05T12:07:00+00:00",
                    "code": "INVALID_SCHEDULED_AT",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
        else:
            scheduled_at_utc = _as_dt(existing.get("scheduled_at_utc"))

        if not scheduled_at_utc:
            return jsonify({
                "success": False,
                "message": "Draft has no valid scheduled_at_utc. Provide scheduled_at or publish_now=true.",
                "code": "MISSING_SCHEDULED_AT",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ---------------------------------------------------
        # ✅ 2) Status decision
        # ---------------------------------------------------
        manual_required = existing.get("manual_required") or []

        if manual_required:
            new_status = getattr(ScheduledPost, "STATUS_SCHEDULED", "scheduled")
            enqueue_now = False
        else:
            enqueue_now = scheduled_at_utc <= now
            new_status = getattr(ScheduledPost, "STATUS_ENQUEUED", "enqueued") if enqueue_now else getattr(ScheduledPost, "STATUS_SCHEDULED", "scheduled")

        # ---------------------------------------------------
        # ✅ 3) Persist updates
        # ---------------------------------------------------
        try:
            ScheduledPost.update_fields(post_id, business_id, {
                "status": new_status,
                "scheduled_at_utc": scheduled_at_utc,  # store as datetime
                "scheduled_at": scheduled_at_utc.isoformat(),
                "updated_at": now,
                "finalized_at": now,
                "finalize_mode": "publish_now" if publish_now else "schedule",
            })
        except Exception as e:
            Log.info(f"{log_tag} finalize failed: {e}")
            return jsonify({"success": False, "message": "Failed to finalize draft"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Manual required: stop
        if manual_required:
            final = ScheduledPost.get_by_id(post_id, business_id)
            return jsonify({
                "success": True,
                "message": "scheduled (manual_required)",
                "data": final,
            }), HTTP_STATUS_CODES["OK"]

        # ---------------------------------------------------
        # ✅ 4) Enqueue immediately if due
        # ---------------------------------------------------
        if enqueue_now:
            try:
                q = publish_queue
                job_id = f"publish_{business_id}_{post_id}"

                try:
                    existing_job = q.fetch_job(job_id)
                    if existing_job and existing_job.get_status() in (
                        "queued",
                        "started",
                        "deferred",
                        "scheduled",
                    ):
                        Log.info(f"{log_tag} already queued job_id={job_id}")
                    else:
                        q.enqueue(
                            "app.services.social.jobs.publish_scheduled_post",
                            str(post_id),
                            str(business_id),
                            job_id=job_id,
                            job_timeout=180,
                            result_ttl=300,
                            failure_ttl=86400,
                        )
                except Exception:
                    q.enqueue(
                        "app.services.social.jobs.publish_scheduled_post",
                        str(post_id),
                        str(business_id),
                        job_id=job_id,
                        job_timeout=180,
                        result_ttl=300,
                        failure_ttl=86400,
                    )

                # store job info
                try:
                    ScheduledPost.update_fields(post_id, business_id, {
                        "enqueue_job_id": job_id,
                        "enqueued_at": now,
                        "updated_at": now,
                    })
                except Exception:
                    pass

            except Exception as e:
                Log.info(f"{log_tag} immediate enqueue failed: {e}")
                try:
                    ScheduledPost.update_status(
                        post_id,
                        business_id,
                        getattr(ScheduledPost, "STATUS_FAILED", "failed"),
                        error=f"enqueue failed: {e}",
                    )
                except Exception:
                    pass
                return jsonify({
                    "success": False,
                    "message": "Finalized but enqueue failed",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        final = ScheduledPost.get_by_id(post_id, business_id)
        return jsonify({
            "success": True,
            "message": "enqueued" if enqueue_now else "scheduled",
            "data": final,
        }), HTTP_STATUS_CODES["OK"]
        
# -------------------------------------------------------------------
# DRAFT POSTS: DELETE
# -------------------------------------------------------------------
@blp_drafts.route("/social/drafts/<post_id>", methods=["DELETE"])
class DeleteDraftPostResource(MethodView):
    """
    Delete a draft.

    Rules:
      - Only the owner can delete it
      - Only drafts can be deleted here (status must be "draft")
    """

    @token_required
    def delete(self, post_id):
        client_ip = request.remote_addr
        log_tag = f"[social_drafts_resources.py][DeleteDraftPostResource][delete][{client_ip}]"

        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")
        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Load existing
        existing = ScheduledPost.get_by_id(post_id, business_id)
        if not existing:
            return jsonify({
                "success": False,
                "message": "Draft not found",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        if str(existing.get("user__id")) != str(user__id):
            return jsonify({
                "success": False,
                "message": "Not allowed",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        if existing.get("status") != getattr(ScheduledPost, "STATUS_DRAFT", "draft"):
            return jsonify({
                "success": False,
                "message": "Only drafts can be deleted. This post is not a draft.",
                "code": "NOT_DELETABLE",
            }), HTTP_STATUS_CODES["CONFLICT"]

        try:
            # Prefer a model helper if you have it
            if hasattr(ScheduledPost, "delete_by_id"):
                ScheduledPost.delete_by_id(post_id, business_id)
            elif hasattr(ScheduledPost, "delete_one"):
                ScheduledPost.delete_one(post_id, business_id)
            else:
                # Fallback: soft-delete (recommended) if you don't have a delete method
                ScheduledPost.update_fields(post_id, business_id, {
                    "status": "deleted",
                    "deleted_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                })

            return jsonify({
                "success": True,
                "message": "draft_deleted",
                "data": {"post_id": str(post_id)},
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to delete draft: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to delete draft",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]