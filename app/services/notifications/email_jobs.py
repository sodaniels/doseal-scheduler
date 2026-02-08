#app/services/notifications/email_jobs.py

from datetime import datetime, timezone
from typing import List, Dict, Any

from ...models.social.scheduled_post import ScheduledPost
from ...models.business_model import Business
from ...utils.logger import Log

from .notification_service import NotificationService
from ..email_service import (
    send_post_published_email,
    send_post_failed_email
)

def _safe_iso(dt: Any) -> str:
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt) if dt is not None else ""


def _summarize_failures(provider_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds:
      - failed_platforms: ["facebook", "instagram"]
      - failed_items: [{platform, placement, destination_id, error}, ...]
      - first_error: "..."
      - failed_count, success_count
    """
    failed_items: List[Dict[str, Any]] = []
    success_count = 0
    failed_count = 0

    for r in provider_results or []:
        if not isinstance(r, dict):
            continue
        st = (r.get("status") or "").lower().strip()
        if st == "success":
            success_count += 1
            continue

        failed_count += 1
        failed_items.append({
            "platform": (r.get("platform") or "").strip().lower(),
            "placement": (r.get("placement") or "feed").strip().lower(),
            "destination_id": str(r.get("destination_id") or ""),
            "error": (r.get("error") or "").strip() or "Unknown error",
        })

    failed_platforms = sorted({x["platform"] for x in failed_items if x.get("platform")})
    first_error = (failed_items[0]["error"] if failed_items else "") or "Publishing failed."

    return {
        "failed_platforms": failed_platforms,
        "failed_items": failed_items,
        "first_error": first_error,
        "failed_count": failed_count,
        "success_count": success_count,
    }


def send_post_published_email_job(
    business_id: str,
    post_id: str,
):
    """
    Background job:
      - loads ScheduledPost
      - loads Business email/name
      - checks NotificationSettings
      - sends published email
    """

    log_tag = f"[email_jobs.py][send_post_published_email_job][{business_id}][{post_id}]"
    Log.info(f"{log_tag} start")

    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        Log.info(f"{log_tag} post not found")
        return

    status = post.get("status")
    if status not in (
        ScheduledPost.STATUS_PUBLISHED,
        getattr(ScheduledPost, "STATUS_PARTIAL", "partial"),
    ):
        Log.info(f"{log_tag} skipping email: status={status}")
        return

    # ----------------------------------------
    # Check Notification Settings
    # ----------------------------------------
    if not NotificationService.is_enabled(
        business_id=business_id,
        channel="email",
        item_key="scheduled_send_succeeded",
        default=False,
    ):
        Log.info(f"{log_tag} email disabled by settings")
        return

    # ----------------------------------------
    # Load business info
    # ----------------------------------------
    biz = Business.get_business_by_id(business_id) or {}
    email = (
        biz.get("email")
        or biz.get("owner_email")
        or biz.get("contact_email")
    )

    if not email:
        Log.info(f"{log_tag} no business email on record")
        return

    business_name =  biz.get("business_name") or "Unknown Business"

    # ----------------------------------------
    # Build email payload
    # ----------------------------------------
    content = post.get("content") or {}
    text = (content.get("text") or "").strip()

    scheduled_dt = post.get("scheduled_at_utc")
    scheduled_time = scheduled_dt.isoformat() if hasattr(scheduled_dt, "isoformat") else str(scheduled_dt)

    published_time = datetime.now(timezone.utc).isoformat()

    platforms = sorted({d.get("platform") for d in post.get("destinations") or [] if d.get("platform")})

    media = (content.get("media") or [])
    media_url = media[0].get("url") if media else None
    media_type = media[0].get("asset_type") if media else None

    send_post_published_email(
        email=email,
        fullname=business_name,
        post_text=text[:280],
        platforms=list(platforms),
        account_names=[],
        scheduled_time=scheduled_time,
        published_time=published_time,
        media_url=media_url,
        media_type=media_type,
        post_url=None,
        dashboard_url="https://app.doseal.com/social/posts",
    )

    Log.info(f"{log_tag} email sent")


def send_post_failed_email_job(
    business_id: str,
    post_id: str,
):
    """
    Background job:
      - loads ScheduledPost
      - loads Business email/name
      - checks NotificationSettings
      - sends FAILED email

    Triggers when overall status == failed (optionally also partial if you want).
    """
    log_tag = f"[email_jobs.py][send_post_failed_email_job][{business_id}][{post_id}]"
    Log.info(f"{log_tag} start")

    post = ScheduledPost.get_by_id(post_id, business_id)
    if not post:
        Log.info(f"{log_tag} post not found")
        return

    status = (post.get("status") or "").lower().strip()
    if status != ScheduledPost.STATUS_FAILED:
        Log.info(f"{log_tag} skipping email: status={status}")
        return

    # ----------------------------------------
    # Check Notification Settings
    # ----------------------------------------
    if not NotificationService.is_enabled(
        business_id=business_id,
        channel="email",
        item_key="scheduled_send_failed",
        default=True,   # you can set False if you want it off by default
    ):
        Log.info(f"{log_tag} email disabled by settings")
        return

    # ----------------------------------------
    # Load business info
    # ----------------------------------------
    biz = Business.get_business_by_id(business_id) or {}
    email = (
        biz.get("email")
        or biz.get("owner_email")
        or biz.get("contact_email")
    )

    if not email:
        Log.info(f"{log_tag} no business email on record")
        return

    business_name = biz.get("business_name") or "Unknown Business"

    # ----------------------------------------
    # Build email payload
    # ----------------------------------------
    content = post.get("content") or {}
    text = (content.get("text") or "").strip()

    scheduled_time = _safe_iso(post.get("scheduled_at_utc"))
    failed_time = datetime.now(timezone.utc).isoformat()

    platforms = sorted({d.get("platform") for d in post.get("destinations") or [] if d.get("platform")})

    media = (content.get("media") or [])
    media_url = media[0].get("url") if media else None
    media_type = media[0].get("asset_type") if media else None

    provider_results = post.get("provider_results") or []
    summary = _summarize_failures(provider_results)

    # overall_error is what you set in _publish_scheduled_post
    overall_error = (post.get("error") or "").strip() or summary["first_error"]

    # ----------------------------------------
    # Send email
    # ----------------------------------------
    send_post_failed_email(
        email=email,
        fullname=business_name,
        post_text=text[:280],
        platforms=list(platforms),
        failed_platforms=summary["failed_platforms"],
        failed_count=summary["failed_count"],
        success_count=summary["success_count"],
        scheduled_time=scheduled_time,
        failed_time=failed_time,
        error_message=overall_error,
        failed_items=summary["failed_items"],  # keep short in template
        media_url=media_url,
        media_type=media_type,
        dashboard_url="https://app.doseal.com/social/posts",
    )

    Log.info(f"{log_tag} email sent")


















