# app/workers/reminder_worker.py
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from bson.objectid import ObjectId

from ..extensions.db import db
from ..utils.logger import Log
from ..utils.crypt import decrypt_data, encrypt_data
from ..services.reminder_queue import (
    ZSET_KEY, JOB_KEY_FMT, JOBSET_BY_PAYABLE_FMT,
    RETRY_DELAY_SEC, MAX_RETRIES, utcnow
)
from ..utils.redis import get_redis  # ✔ your helper

SLEEP_IDLE_SEC = 1
BATCH_POP = 50  # max jobs to pop per cycle

# --- auto-clean config ---
EXPIRE_GRACE_SEC = 3600      # consider "expired" if ETA <= now - 1h
CLEANUP_EVERY_SEC = 60       # run GC once per minute
_MAX_PRUNE_PER_CYCLE = 2000  # cap the GC work per sweep

def _b2s(x):
    return x.decode("utf-8") if isinstance(x, (bytes, bytearray)) else x

def _parse_pid_from_jid(jid: str) -> str | None:
    # jid format: payable:{pid}:off:{d}:at:{eta}
    try:
        parts = jid.split(":")
        return parts[1] if len(parts) >= 2 and parts[0] == "payable" else None
    except Exception:
        return None

def safe_decrypt(v):
    try:
        return decrypt_data(v) if v else None
    except Exception:
        return None

def process_job(payload: dict):
    """
    Executes a reminder job:
    - loads payable
    - checks status/idempotency
    - (send email+sms)
    - records reminder + bumps status to 'notified'
    """
    col = db.get_collection("payables")
    pid = payload["payable_id"]
    offset = int(payload["offset_days"])

    p = col.find_one({"_id": ObjectId(pid)})
    if not p:
        Log.info(f"[reminder-worker] payable not found pid={pid}")
        return True  # discard

    status = (safe_decrypt(p.get("status")) or "").lower()
    if status in ("cancelled", "completed"):
        Log.info(f"[reminder-worker] skip pid={pid} status={status}")
        return True  # discard

    # idempotency: if already a reminder for this offset, skip
    for r in (p.get("reminders") or []):
        if int(r.get("offset_days", -1)) == offset:
            Log.info(f"[reminder-worker] already reminded pid={pid} offset={offset}")
            return True

    name = safe_decrypt(p.get("name"))
    ref = safe_decrypt(p.get("reference"))
    cur = safe_decrypt(p.get("currency"))
    due_at = p.get("due_at")
    amt = p.get("amount")

    recipients = determine_admin_recipients(p)

    # Send notifications (wrap in try to allow retry)
    subject = f"[Reminder] {name or ref} due on {due_at.date()}"
    body = (
        f"Payable {ref or name} of {cur or ''} {amt} "
        f"is due on {due_at.strftime('%Y-%m-%d %H:%M UTC')} "
        f"(scheduled {offset} day(s) in advance)."
    )
    # notify_email_and_sms(recipients=recipients, subject=subject, body=body)

    # Record reminder + set status to 'notified'
    from datetime import timedelta as _td
    col.update_one(
        {"_id": p["_id"]},
        {
            "$push": {
                "reminders": {
                    "offset_days": offset,
                    "scheduled_for": due_at - _td(days=offset),
                    "sent_at": utcnow(),
                    "channels": ["email", "sms"],
                    "success": True,
                }
            },
            "$set": {"status": encrypt_data("notified"), "updated_at": utcnow()}
        }
    )
    return True

def determine_admin_recipients(payable_doc):
    # Replace with your tenant/Business settings lookup as needed
    return {"emails": ["finance@yourco.com"], "phones": ["+233555000111"]}

def _requeue_with_backoff(r, payload):
    attempts = int(payload.get("attempts", 0)) + 1
    if attempts > MAX_RETRIES:
        Log.info(f"[reminder-worker] max retries exceeded for {payload.get('job_id')}")
        return
    payload["attempts"] = attempts

    now_ts = int(datetime.now(timezone.utc).timestamp())
    next_eta = now_ts + RETRY_DELAY_SEC
    jid = payload["job_id"]

    # write payload & requeue — set payload TTL to end at (next_eta + 1h)
    ttl_seconds = max((next_eta - now_ts) + EXPIRE_GRACE_SEC, 60)
    r.set(JOB_KEY_FMT.format(job_id=jid), json.dumps(payload), ex=int(ttl_seconds))
    r.zadd(ZSET_KEY, {jid: next_eta})
    Log.info(f"[reminder-worker] requeued {jid} attempts={attempts} eta+{RETRY_DELAY_SEC}s ttl={ttl_seconds}")

