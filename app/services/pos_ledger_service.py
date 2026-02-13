# services/pos_ledger_service.py
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional, Iterable, Dict, Any
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import DuplicateKeyError

from ..extensions.db import db
from ..utils.doseal.ensure_index import ensure_index
from ..utils.pos_idempotent_keys import (
    keys_for_stock_hold,
    keys_for_stock_release_expired,
    keys_for_stock_release,
    keys_for_stock_capture
)

# ---------- Utilities ----------
def _now():
    return datetime.now(timezone.utc)

def _as_oid(v) -> ObjectId:
    return v if isinstance(v, ObjectId) else ObjectId(str(v))

def _id_variants(v) -> list:
    """
    Accept str|ObjectId and return both variants for bridging mixed data during migration.
    Prefer normalizing upstream to ObjectId and remove this once everything is consistent.
    """
    out = []
    if isinstance(v, ObjectId):
        out.append(v)
        out.append(str(v))
    else:
        s = str(v)
        out.append(s)
        try:
            out.append(ObjectId(s))
        except Exception:
            pass
    return out

# ---------- Collections ----------
def _stock_ledger():
    return db.get_collection("stock_ledger")
    

def _stock_holds():
    return db.get_collection("stock_holds")

def _idem():
    return db.get_collection("idempotency")

# ---------- Indexes ----------
def setup_indexes(idempotency_ttl_seconds: int = 30 * 24 * 3600):
    # ---- stock_ledger ----
    sl = _stock_ledger()
    ensure_index(sl, IndexModel(
        [("business_id", ASCENDING), ("outlet_id", ASCENDING), ("product_id", ASCENDING),
         ("composite_variant_id", ASCENDING), ("created_at", ASCENDING)],
        name="stock_identity_time"
    ))
    ensure_index(sl, IndexModel(
        [("business_id", ASCENDING), ("outlet_id", ASCENDING), ("product_id", ASCENDING),
         ("created_at", ASCENDING)],
        name="stock_identity_time_no_variant"
    ))
    ensure_index(sl, IndexModel(
        [("reference_type", ASCENDING), ("reference_id", ASCENDING), ("created_at", ASCENDING)],
        name="reference_lookup"
    ))

    # ---- stock_holds ----
    sh = _stock_holds()
    ensure_index(sh, IndexModel(
        [("hold_id", ASCENDING)],
        name="hold_unique",
        unique=True
    ))
    ensure_index(sh, IndexModel(
        [("business_id", ASCENDING), ("outlet_id", ASCENDING), ("status", ASCENDING), ("created_at", ASCENDING)],
        name="holds_by_status"
    ))
    ensure_index(sh, IndexModel(
        [("business_id", ASCENDING), ("cart_id", ASCENDING), ("status", ASCENDING)],
        name="holds_cart_active"
    ))

    # ---- idempotency ----
    idem = _idem()
    ensure_index(idem, IndexModel(
        [("key", ASCENDING)],
        name="idem_key_unique",
        unique=True
    ))
    ensure_index(idem, IndexModel(
        [("created_at", ASCENDING)],
        name="idem_ttl",
        expireAfterSeconds=idempotency_ttl_seconds
    ))

# ---------- Idempotency ----------
def _idempotency_guard(key: str, meta: Optional[dict] = None, session=None):
    try:
        _idem().insert_one({"key": key, "created_at": _now(), "meta": meta or {}}, session=session)
    except DuplicateKeyError:
        # Same operation already recorded — treat as a safe replay.
        raise RuntimeError("IDEMPOTENT_REPLAY")

# ---------- Stock maths ----------
def _sum_on_hand(
    *,
    business_id,
    outlet_id,
    product_id,
    composite_variant_id: Optional[str | ObjectId] = None,
    session=None
) -> float:
    match = {
        "business_id": {"$in": _id_variants(business_id)},
        "outlet_id":   {"$in": _id_variants(outlet_id)},
        "product_id":  {"$in": _id_variants(product_id)},
    }
    if composite_variant_id:
        match["composite_variant_id"] = {"$in": _id_variants(composite_variant_id)}
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "on_hand": {"$sum": "$quantity_delta"}}}
    ]
    agg = list(_stock_ledger().aggregate(pipeline, session=session))
    return float(agg[0]["on_hand"]) if agg else 0.0

