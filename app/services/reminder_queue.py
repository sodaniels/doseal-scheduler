# app/services/reminder_queue.py
import json
from typing import List
from datetime import datetime, timedelta, timezone
from bson.objectid import ObjectId

from app.extensions.db import db
from app.utils.logger import Log
from ..utils.job_redis import get_redis, set_redis_with_expiry

RETRY_DELAY_SEC = 300
MAX_RETRIES = 12

# ---- Redis keys ----
ZSET_KEY = "sched:payable_reminders"                    # score = ETA (epoch), member = job_id
JOB_KEY_FMT = "sched:job:{job_id}"                      # payload key
JOBSET_BY_PAYABLE_FMT = "sched:jobs_by_payable:{pid}"   # per-payable job ids

# ---- Expiry policy ----
TTL_AFTER_ETA_SEC = 3600   # keep payload 1 hour beyond ETA
MIN_TTL_SEC       = 60     # safety guard

# ---- Time helpers ----
def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

# ---- Deterministic Job ID (idempotent) ----
def _job_id(payable_id: str, offset_days: int, eta_epoch: int) -> str:
    # deterministic (no random suffix) => safe to re-call without duplicates
    return f"payable:{payable_id}:off:{offset_days}:at:{eta_epoch}"

def schedule_reminder_jobs(payable_id: str, due_at: datetime, offsets_days: List[int]):
    """
    Idempotent scheduling.
    - Adds (job_id -> payload) with TTL = (ETA - now) + 1h
    - Adds job_id to global ZSET and per-payable SET (NX to prevent dupes)
    - Mirrors the schedule into Mongo for UI
    """
    r = get_redis(ZSET_KEY)
    col = db.get_collection("payables")

    due_at_utc = to_utc(due_at)
    now_ts = int(utcnow().timestamp())
    unique_offsets = sorted({int(x) for x in (offsets_days or [])})

    scheduled_jobs = []
    for d in unique_offsets:
        eta_dt = due_at_utc - timedelta(days=d)
        if eta_dt <= utcnow():
            Log.info(f"[reminder_queue] skip offset={d}, eta {eta_dt.isoformat()} in past")
            continue

        eta_epoch = int(eta_dt.timestamp())
        jid = _job_id(payable_id, d, eta_epoch)
        key = JOB_KEY_FMT.format(job_id=jid)

        ttl_seconds = max((eta_epoch - now_ts) + TTL_AFTER_ETA_SEC, MIN_TTL_SEC)
        payload = {
            "job_id": jid,
            "payable_id": payable_id,
            "offset_days": d,
            "eta_epoch": eta_epoch,
            "attempts": 0,
        }

        # store/refresh payload with TTL ending ~1h after ETA
        set_redis_with_expiry(key, int(ttl_seconds), json.dumps(payload))

        # insert into ZSET/SET only if not there already
        already = r.zscore(ZSET_KEY, jid)
        if already is None:
            pipe = r.pipeline(transaction=True)
            pipe.zadd(ZSET_KEY, {jid: eta_epoch}, nx=True)
            pipe.sadd(JOBSET_BY_PAYABLE_FMT.format(pid=payable_id), jid)
            pipe.execute()
            Log.info(f"[reminder_queue] scheduled pid={payable_id} off={d} eta={eta_dt.isoformat()} jid={jid} ttl={ttl_seconds}s")
        else:
            Log.info(f"[reminder_queue] exists jid={jid}; refreshed TTL")

        scheduled_jobs.append({"offset_days": d, "eta": eta_dt, "redis_job_id": jid})

    if scheduled_jobs:
        col.update_one(
            {"_id": ObjectId(payable_id)},
            {"$set": {"scheduled_jobs": scheduled_jobs, "updated_at": utcnow()}}
        )

