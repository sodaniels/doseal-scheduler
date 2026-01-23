# services/wallet.py
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from bson import ObjectId
from pymongo import (
    ASCENDING, DESCENDING, 
    ReturnDocument, IndexModel
)
from typing import Optional, Iterable, Literal, Tuple, Dict, Any, List

from pymongo.errors import DuplicateKeyError
from ..extensions.db import db

# ---------- Utilities ----------
def _now():
    return datetime.now(timezone.utc)

def _dec(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))

# Account ID builders (centralized)
def _treasury_acct(business_id: str) -> str:
    return f"BUSINESS_TREASURY:{business_id}"

def _agent_acct(business_id: str, agent_id: str) -> str:
    return f"AGENT_FLOAT:{business_id}:{agent_id}"

def _clearing_acct(business_id: str) -> str:
    return f"CLEARING_PAYOUTS:{business_id}"

def _opening_balance_acct(business_id: str) -> str:
    return f"OPENING_BALANCE:{business_id}"

# Collection getters
def _accounts():
    return db.get_collection("accounts")

def _ledger():
    return db.get_collection("ledger")

def _holds():
    return db.get_collection("holds")

def _idem():
    return db.get_collection("idempotency")

# --- add near other collection getters ---
def _wallet_state():
    return db.get_collection("wallet_state")


# ---------- Indexes (call once at startup) ----------
def setup_indexes(idempotency_ttl_seconds: int = 30 * 24 * 3600):
    # Accounts
    _accounts().create_index([("account_id", ASCENDING)], unique=True)
    _accounts().create_index([("business_id", ASCENDING)])
    _accounts().create_index([("owner_id", ASCENDING)])
    _accounts().create_index([("type", ASCENDING)])

    # Ledger
    _ledger().create_index([("txn_id", ASCENDING)], unique=True)
    _ledger().create_index([("business_id", ASCENDING), ("created_at", ASCENDING)])
    _ledger().create_index([("debit_account", ASCENDING)])
    _ledger().create_index([("credit_account", ASCENDING)])
    
    #seed account
    # Wallet state (one row per business)
    _wallet_state().create_index([("business_id", ASCENDING)], unique=True)

    # Holds
    _holds().create_index([("hold_id", ASCENDING)], unique=True)
    _holds().create_index([("business_id", ASCENDING), ("account_id", ASCENDING), ("status", ASCENDING)])

    # Idempotency
    _idem().create_index([("key", ASCENDING)], unique=True)
    _idem().create_indexes([
        IndexModel([("created_at", ASCENDING)], name="created_at_ttl", expireAfterSeconds=idempotency_ttl_seconds)
    ])

