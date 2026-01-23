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

def keys_for_cash_collection(business_id: str, agent_id: str, barlcode: str, amount: float | str) -> KeyPair:
    biz = _sanitize(business_id); ag = _sanitize(agent_id); barc = _sanitize(barlcode)
    h = _short_hash({"op":"collection","biz":biz,"ag":ag,"ref":barc,"amt":_money(amount)})
    return KeyPair(idem=f"collection:{biz}:{ag}:{barc}:{h}", ref=f"collection:{biz}:{ag}:{barc}")
