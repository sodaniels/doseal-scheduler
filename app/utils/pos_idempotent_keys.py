# services/pos_idempotent_keys.py
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, re
from typing import Optional, Iterable, Dict, Any

@dataclass(frozen=True)
class KeyPair:
    """Pair of values you pass to stock ops."""
    idem: str  # idempotency_key
    ref: str   # human-readable reference (e.g., meta)

SAFE_CHARS = re.compile(r"[^a-zA-Z0-9:_\-\.]")

def _sanitize(part: str) -> str:
    s = str(part).strip().replace(" ", "-").lower()
    return SAFE_CHARS.sub("", s)

def _short_hash(payload: dict, length: int = 24) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    import hashlib as _h
    return _h.sha256(raw).hexdigest()[:length]

def _normalize_items(items: Iterable[Dict[str, Any]]) -> list[dict]:
    """
    Keep only keys that define stock identity/amount.
    Accept both sku OR product_id (+ optional variant).
    """
    cleaned = []
    for i in items:
        rec = {
            "qty": int(i["qty"]),
        }
        # prefer product_id if present; else sku
        if "product_id" in i and i["product_id"]:
            rec["product_id"] = str(i["product_id"])
            if "composite_variant_id" in i and i["composite_variant_id"]:
                rec["composite_variant_id"] = str(i["composite_variant_id"])
        else:
            rec["sku"] = str(i["sku"])
        cleaned.append(rec)
    # sort stably (by product_id/variant/sku) so order doesn't affect the hash
    def kf(x):
        if "product_id" in x:
            return (x["product_id"], x.get("composite_variant_id", ""), "")
        return ("", "", x["sku"])
    cleaned.sort(key=kf)
    return cleaned

def keys_for_stock_hold(
    *,
    business_id: str,
    outlet_id: str,
    cart_id: str,
    items: Iterable[Dict[str, Any]],
    cashier_id: Optional[str] = None
) -> KeyPair:
    biz = _sanitize(business_id)
    out = _sanitize(outlet_id)
    cart = _sanitize(cart_id)
    norm_items = _normalize_items(items)
    payload = {"op": "stock_hold", "biz": biz, "out": out, "cart": cart, "items": norm_items}
    if cashier_id:
        payload["cashier"] = _sanitize(cashier_id)
    h = _short_hash(payload)
    return KeyPair(
        idem=f"stock-hold:{biz}:{out}:{cart}:{h}",
        ref =f"stock-hold:{biz}:{out}:{cart}"
    )

def keys_for_stock_capture(business_id: str, hold_id: str, sale_id: Optional[str] = None) -> KeyPair:
    biz = _sanitize(business_id); hid = _sanitize(hold_id)
    if sale_id:
        sid = _sanitize(sale_id)
        return KeyPair(idem=f"stock-cap:{biz}:{hid}:{sid}", ref=f"stock-cap:{biz}:{hid}:{sid}")
    return KeyPair(idem=f"stock-cap:{biz}:{hid}", ref=f"stock-cap:{biz}:{hid}")

def keys_for_stock_release(business_id: str, hold_id: str, reason: Optional[str] = None) -> KeyPair:
    biz = _sanitize(business_id); hid = _sanitize(hold_id)
    if reason:
        r = _sanitize(reason)
        return KeyPair(idem=f"stock-rel:{biz}:{hid}:{r}", ref=f"stock-rel:{biz}:{hid}:{r}")
    return KeyPair(idem=f"stock-rel:{biz}:{hid}", ref=f"stock-rel:{biz}:{hid}")

def keys_for_stock_release_expired(business_id: str, hold_id: str) -> KeyPair:
    biz = _sanitize(business_id); hid = _sanitize(hold_id)
    return KeyPair(idem=f"stock-rel-exp:{biz}:{hid}", ref=f"stock-rel-exp:{biz}:{hid}")
