# app/services/general/reminder_gc.py
from typing import List, Tuple, Dict, Any
import json
from datetime import datetime, timezone

from bson.objectid import ObjectId
from ...utils.job_redis import get_redis
from ...extensions.db import db
from ...utils.logger import Log
from ...services.reminder_queue import (
    ZSET_KEY, JOB_KEY_FMT, JOBSET_BY_PAYABLE_FMT
)

EXPIRE_GRACE_SEC = 3600  # 1 hour after ETA

def _b2s(x):
    return x.decode("utf-8") if isinstance(x, (bytes, bytearray)) else x

def _parse_pid_from_jid(jid: str) -> str | None:
    # jid format: payable:{pid}:off:{d}:at:{eta}
    try:
        parts = jid.split(":")
        return parts[1] if len(parts) >= 2 and parts[0] == "payable" else None
    except Exception:
        return None

def prune_expired_jobs_by_eta(max_to_prune: int = 1000) -> Dict[str, Any]:
    """
    Deletes jobs whose ETA <= (now - 1h).
    Cleans: ZSET member, payload key, per-payable SET link, and Mongo 'scheduled_jobs' mirror.
    Returns stats for logging/monitoring.
    """
    r = get_redis(ZSET_KEY)
    col = db.get_collection("payables")

    now_ts = int(datetime.now(timezone.utc).timestamp())
    cutoff = now_ts - EXPIRE_GRACE_SEC

    # fetch candidates (oldest first) up to max_to_prune
    rows: List[Tuple[bytes, float]] = r.zrangebyscore(ZSET_KEY, "-inf", cutoff, start=0, num=max_to_prune, withscores=True)

    pruned = 0
    examined = len(rows)
    pids: Dict[str, List[str]] = {}  # pid -> [jid,...] for mongo cleanup

    # remove in batches for efficiency
    pipe = r.pipeline(transaction=True)

    for member, _score in rows:
        jid = _b2s(member)
        pid = _parse_pid_from_jid(jid)
        # remove payload (if still there)
        pipe.delete(JOB_KEY_FMT.format(job_id=jid))
        # remove from ZSET
        pipe.zrem(ZSET_KEY, jid)
        # remove per-payable set link
        if pid:
            pipe.srem(JOBSET_BY_PAYABLE_FMT.format(pid=pid), jid)
            pids.setdefault(pid, []).append(jid)
        pruned += 1

    if examined:
        pipe.execute()

    # Clean Mongo mirrors: pull any matching job ids from scheduled_jobs
    for pid, jids in pids.items():
        try:
            col.update_one(
                {"_id": ObjectId(pid)},
                {"$pull": {"scheduled_jobs": {"redis_job_id": {"$in": jids}}}}
            )
        except Exception as e:
            Log.info(f"[reminder-gc] mongo pull failed pid={pid}: {e}")

    Log.info(f"[reminder-gc] examined={examined} pruned={pruned} cutoff<={cutoff}")
    return {"examined": examined, "pruned": pruned, "cutoff": cutoff}
