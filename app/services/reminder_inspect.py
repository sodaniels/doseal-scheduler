# app/services/reminder_inspect.py
import json
from bson.objectid import ObjectId
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any

from ..utils.crypt import decrypt_data
from ..utils.job_redis import get_redis
from ..extensions.db import db

from ..utils.logger import Log
from ..services.reminder_queue import (
    ZSET_KEY, JOB_KEY_FMT, JOBSET_BY_PAYABLE_FMT
)

# --- small utils ---
def _b2s(x):
    return x.decode("utf-8") if isinstance(x, (bytes, bytearray)) else x

def _ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()

def _load_payload(r, jid: str) -> Dict[str, Any]:
    raw = r.get(JOB_KEY_FMT.format(job_id=jid))
    if not raw:
        return {}
    try:
        return json.loads(_b2s(raw))
    except Exception:
        return {}

# --- main listing helpers ---

def list_next_due(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Earliest 'limit' jobs by ETA from the global ZSET.
    """
    r = get_redis(ZSET_KEY)
    rows: List[Tuple[bytes, float]] = r.zrange(ZSET_KEY, 0, max(0, limit - 1), withscores=True)
    out: List[Dict[str, Any]] = []
    for member, score in rows:
        jid = _b2s(member)
        payload = _load_payload(r, jid)
        out.append({
            "job_id": jid,
            "eta_epoch": int(score),
            "eta_iso": _ts_to_iso(score),
            **payload,  # contains job_id/payable_id/offset_days/attempts/etc.
        })
    return out

def list_jobs_window(start_utc: Optional[datetime], end_utc: Optional[datetime], limit: int = 500) -> List[Dict[str, Any]]:
    """
    Jobs whose ETA is within [start_utc, end_utc].
    Use None for open-ended bounds.
    """
    r = get_redis(ZSET_KEY)
    min_score = "-inf" if start_utc is None else int(start_utc.replace(tzinfo=timezone.utc).timestamp())
    max_score = "+inf" if end_utc is None else int(end_utc.replace(tzinfo=timezone.utc).timestamp())

    # redis-py: zrangebyscore(key, min, max, start=0, num=None, withscores=False)
    rows: List[Tuple[bytes, float]] = r.zrangebyscore(ZSET_KEY, min_score, max_score, start=0, num=limit, withscores=True)
    out: List[Dict[str, Any]] = []
    for member, score in rows:
        jid = _b2s(member)
        payload = _load_payload(r, jid)
        out.append({
            "job_id": jid,
            "eta_epoch": int(score),
            "eta_iso": _ts_to_iso(score),
            **payload,
        })
    return out

def list_jobs_for_payable(payable_id: str) -> List[Dict[str, Any]]:
    """
    All queued jobs for a given payable (from the per-payable SET),
    augmented with their ETA from the global ZSET.
    """
    r = get_redis(ZSET_KEY)
    job_set_key = JOBSET_BY_PAYABLE_FMT.format(pid=payable_id)
    members = r.smembers(job_set_key) or set()
    out: List[Dict[str, Any]] = []
    for m in members:
        jid = _b2s(m)
        score = r.zscore(ZSET_KEY, jid)
        payload = _load_payload(r, jid)
        out.append({
            "job_id": jid,
            "eta_epoch": int(score) if score is not None else None,
            "eta_iso": _ts_to_iso(score) if score is not None else None,
            **payload,
        })
    # sort by ETA (None at end)
    out.sort(key=lambda x: (x["eta_epoch"] is None, x["eta_epoch"]))
    return out

def list_jobs_from_mongo_mirror(business_id: Optional[str] = None, limit_per_payable: int = 100) -> List[Dict[str, Any]]:
    """
    Pulls from Mongo's `scheduled_jobs` mirror for UI/diagnostics.
    Not authoritative if Redis has diverged, but handy for dashboards.
    """
    col = db.get_collection("payables")
    q: Dict[str, Any] = {"scheduled_jobs": {"$exists": True, "$ne": []}}
    if business_id:
        from bson.objectid import ObjectId
        try:
            q["business_id"] = ObjectId(business_id)
        except Exception:
            Log.info(f"[inspect] invalid business_id {business_id}")

    cur = col.find(q, {"scheduled_jobs": 1}).limit(1000)
    out: List[Dict[str, Any]] = []
    for doc in cur:
        pid = str(doc["_id"])
        for j in (doc.get("scheduled_jobs") or [])[:limit_per_payable]:
            out.append({
                "payable_id": pid,
                "job_id": j.get("redis_job_id"),
                "offset_days": j.get("offset_days"),
                "eta_iso": j.get("eta").isoformat() if j.get("eta") else None,
            })
    # sort by eta if present
    out.sort(key=lambda x: (x["eta_iso"] is None, x["eta_iso"]))
    return out

def hydrate_jobs_with_payables(
    jobs: List[Dict[str, Any]],
    fields: Optional[Dict[str, int]] = None
) -> List[Dict[str, Any]]:
    """
    Given a list of job dicts (each with 'payable_id'), attach a 'payable' sub-doc
    with selected fields from Mongo. Encrypted fields are decrypted.

    fields: Mongo projection dict. Defaults to common fields.
    """
    if not jobs:
        return jobs

    # Default projection
    if fields is None:
        fields = {
            "name": 1,
            "reference": 1,
            "currency": 1,
            "status": 1,
            "amount": 1,
            "due_at": 1,
            "business_id": 1,
            "created_by": 1,
        }

    # Collect ObjectIds
    ids = []
    for j in jobs:
        pid = j.get("payable_id")
        try:
            if pid:
                ids.append(ObjectId(pid))
        except Exception:
            # ignore invalid ids
            pass

    if not ids:
        return jobs

    col = db.get_collection("payables")
    docs = list(col.find({"_id": {"$in": ids}}, fields))

    # Build a map of payable_id -> payable_view (with decrypted strings)
    pmap: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        pid = str(d["_id"])
        pmap[pid] = {
            "payable_id": pid,
            "name": decrypt_data(d.get("name")) if d.get("name") else None,
            "reference": decrypt_data(d.get("reference")) if d.get("reference") else None,
            "currency": decrypt_data(d.get("currency")) if d.get("currency") else None,
            "status": decrypt_data(d.get("status")) if d.get("status") else None,
            "amount": decrypt_data(d.get("amount")) if d.get("amount") else None,
            "due_at": d.get("due_at"),
            "business_id": str(d.get("business_id")) if d.get("business_id") else None,
            "created_by": str(d.get("created_by")) if d.get("created_by") else None,
        }

    # Attach payable view to each job
    enriched = []
    for j in jobs:
        pid = j.get("payable_id")
        j2 = dict(j)
        j2["payable"] = pmap.get(pid)  # may be None if not found
        enriched.append(j2)

    return enriched