def _sum_committed_active(
    *,
    business_id,
    outlet_id,
    product_id,
    composite_variant_id: Optional[str | ObjectId] = None,
    session=None
) -> float:
    match = {
        "business_id": {"$in": _id_variants(business_id)},
        "outlet_id":   {"$in": _id_variants(outlet_id)},
        "product_id":  {"$in": _id_variants(product_id)},
        "status": "ACTIVE",
    }
    if composite_variant_id:
        match["composite_variant_id"] = {"$in": _id_variants(composite_variant_id)}
    pipeline = [
        {"$match": match},
        {"$unwind": "$items"},
        {"$group": {"_id": None, "committed": {"$sum": "$items.qty"}}}
    ]
    agg = list(_stock_holds().aggregate(pipeline, session=session))
    return float(agg[0]["committed"]) if agg else 0.0

# ---------- Public API: stock holds ----------
def place_stock_hold(
    *,
    business_id: str,
    outlet_id: str,
    cashier_id: str,
    cart_id: str,
    items: Iterable[Dict[str, Any]],
    idempotency_key: str,
    purpose: str,
    ref: str,
    expires_in_minutes: int = 15
) -> Dict[str, Any]:
    """
    Reserve stock for a cart (one hold document with multiple line items).
    Each item must include:
      - product_id (preferred) or sku
      - qty (int)
      - optional composite_variant_id
    """
    hold_id = f"stock-hold-{ObjectId()}"
    business_oid = _as_oid(business_id)
    outlet_oid   = _as_oid(outlet_id)
    cashier_oid  = _as_oid(cashier_id)

    # Normalize items (prefer product_id path)
    norm: list[dict] = []
    for it in items:
        qty = int(it["qty"])
        if qty <= 0:
            raise ValueError("Quantity must be positive")
        rec = {"qty": qty}
        if "product_id" in it and it["product_id"]:
            rec["product_id"] = str(it["product_id"])
            if "composite_variant_id" in it and it["composite_variant_id"]:
                rec["composite_variant_id"] = str(it["composite_variant_id"])
        elif "sku" in it and it["sku"]:
            rec["sku"] = str(it["sku"])
        else:
            raise ValueError("Each item must have product_id or sku")
        norm.append(rec)

    with db.client.start_session() as s, s.start_transaction():
        _idempotency_guard(
            idempotency_key,
            {"op": "stock_hold", "business_id": business_oid, "cart_id": cart_id, "ref": ref},
            session=s
        )

        # Availability check per line (product_id path)
        for it in norm:
            if "product_id" not in it:
                # If your deployment uses SKU-driven identity, add that path here.
                raise ValueError("INSUFFICIENT_STOCK: Missing product_id path support in this deployment")
            pid = it["product_id"]
            vid = it.get("composite_variant_id")
            on_hand   = _sum_on_hand(business_id=business_oid, outlet_id=outlet_oid, product_id=pid, composite_variant_id=vid, session=s)
            committed = _sum_committed_active(business_id=business_oid, outlet_id=outlet_oid, product_id=pid, composite_variant_id=vid, session=s)
            available = on_hand - committed
            if available < it["qty"]:
                raise ValueError("INSUFFICIENT_STOCK")

        doc = {
            "hold_id": hold_id,
            "business_id": business_oid,
            "outlet_id": outlet_oid,
            "cashier_id": cashier_oid,
            "cart_id": str(cart_id),
            "items": norm,           # [{product_id?, composite_variant_id?, sku?, qty}]
            "status": "ACTIVE",
            "purpose": purpose,
            "ref": ref,
            "created_at": _now(),
            "updated_at": _now(),
            "expires_at": _now() + timedelta(minutes=expires_in_minutes),
        }
        _stock_holds().insert_one(doc, session=s)

    return {"success": True, "status_code": 200, "hold_id": hold_id}

