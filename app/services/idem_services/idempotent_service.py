from flask import jsonify
from bson import ObjectId
from app import db
from ...utils.logger import Log # import logging
from ..pos_ledger_service import (
    place_stock_hold,
    capture_stock_hold,
    release_stock_hold,
    release_expired_stock_holds
)
from ...utils.pos_idempotent_keys import (
    keys_for_stock_hold,
    keys_for_stock_release_expired,
    keys_for_stock_release,
    keys_for_stock_capture
)


def place_hold_service(cart, business_id, outlet_id, cashier_id, checksum_private):
    # Build minimal items list (SKU + integer qty)
    try:
        lines = cart["lines"]
        items = [{"product_id": str(l["product_id"]), "qty": int(l["quantity"])} for l in lines]
        
    except Exception as e:
        # fall back to fail-closed if payload is malformed
        return {
            "success": False,
            "status_code": 400,
            "message": f"Invalid cart lines for stock hold: {e}"
        }
    
    # ---- 2) Build idempotency key & human ref ----
    cart_id = checksum_private
    k = keys_for_stock_hold(
        business_id=business_id,
        outlet_id=outlet_id,
        cart_id=cart_id,
        items=items,
        cashier_id=cashier_id,
    )
    
    # ---- 3) Try to place the stock hold (reserve) ----
    try:
        hold_res = place_stock_hold(
            business_id=business_id,
            outlet_id=outlet_id,
            cashier_id=cashier_id,
            cart_id=cart_id,
            items=items,
            idempotency_key=k.idem,
            purpose="Reserve stock for POS checkout",
            ref=k.ref,
        )
        hold_id = hold_res["hold_id"]
        
        return hold_id
    

    except RuntimeError as e:
        # The same request (same cart+items) was already processed → return existing ACTIVE hold.
        if str(e) == "IDEMPOTENT_REPLAY":
            doc = db.get_collection("stock_holds").find_one({
                "business_id": ObjectId(business_id),
                "cart_id": cart_id,
                "status": "ACTIVE"
            })
            if not doc:
                # Could be CAPTURED/RELEASED; decide your policy.
                Log.info("[idempotent_service.py] Could be CAPTURED/RELEASED; decide your policy.")
                return {
                    "success": False,
                    "status_code": 409,
                    "message": "This cart has already been finalized or released."
                }
            hold_id = doc["hold_id"]
        else:
            # Unknown runtime error → bubble up as 500
            return {
                "success": False,
                "status_code": 500,
                "message": f"Stock hold failed: {e}"
            }

    except ValueError as ve:
        # Inventory helpers raise ValueError("INSUFFICIENT_STOCK") when reservation would oversell
        Log.info("[idempotent_service.py] Inventory helpers raise ValueError('INSUFFICIENT_STOCK') when reservation would oversell.")
        msg = str(ve)
        return {
            "success": False,
            "status_code": 422 if "INSUFFICIENT_STOCK" in msg else 400,
            "message": msg
        }
    
    except Exception as e:
        Log.info(f"[idempotent_service.py] Error occurred: {str(e)}")
        msg = str(e)
        return {
            "success": False,
            "status_code": 422 if "INSUFFICIENT_STOCK" in msg else 400,
            "message": msg
        }
