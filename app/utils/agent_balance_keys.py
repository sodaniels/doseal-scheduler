# services/keys.py
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, re, uuid
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class KeyPair:
    """Pair of values you pass to wallet ops."""
    idem: str  # idempotency_key
    ref: str   # human-readable reference (goes to ledger meta)

# -------- utils --------
SAFE_CHARS = re.compile(r"[^a-zA-Z0-9:_\-\.]")

def _sanitize(part: str) -> str:
    s = str(part).strip().replace(" ", "-").lower()
    return SAFE_CHARS.sub("", s)

def _short_hash(payload: dict, length: int = 24) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:length]

def _money(x) -> str:
    return str(Decimal(str(x)).quantize(Decimal("0.00")))

# -------- key builders --------
def keys_for_init0(business_id: str, agent_id: str) -> KeyPair:
    biz = _sanitize(business_id); ag = _sanitize(agent_id)
    return KeyPair(idem=f"init0:{biz}:{ag}", ref=f"account-init:{biz}:{ag}")

def keys_for_funding(
    business_id: str,
    agent_id: str,
    funding_request_id: Optional[str] = None,
    amount: Optional[float | str] = None,
) -> KeyPair:
    biz = _sanitize(business_id); ag = _sanitize(agent_id)
    if funding_request_id:
        req = _sanitize(funding_request_id)
        return KeyPair(idem=f"fund:{biz}:{ag}:{req}", ref=f"funding:{biz}:{ag}:{req}")
    # Fallback (deterministic hash if you truly have no external ID)
    h = _short_hash({"op":"fund","business_id":biz,"agent_id":ag,"amount":_money(amount or 0)})
    return KeyPair(idem=f"fund:{biz}:{ag}:{h}", ref=f"funding:{biz}:{ag}:{h}")

def keys_for_hold(business_id: str, agent_id: str, client_ref: str, amount: float | str) -> KeyPair:
    biz = _sanitize(business_id); ag = _sanitize(agent_id); cref = _sanitize(client_ref)
    h = _short_hash({"op":"hold","biz":biz,"ag":ag,"ref":cref,"amt":_money(amount)})
    return KeyPair(idem=f"hold:{biz}:{ag}:{cref}:{h}", ref=f"hold:{biz}:{ag}:{cref}")

def keys_for_capture(business_id: str, hold_id: str) -> KeyPair:
    biz = _sanitize(business_id); hid = _sanitize(hold_id)
    return KeyPair(idem=f"cap:{biz}:{hid}", ref=f"capture:{biz}:{hid}")

def keys_for_release(business_id: str, hold_id: str) -> KeyPair:
    biz = _sanitize(business_id); hid = _sanitize(hold_id)
    return KeyPair(idem=f"rel:{biz}:{hid}", ref=f"release:{biz}:{hid}")

def keys_for_refund(business_id: str, original_txn_id: str, reason: Optional[str] = None) -> KeyPair:
    biz = _sanitize(business_id); tx = _sanitize(original_txn_id)
    if reason:
        r = _sanitize(reason)
        return KeyPair(idem=f"refund:{biz}:{tx}:{r}", ref=f"refund:{biz}:{tx}:{r}")
    return KeyPair(idem=f"refund:{biz}:{tx}", ref=f"refund:{biz}:{tx}")

# Optional: random client-visible request ID (persist before use!)
def new_random_funding_keys(business_id: str, agent_id: str) -> KeyPair:
    req = uuid.uuid4().hex[:16]
    return keys_for_funding(business_id, agent_id, funding_request_id=req)

# Optional: top-up keys (for OPENING_BALANCE → TREASURY topups)
def keys_for_treasury_topup(business_id: str, topup_id: str) -> KeyPair:
    biz = _sanitize(business_id); tid = _sanitize(topup_id)
    return KeyPair(idem=f"topup:{biz}:{tid}", ref=f"treasury-topup:{biz}:{tid}")


# --- add near other key builders ---
def keys_for_treasury_seed(business_id: str) -> KeyPair:
    biz = _sanitize(business_id)
    return KeyPair(idem=f"seed:{biz}", ref=f"treasury-seed:{biz}")