# ---------- Core helpers ----------
def _ensure_account(
    *,
    business_id: str,
    account_id: str,
    currency: str = "GBP",
    owner_id: Optional[str] = None,
    type_: str = "AGENT_FLOAT",
    session=None
):
    doc = {
        "business_id": ObjectId(business_id),
        "account_id": account_id,
        "currency": currency,
        "owner_id": ObjectId(owner_id), 
        "type": type_,
        "settled": "0.00",
        "available": "0.00",
        "version": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _accounts().update_one({"account_id": account_id}, {"$setOnInsert": doc}, upsert=True, session=session)

def _get_account(account_id: str, session=None):
    acc = _accounts().find_one({"account_id": account_id}, session=session)
    if not acc:
        raise ValueError(f"Account {account_id} not found")
    return acc

def _idempotency_guard(key: str, meta: Optional[dict] = None, session=None):
    try:
        _idem().insert_one({"key": key, "created_at": _now(), "meta": meta or {}}, session=session)
    except DuplicateKeyError:
        raise RuntimeError("IDEMPOTENT_REPLAY")

def _post_ledger(
    *,
    business_id: str,
    txn_id: str,
    debit_acct: str,
    credit_acct: str,
    amount: Decimal,
    currency: str = "GBP",
    meta: Optional[dict] = None,
    session=None
):
    entry = {
        "business_id": business_id,
        "txn_id": txn_id,
        "debit_account": debit_acct,
        "credit_account": credit_acct,
        "amount": str(amount),
        "currency": currency,
        "created_at": _now(),
        "meta": meta or {}
    }
    _ledger().insert_one(entry, session=session)

def _apply_balance_delta(
    *,
    account_id: str,
    delta_settled: Decimal = Decimal("0"),
    delta_available: Decimal = Decimal("0"),
    session=None
):
    acc = _get_account(account_id, session=session)
    settled = Decimal(acc["settled"]) + delta_settled
    available = Decimal(acc["available"]) + delta_available
    if settled < 0 or available < 0:
        raise ValueError("Insufficient funds")

    updated = _accounts().find_one_and_update(
        {"_id": acc["_id"], "version": acc["version"]},
        {"$set": {
            "settled": str(settled),
            "available": str(available),
            "updated_at": _now(),
        }, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
        session=session
    )
    if not updated:
        raise RuntimeError("OPTIMISTIC_LOCK_FAILED")
    return updated

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _collection(name: str):
    return db.get_collection(name)

def _id_variants(v: Any) -> list:
    """
    Accepts str | ObjectId and returns both variants when possible,
    so queries work even if some collections store str and others ObjectId.
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

def _apply_time_range(match: dict, field: str, date_from: Optional[datetime], date_to: Optional[datetime]):
    if date_from or date_to:
        cond = {}
        if date_from: cond["$gte"] = date_from
        if date_to:   cond["$lt"]  = date_to
        match[field] = cond

def _cursor_filter(after: Optional[str], sort_dir: int) -> Tuple[dict, Optional[ObjectId]]:
    """
    Keyset pagination on _id. If sort_dir == DESCENDING, use _id < after.
    If sort_dir == ASCENDING,  use _id > after.
    """
    if not after:
        return {}, None
    try:
        oid = ObjectId(after)
    except Exception:
        return {}, None
    if sort_dir == DESCENDING:
        return {"_id": {"$lt": oid}}, oid
    return {"_id": {"$gt": oid}}, oid

def _page_result(items: List[dict], limit: int) -> Dict[str, Any]:
    """
    Standard response shape with `next_after` cursor.
    """
    next_after = None
    if len(items) == limit:
        next_after = str(items[-1]["_id"])
    # stringify _id for client friendliness
    for it in items:
        it["_id"] = str(it["_id"])
        it["business_id"] = str(it["business_id"])
        it["owner_id"] = str(it["owner_id"])
    return {"items": items, "next_after": next_after}
# ---------- Public operations (ALL require business_id) ----------
def credit_initial_float(
    *,
    business_id: str,
    agent_id: str,
    amount,
    idempotency_key: str,
    reference: Optional[str] = None
):
    """
    Business -> Agent initial credit (increases agent settled & available).
    If amount == 0, we still write a ledger row for auditability (no balance change).
    """
    amt = _dec(amount)
    business_acct = _treasury_acct(business_id)
    agent_acct = _agent_acct(business_id, agent_id)
    
    business_id = ObjectId(business_id)
    agent_id = ObjectId(agent_id)

    with db.client.start_session() as s, s.start_transaction():
        _ensure_account(business_id=business_id, account_id=business_acct, owner_id=business_id, type_="TREASURY", session=s)
        _ensure_account(business_id=business_id, account_id=agent_acct,   owner_id=agent_id,   type_="AGENT_FLOAT", session=s)

        _idempotency_guard(
            idempotency_key,
            {"op": "credit_initial", "business_id": business_id, "agent_id": agent_id, "amount": str(amt), "reference": reference},
            session=s
        )
        
        txn_id = f"init-{ObjectId()}"
        _post_ledger(
            business_id=business_id,
            txn_id=txn_id,
            debit_acct=business_acct,
            credit_acct=agent_acct,
            amount=amt,
            meta={"reference": reference} if reference else None,
            session=s
        )

        if amt != Decimal("0.00"):
            _apply_balance_delta(account_id=business_acct, delta_settled=-amt, delta_available=-amt, session=s)
            _apply_balance_delta(account_id=agent_acct,    delta_settled= amt, delta_available= amt, session=s)

    return {"success": True, "status_code": 200, "txn_id": txn_id, "agent_account": agent_acct}

def create_agent_account_with_zero_init(*, business_id: str, agent_id: str):
    """
    Ensures the agent account exists and writes a zero-amount initial credit for audit.
    Safe to call multiple times thanks to idempotency.
    """
    from ..utils.agent_balance_keys import keys_for_init0  # local import to avoid circulars when packaging
    kp = keys_for_init0(business_id, agent_id)

    try:
        return credit_initial_float(
            business_id=business_id,
            agent_id=agent_id,
            amount=0.0,
            idempotency_key=kp.idem,
            reference=kp.ref,
        )
    except RuntimeError as e:
        if str(e) == "IDEMPOTENT_REPLAY":
            return {
                "status": "ok",
                "message": "Account already initialized",
                "agent_account": _agent_acct(business_id, agent_id)
            }
        raise


def place_hold(
    *,
    business_id: str,
    agent_id: str,
    amount,
    idempotency_key: str,
    purpose: str,
    ref: str
):
    """
    Authorization step: reduce AVAILABLE only; create HOLD record.
    """
    amt = _dec(amount)
    agent_acct = _agent_acct(business_id, agent_id)
    hold_id = f"hold-{ObjectId()}"

    with db.client.start_session() as s, s.start_transaction():
        _ensure_account(business_id=business_id, account_id=agent_acct, owner_id=agent_id, type_="AGENT_FLOAT", session=s)
        _idempotency_guard(
            idempotency_key,
            {"op": "hold", "business_id": business_id, "agent_id": agent_id, "amount": str(amt), "ref": ref},
            session=s
        )
        
        business_id = ObjectId(business_id)

        _apply_balance_delta(account_id=agent_acct, delta_available=-amt, session=s)
        _holds().insert_one({
            "hold_id": hold_id,
            "business_id": business_id,
            "account_id": agent_acct,
            "agent_id": ObjectId(agent_id),
            "amount": str(amt),
            "currency": "GBP",
            "status": "ACTIVE",
            "purpose": purpose,
            "ref": ref,
            "created_at": _now(),
            "updated_at": _now(),
        }, session=s)

    return {
        "status": "ok", 
        "success":True, 
        "status_code":200, 
        "hold_id": hold_id, 
        "account_id": agent_acct, 
        "amount": str(amt)
    }

def capture_hold(
    *,
    business_id: str,
    hold_id: str,
    idempotency_key: str,
    payout_network_account: Optional[str] = None,
    meta: Optional[dict] = None
):
    """
    Success path: post double-entry (agent -> clearing), reduce SETTLED, mark hold captured.
    AVAILABLE was reduced at place_hold time.
    """
    clearing_acct = payout_network_account or _clearing_acct(business_id)

    with db.client.start_session() as s, s.start_transaction():
        
        business_id = ObjectId(business_id)
        
        hold = _holds().find_one({"hold_id": hold_id}, session=s)
        if not hold or hold["status"] != "ACTIVE":
            raise ValueError("Hold not found or not active")
        if hold["business_id"] != business_id:
            raise ValueError("Business mismatch for hold")

        _ensure_account(business_id=business_id, account_id=clearing_acct, owner_id=business_id, type_="CLEARING", session=s)
        _idempotency_guard(idempotency_key, {"op": "capture", "hold_id": hold_id, "business_id": business_id}, session=s)

        amt = Decimal(hold["amount"])
        agent_acct = hold["account_id"]

        txn_id = f"cap-{ObjectId()}"
        _post_ledger(
            business_id=business_id,
            txn_id=txn_id,
            debit_acct=agent_acct,
            credit_acct=clearing_acct,
            amount=amt,
            meta=(meta or {}) | {"hold_id": hold_id},
            session=s
        )

        _apply_balance_delta(account_id=agent_acct,    delta_settled=-amt, session=s)
        _apply_balance_delta(account_id=clearing_acct, delta_settled= amt, delta_available= amt, session=s)

        _holds().update_one({"_id": hold["_id"]}, {"$set": {"status": "CAPTURED", "captured_txn_id": txn_id, "updated_at": _now()}}, session=s)

    return {"status": "ok", "status_code": 200, "success": True, "txn_id": txn_id}

def release_hold(*, business_id: str, hold_id: str, idempotency_key: str):
    """
    Failure/timeout path: restore AVAILABLE; mark hold RELEASED.
    """
    with db.client.start_session() as s, s.start_transaction():
        hold = _holds().find_one({"hold_id": hold_id}, session=s)
        if not hold or hold["status"] != "ACTIVE":
            raise ValueError("Hold not found or not active")
        if hold["business_id"] != business_id:
            raise ValueError("Business mismatch for hold")
        
        business_id = ObjectId(business_id)

        _idempotency_guard(idempotency_key, {"op": "release", "hold_id": hold_id, "business_id": business_id}, session=s)

        amt = Decimal(hold["amount"])
        _apply_balance_delta(account_id=hold["account_id"], delta_available=amt, session=s)
        _holds().update_one({"_id": hold["_id"]}, {"$set": {"status": "RELEASED", "updated_at": _now()}}, session=s)

    return {
        "status": "ok", 
        "success":True, 
        "status_code":200, 
        "hold_id": hold_id
    }

def refund_capture(*, business_id: str, original_txn_id: str, idempotency_key: str, reason: str):
    """
    Optional: reverse of capture (policy dependent).
    """
    with db.client.start_session() as s, s.start_transaction():
        _idempotency_guard(idempotency_key, {"op": "refund", "orig": original_txn_id, "business_id": business_id}, session=s)

        business_id = ObjectId(business_id)
        
        entry = _ledger().find_one({"txn_id": original_txn_id}, session=s)
        if not entry:
            raise ValueError("Original transaction not found")
        if entry["business_id"] != business_id:
            raise ValueError("Business mismatch for transaction")

        amt = Decimal(entry["amount"])
        agent_acct = entry["debit_account"]
        clearing_acct = entry["credit_account"]

        txn_id = f"refund-{ObjectId()}"
        _post_ledger(
            business_id=business_id,
            txn_id=txn_id,
            debit_acct=clearing_acct,
            credit_acct=agent_acct,
            amount=amt,
            meta={"refund_of": original_txn_id, "reason": reason},
            session=s
        )

        _apply_balance_delta(account_id=clearing_acct, delta_settled=-amt, delta_available=-amt, session=s)
        _apply_balance_delta(account_id=agent_acct,    delta_settled= amt,  delta_available= amt, session=s)

    return {"status": "ok", "status_code": 200, "success": True, "txn_id": txn_id}


def list_accounts(
    *,
    business_id: Any,
    owner_id: Optional[Any] = None,                 # filter by agent/user that owns the account
    type_: Optional[str] = None,                    # "TREASURY" | "AGENT_FLOAT" | "CLEARING" | ...
    limit: int = 50,
    after: Optional[str] = None,                    # cursor (_id)
    sort: Literal["desc","asc"] = "desc",
) -> Dict[str, Any]:
    """
    List accounts for a business with optional filters and cursor pagination.
    """
    q = {"business_id": {"$in": _id_variants(business_id)}}
    if owner_id is not None:
        q["owner_id"] = {"$in": _id_variants(owner_id)}
    if type_:
        q["type"] = type_

    sort_dir = DESCENDING if sort == "desc" else ASCENDING
    cur_filter, _ = _cursor_filter(after, sort_dir)
    q.update(cur_filter)

    cursor = _collection("accounts").find(q).sort([("_id", sort_dir)]).limit(limit)
    return _page_result(list(cursor), limit)

# ---------- HOLDS ----------

def list_holds(
    *,
    business_id: Any,
    agent_id: Optional[Any] = None,
    account_id: Optional[str] = None,
    status: Optional[Iterable[str]] = None,         # e.g., ["ACTIVE"] or ["CAPTURED","RELEASED"]
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 100,
    after: Optional[str] = None,
    sort: Literal["desc","asc"] = "desc",
) -> Dict[str, Any]:
    """
    List holds for a business with filters and cursor pagination.
    """
    q = {"business_id": {"$in": _id_variants(business_id)}}
    if agent_id is not None:
        q["agent_id"] = {"$in": _id_variants(agent_id)}
    if account_id:
        q["account_id"] = account_id
    if status:
        q["status"] = {"$in": list(status)}

    _apply_time_range(q, "created_at", date_from, date_to)

    sort_dir = DESCENDING if sort == "desc" else ASCENDING
    cur_filter, _ = _cursor_filter(after, sort_dir)
    q.update(cur_filter)

    cursor = _collection("holds").find(q).sort([("_id", sort_dir)]).limit(limit)
    return _page_result(list(cursor), limit)

def get_hold_by_id(hold_id: str) -> Optional[dict]:
    """
    Fetch a single hold by its hold_id.
    """
    doc = _collection("holds").find_one({"hold_id": hold_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc

# ---------- LEDGER ----------

def list_ledger_entries(
    *,
    business_id: Any,
    account_id: Optional[str] = None,               # if provided, returns both debit and credit rows for this account
    txn_id: Optional[str] = None,                   # exact lookup for a specific transaction
    role: Optional[Literal["debit","credit"]] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 200,
    after: Optional[str] = None,
    sort: Literal["desc","asc"] = "desc",
) -> Dict[str, Any]:
    """
    List ledger rows for a business with common filters and cursor pagination.

    - If `txn_id` is given, it overrides other filters.
    - If `account_id` is given:
        - with role=None: includes rows where account is either debit OR credit
        - with role="debit"/"credit": filters on that side only
    """
    if txn_id:
        doc = _collection("ledger").find_one({"txn_id": txn_id})
        if not doc:
            return {"items": [], "next_after": None}
        doc["_id"] = str(doc["_id"])
        return {"items": [doc], "next_after": None}

    q = {"business_id": {"$in": _id_variants(business_id)}}

    if account_id:
        if role == "debit":
            q["debit_account"] = account_id
        elif role == "credit":
            q["credit_account"] = account_id
        else:
            q["$or"] = [{"debit_account": account_id}, {"credit_account": account_id}]

    _apply_time_range(q, "created_at", date_from, date_to)

    sort_dir = DESCENDING if sort == "desc" else ASCENDING
    cur_filter, _ = _cursor_filter(after, sort_dir)
    q.update(cur_filter)

    cursor = _collection("ledger").find(q).sort([("_id", sort_dir)]).limit(limit)
    return _page_result(list(cursor), limit)

def get_ledger_by_txn_id(txn_id: str) -> Optional[dict]:
    """
    Fetch a single ledger transaction by its txn_id.
    """
    doc = _collection("ledger").find_one({"txn_id": txn_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc
def _apply_balance_delta_maybe_negative(
    *,
    account_id: str,
    delta_settled: Decimal = Decimal("0"),
    delta_available: Decimal = Decimal("0"),
    allow_negative: bool = False,
    session=None
):
    acc = _get_account(account_id, session=session)
    settled = Decimal(acc["settled"]) + delta_settled
    available = Decimal(acc["available"]) + delta_available

    if not allow_negative and (available < 0 or settled < 0):
        raise ValueError("Insufficient funds")

    updated = _accounts().find_one_and_update(
        {"_id": acc["_id"], "version": acc["version"]},
        {"$set": {
            "settled": str(settled),
            "available": str(available),
            "updated_at": _now(),
        }, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
        session=session
    )
    if not updated:
        raise RuntimeError("OPTIMISTIC_LOCK_FAILED")
    return updated

# --- Add the actual top-up operation ---
def topup_treasury_opening_balance(
    *,
    business_id: str,
    amount,
    idempotency_key: str,
    reference: Optional[str] = None
):
    """
    One-time or repeated top-up of BUSINESS_TREASURY from an OPENING_BALANCE account.
    Keeps double-entry intact. Opening balance is allowed to go negative.
    """
    amt = _dec(amount)
    treasury = _treasury_acct(business_id)
    opening  = _opening_balance_acct(business_id)
    business_id = ObjectId(business_id)

    with db.client.start_session() as s, s.start_transaction():
        _ensure_account(business_id=business_id, account_id=treasury, owner_id=business_id, type_="TREASURY", session=s)
        _ensure_account(business_id=business_id, account_id=opening,  owner_id=business_id, type_="OPENING_BALANCE", session=s)

        _idempotency_guard(
            idempotency_key,
            {"op": "treasury_topup", "business_id": business_id, "amount": str(amt), "reference": reference},
            session=s
        )

        txn_id = f"topup-{ObjectId()}"
        _post_ledger(
            business_id=business_id,
            txn_id=txn_id,
            debit_acct=opening,          # opening balance down (can be negative)
            credit_acct=treasury,        # treasury up
            amount=amt,
            meta={"reference": reference} if reference else None,
            session=s
        )

        # Allow negative on opening balance only
        _apply_balance_delta_maybe_negative(account_id=opening,  delta_settled=-amt, allow_negative=True, session=s)
        _apply_balance_delta_maybe_negative(account_id=treasury, delta_settled= amt,  delta_available= amt, session=s)

    return {"status": "ok", "txn_id": txn_id}

# --- add this new function near your top-up helpers ---
def seed_treasury_once_opening_balance(
    *,
    business_id: str,
    amount,
    seeded_by: str,                  # who/what seeded (admin email/user id, or "system")
    idempotency_key: Optional[str] = None,
    reference: Optional[str] = None
):
    """
    Seed the business treasury ONCE with an opening top-up.
    Safe to call multiple times: subsequent calls are NOOPs.

    Writes:
      - Ledger: OPENING_BALANCE:{biz} -> BUSINESS_TREASURY:{biz}
      - Accounts: treasury up (settled & available), opening down (can go negative)
      - wallet_state: {business_id, seeded=True, seed_txn_id, seeded_at, seeded_by}

    Idempotency:
      Pass a stable key (see keys_for_treasury_seed) or we default to "seed:{biz}".
    """
    amt = _dec(amount)
    treasury = _treasury_acct(business_id)
    opening  = _opening_balance_acct(business_id)
    idem_key = idempotency_key or f"seed:{business_id}"
    meta = {"reference": reference, "seed": True, "seeded_by": seeded_by}
    
    business_id = ObjectId(business_id)

    with db.client.start_session() as s, s.start_transaction():
        # If already seeded, short-circuit (NOOP)
        state = _wallet_state().find_one({"business_id": business_id}, session=s)
        if state and state.get("seeded") is True:
            return {
                "status": False,
                "status_code": 409,
                "reason": "already_seeded",
                "seed_txn_id": state.get("seed_txn_id"),
                "seeded_at": state.get("seeded_at"),
            }

        # Ensure accounts exist
        _ensure_account(business_id=business_id, account_id=treasury, owner_id=business_id, type_="TREASURY", session=s)
        _ensure_account(business_id=business_id, account_id=opening,  owner_id=business_id, type_="OPENING_BALANCE", session=s)

        # Idempotency guard (protects against concurrent seed attempts)
        _idempotency_guard(idem_key, {"op": "treasury_seed", "business_id": business_id, "amount": str(amt), **meta}, session=s)

        # Post ledger & balance deltas
        txn_id = f"seed-{ObjectId()}"
        _post_ledger(
            business_id=business_id,
            txn_id=txn_id,
            debit_acct=opening,      # opening can go negative
            credit_acct=treasury,    # treasury increases
            amount=amt,
            meta=meta,
            session=s
        )
        _apply_balance_delta_maybe_negative(account_id=opening,  delta_settled=-amt, allow_negative=True, session=s)
        _apply_balance_delta_maybe_negative(account_id=treasury, delta_settled= amt,  delta_available= amt, session=s)

        # Mark as seeded (upsert; unique index on business_id ensures single-row)
        _wallet_state().update_one(
            {"business_id": business_id},
            {"$set": {
                "business_id": business_id,
                "seeded": True,
                "seed_txn_id": txn_id,
                "seeded_at": _now(),
                "seeded_by": ObjectId(seeded_by),
                "updated_at": _now(),
            }, "$setOnInsert": {
                "created_at": _now(),
            }},
            upsert=True,
            session=s
        )

    return {"status": "ok","status_code": 200, "success":True, "txn_id": txn_id}


def get_agent_account(business_id, agent_id):
    
    
    acct_id = f"AGENT_FLOAT:{business_id}:{agent_id}"
    account = db.get_collection("accounts").find_one({"account_id": acct_id})
    
    return account