def _cleanup_expired_jobs(r) -> Dict[str, int]:
    """
    GC: delete all jobs with ETA <= now - 1h.
    Removes payload key, ZSET member, per-payable set link,
    and cleans Mongo 'scheduled_jobs' mirror.
    """
    now_ts = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_ts - EXPIRE_GRACE_SEC

    # fetch candidates up to cap
    rows: List[Tuple[bytes, float]] = r.zrangebyscore(
        ZSET_KEY, "-inf", cutoff, start=0, num=_MAX_PRUNE_PER_CYCLE, withscores=True
    )
    if not rows:
        return {"examined": 0, "pruned": 0}

    pids_map: Dict[str, List[str]] = {}  # pid -> list(jids)
    pipe = r.pipeline(transaction=True)
    pruned = 0

    for member, _score in rows:
        jid = _b2s(member)
        pid = _parse_pid_from_jid(jid)
        pipe.delete(JOB_KEY_FMT.format(job_id=jid))
        pipe.zrem(ZSET_KEY, jid)
        if pid:
            pipe.srem(JOBSET_BY_PAYABLE_FMT.format(pid=pid), jid)
            pids_map.setdefault(pid, []).append(jid)
        pruned += 1

    pipe.execute()

    # Clean Mongo mirrors in bulk
    col = db.get_collection("payables")
    for pid, jids in pids_map.items():
        try:
            col.update_one(
                {"_id": ObjectId(pid)},
                {"$pull": {"scheduled_jobs": {"redis_job_id": {"$in": jids}}}}
            )
        except Exception as e:
            Log.info(f"[reminder-worker] mongo mirror cleanup failed pid={pid}: {e}")

    Log.info(f"[reminder-worker] GC pruned={pruned} (ETA <= now-1h)")
    return {"examined": len(rows), "pruned": pruned}

def run_worker():
    """
    Simple loop:
    - peek next job in ZSET
    - if due, pop up to BATCH_POP with ZPOPMIN
    - process each (safe)
    - periodically GC entries older than ETA+1h
    """
    r = get_redis()
    Log.info("[reminder-worker] STARTED")

    last_cleanup = 0.0

    while True:
        try:
            # periodic GC
            now = time.time()
            if now - last_cleanup >= CLEANUP_EVERY_SEC:
                try:
                    _cleanup_expired_jobs(r)
                except Exception as e:
                    Log.info(f"[reminder-worker] cleanup error: {e}")
                last_cleanup = now

            # Peek earliest
            peek = r.zrange(ZSET_KEY, 0, 0, withscores=True)
            if not peek:
                time.sleep(SLEEP_IDLE_SEC)
                continue

            now_ts = int(datetime.now(timezone.utc).timestamp())
            next_member, next_score = peek[0]
            next_score = int(next_score)

            if next_score > now_ts:
                # Sleep until due or idle interval
                sleep_for = min(max(0, next_score - now_ts), 5)
                time.sleep(max(sleep_for, SLEEP_IDLE_SEC))
                continue

            # Pop a batch of due jobs
            popped = r.zpopmin(ZSET_KEY, BATCH_POP)  # [(member, score), ...]
            if not popped:
                time.sleep(SLEEP_IDLE_SEC)
                continue

            for member, score in popped:
                jid = _b2s(member)

                # load payload
                raw = r.get(JOB_KEY_FMT.format(job_id=jid))
                if not raw:
                    # payload missing, just continue
                    Log.info(f"[reminder-worker] payload missing for jid={jid}")
                    continue

                payload = json.loads(_b2s(raw)) if isinstance(raw, (bytes, bytearray)) else json.loads(raw)
                try:
                    ok = process_job(payload)
                    # cleanup if ok
                    if ok:
                        r.delete(JOB_KEY_FMT.format(job_id=jid))
                        # also remove from per-payable set
                        pid = payload.get("payable_id")
                        if pid:
                            r.srem(JOBSET_BY_PAYABLE_FMT.format(pid=pid), jid)
                except Exception as e:
                    Log.info(f"[reminder-worker] processing failed jid={jid}: {e}")
                    # requeue with backoff
                    _requeue_with_backoff(r, payload)

        except Exception as loop_err:
            Log.info(f"[reminder-worker] loop error: {loop_err}")
            time.sleep(2)  # brief backoff to avoid tight error loop