def capture_stock_hold(
    *,
    business_id: str,
    hold_id: str,
    idempotency_key: str,
    sale_id: Optional[str] = None,
    meta: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Finalize a reserved cart:
      - Append SALE rows (negative quantity) to stock_ledger
      - Mark the hold CAPTURED
    """
    business_oid = _as_oid(business_id)
    with db.client.start_session() as s, s.start_transaction():
        hold = _stock_holds().find_one({"hold_id": hold_id}, session=s)
        if not hold or hold.get("status") != "ACTIVE":
            raise ValueError("Hold not found or not active")
        if hold["business_id"] != business_oid:
            raise ValueError("Business mismatch for hold")

        _idempotency_guard(
            idempotency_key,
            {"op": "stock_capture", "business_id": business_oid, "hold_id": hold_id},
            session=s
        )

        # Post SALE entries
        for it in hold["items"]:
            pid = it.get("product_id")
            if not pid:
                # See comment in place_stock_hold
                raise ValueError("Unsupported SKU-only hold in this deployment")
            qty = int(it["qty"])
            row = {
                "business_id": business_oid,
                "outlet_id": hold["outlet_id"],
                "product_id": ObjectId(pid),
                "user_id": None,
                "user__id": hold["cashier_id"],
                "quantity_delta": -qty,  # SALE -> negative
                "reference_type": "SALE",
                "reference_id": ObjectId(sale_id) if sale_id else None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            if it.get("composite_variant_id"):
                row["composite_variant_id"] = ObjectId(it["composite_variant_id"])
            if meta:
                row["meta"] = meta
            _stock_ledger().insert_one(row, session=s)

        _stock_holds().update_one(
            {"_id": hold["_id"]},
            {"$set": {"status": "CAPTURED", "captured_sale_id": ObjectId(sale_id) if sale_id else None, "updated_at": _now()}},
            session=s
        )

    return {"success": True, "status_code": 200, "hold_id": hold_id, "captured": True}

def release_stock_hold(
    *,
    business_id: str,
    hold_id: str,
    idempotency_key: str,
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Cancel/timeout a reservation:
      - Mark hold RELEASED
      - No ledger writes (reservation only)
    """
    business_oid = _as_oid(business_id)
    with db.client.start_session() as s, s.start_transaction():
        hold = _stock_holds().find_one({"hold_id": hold_id}, session=s)
        if not hold or hold.get("status") != "ACTIVE":
            raise ValueError("Hold not found or not active")
        if hold["business_id"] != business_oid:
            raise ValueError("Business mismatch for hold")

        _idempotency_guard(
            idempotency_key,
            {"op": "stock_release", "business_id": business_oid, "hold_id": hold_id, "reason": reason},
            session=s
        )
        _stock_holds().update_one(
            {"_id": hold["_id"]},
            {"$set": {"status": "RELEASED", "release_reason": reason, "updated_at": _now()}},
            session=s
        )

    return {"success": True, "status_code": 200, "hold_id": hold_id, "released": True}

def release_expired_stock_holds(
    *,
    business_id: str,
    older_than_minutes: int = 15
) -> Dict[str, Any]:
    """
    Sweep ACTIVE holds whose expires_at has passed; uses idempotent single-hold releases.
    """

    business_oid = _as_oid(business_id)
    now = _now()

    q = {
        "business_id": {"$in": _id_variants(business_oid)},
        "status": "ACTIVE",
        "expires_at": {"$lte": now}
    }
    to_release = list(_stock_holds().find(q).limit(200))  # batch size cap
    released = 0
    for h in to_release:
        k = keys_for_stock_release_expired(business_id, h["hold_id"])
        try:
            release_stock_hold(
                business_id=business_id,
                hold_id=h["hold_id"],
                idempotency_key=k.idem,
                reason="timeout"
            )
            released += 1
        except Exception:
            # Race with another worker / already released — ignore.
            pass

    return {"success": True, "status_code": 200, "released": released}

# ---------- helpers ----------
def get_available_for_product(
    *,
    business_id: str,
    outlet_id: str,
    product_id: str,
    composite_variant_id: Optional[str] = None
) -> Dict[str, float]:
    """
    Returns:
      {
        "on_hand": float,
        "committed": float,
        "available_to_reserve": float
      }
    """
    business_oid = _as_oid(business_id)
    outlet_oid   = _as_oid(outlet_id)
    on_hand   = _sum_on_hand(business_id=business_oid, outlet_id=outlet_oid, product_id=product_id, composite_variant_id=composite_variant_id)
    committed = _sum_committed_active(business_id=business_oid, outlet_id=outlet_oid, product_id=product_id, composite_variant_id=composite_variant_id)
    return {
        "on_hand": on_hand,
        "committed": committed,
        "available_to_reserve": on_hand - committed
    }
