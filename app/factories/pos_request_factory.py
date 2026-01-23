from typing import Any, Dict, Optional
from pydantic import ValidationError
from ..utils.pos_request import RequestMaker
from ..utils.logger import Log

class RequestFactory:
    def make_transaction(body: Dict[str, Any]) -> Optional[RequestMaker]:
        try:
            # Basic setup
            
            # Build line object
            user__id = body.get("user__id")
            user_id = body.get("user_id")
            device_id = body.get("device_id")
            tenant_id = body.get("tenant_id")
            cash_session_id = body.get("cash_session_id")
            cashier_id = body.get("cashier_id")
            customer_id = body.get("customer_id")
            sku = body.get("sku")
            cart = body.get("cart")
            business_id = body.get("business_id")
            outlet_id = body.get("outlet_id")
            coupon_code = body.get("coupon_code")
            payment_method = body.get("payment_method")
            amount_paid = body.get("amount_paid")
            notes = body.get("notes")
            transaction_number = body.get("transaction_number")
            receipt_number = body.get("receipt_number")
            
    
            # preparing request      
            return RequestMaker(
                user__id=user__id,
                user_id=user_id,
                cashier_id=cashier_id,
                tenant_id=tenant_id,
                business_id=business_id,
                cash_session_id=cash_session_id,
                outlet_id=outlet_id,
                customer_id=customer_id,
                sku=sku,
                cart=cart,
                payment_method=payment_method,
                amount_paid=amount_paid,
                device_id=device_id,
                notes=notes,
                coupon_code=coupon_code,
                transaction_number=transaction_number,
                receipt_number=receipt_number,
            )

        except ValidationError as ve:
            Log.error(f"[RequestFactory] Validation error: {ve}")
        except Exception as e:
            Log.error(f"[RequestFactory] Unexpected error: {e}")
            return None