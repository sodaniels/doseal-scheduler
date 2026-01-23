# services/funding.py
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from bson import ObjectId
from pymongo import ASCENDING, IndexModel
from app.extensions.db import db

from ..utils.agent_balance_keys import keys_for_funding
from ..services.wallet_service import (
    credit_initial_float,
    create_agent_account_with_zero_init,
)

# -------- utils --------
def _now():
    return datetime.now(timezone.utc)

def _money(x) -> str:
    return str(Decimal(str(x)).quantize(Decimal("0.00")))

def _col():
    return db.get_collection("funding_requests")

# -------- indexes (call once at startup) --------
def setup_funding_indexes():
    _col().create_indexes([
        IndexModel([("business_id", ASCENDING), ("created_at", ASCENDING)], name="biz_created"),
        IndexModel([("agent_id", ASCENDING), ("created_at", ASCENDING)], name="agent_created"),
        IndexModel([("status", ASCENDING), ("created_at", ASCENDING)], name="status_created"),
    ])

# -------- API: create + execute in one step --------
def start_funding_request(
    *,
    business_id: str,
    agent_id: str,
    amount,
    created_by: str,
    note: Optional[str] = None
) -> dict:
    """
    1) Create a funding_request doc (PENDING) and get its _id (this is funding_request_id).
    2) Ensure agent account exists with zero-init ledger (idempotent).
    3) Generate idempotency_key and reference from funding_request_id.
    4) Call credit_initial_float; update request status accordingly.
    """
    fr_col = _col()
    ins = fr_col.insert_one({
        "business_id": business_id,
        "agent_id": agent_id,
        "amount": _money(amount),
        "created_by": created_by,
        "note": note,
        "status": "PENDING",
        "attempts": 0,
        "created_at": _now(),
        "updated_at": _now(),
    })
    funding_request_id = str(ins.inserted_id)

    # Ensure account exists + zero init
    create_agent_account_with_zero_init(business_id=business_id, agent_id=agent_id)

    # Build keys
    kp = keys_for_funding(business_id, agent_id, funding_request_id=funding_request_id)

    try:
        fr_col.update_one({"_id": ins.inserted_id}, {"$inc": {"attempts": 1}})
        res = credit_initial_float(
            business_id=business_id,
            agent_id=agent_id,
            amount=amount,
            idempotency_key=kp.idem,
            reference=kp.ref,
        )
        fr_col.update_one(
            {"_id": ins.inserted_id},
            {"$set": {"status": "COMPLETED", "txn_id": res["txn_id"], "idempotency_key": kp.idem, "reference": kp.ref, "updated_at": _now()}}
        )
        return {"funding_request_id": funding_request_id, "idempotency_key": kp.idem, "reference": kp.ref, "txn": res}
    except Exception as e:
        fr_col.update_one(
            {"_id": ins.inserted_id},
            {"$set": {"status": "FAILED", "error": str(e), "idempotency_key": kp.idem, "reference": kp.ref, "updated_at": _now()}}
        )
        raise

# -------- API: execute an existing request by ID (retry-safe) --------
def execute_funding_request_by_id(*, funding_request_id: str) -> dict:
    """
    Use this when the client already knows funding_request_id.
    - If COMPLETED: return existing outcome (idempotent).
    - If FAILED: decide if another attempt is allowed (business rule).
    - If PENDING: execute it now.
    """
    fr_col = _col()
    doc = fr_col.find_one({"_id": ObjectId(funding_request_id)})
    if not doc:
        raise ValueError("Funding request not found")

    business_id = doc["business_id"]
    agent_id = doc["agent_id"]
    amount = Decimal(doc["amount"])

    kp = keys_for_funding(business_id, agent_id, funding_request_id=funding_request_id)

    status = doc.get("status")
    if status == "COMPLETED":
        return {
            "funding_request_id": funding_request_id,
            "idempotency_key": kp.idem,
            "reference": kp.ref,
            "status": "COMPLETED",
            "txn_id": doc.get("txn_id"),
        }

    if status not in ("PENDING", "FAILED"):
        raise RuntimeError(f"Unsupported status {status}")

    # Ensure account exists
    create_agent_account_with_zero_init(business_id=business_id, agent_id=agent_id)

    try:
        fr_col.update_one({"_id": doc["_id"]}, {"$inc": {"attempts": 1}, "$set": {"status": "PENDING", "updated_at": _now()}})
        res = credit_initial_float(
            business_id=business_id,
            agent_id=agent_id,
            amount=amount,
            idempotency_key=kp.idem,
            reference=kp.ref,
        )
        fr_col.update_one({"_id": doc["_id"]}, {"$set": {"status": "COMPLETED", "txn_id": res["txn_id"], "updated_at": _now()}})
        return {"funding_request_id": funding_request_id, "idempotency_key": kp.idem, "reference": kp.ref, "txn": res}
    except Exception as e:
        fr_col.update_one({"_id": doc["_id"]}, {"$set": {"status": "FAILED", "error": str(e), "updated_at": _now()}})
        raise
