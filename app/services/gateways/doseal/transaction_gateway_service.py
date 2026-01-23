import json
from flask import jsonify, request
from typing import Dict, Any
from ....utils.logger import Log # import logging
from ....utils.essentials import Essensial
from ....models.people_model import Agent
from ....models.admin.setup_model import Tax
from ....models.subscriber_model import Subscriber
from ....models.beneficiary_model import Beneficiary
from ....models.sender_model import Sender
from ....services.shop_api_service import ShopApiService
from ....models.settings_model import Limit
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
from ....constants.service_code import (
    HTTP_STATUS_CODES, TRANSACTION_GENERAL_REQUIRED_FIELDS
)
from ....factories.pos_request_factory import RequestFactory
from ....utils.calculate_composite_fee import calculate_composite_fee
from ....utils.transaction_utils import Transaction_amount_wizard
from ....utils.pos_request import RequestMaker
from ....services.gateways.doseal.gateway_service import GatewayService
from ....utils.generators import generate_internal_reference
from ....services.pos.inventory_service import InventoryService
from ....models.product_model import Product, Discount
from ....services.idem_services.idempotent_service import place_hold_service
from ....utils.redis import (
    set_redis_with_expiry, get_redis, remove_redis
)
from ....utils.helpers import sanitize_device_id

class TransactionGatewayService:
        
    @classmethod   
    def initiate_input(self, body: Dict[str, Any]) -> Dict:
        client_ip = request.remote_addr
        log_tag = f'[transaction_gateway_service.py][initiate_input][{client_ip}]'
        
        transaction_data = body
        
        try:
            # ============================================
            # EXTRACT REQUEST DATA
            # ============================================
            
            tenant_id = transaction_data.get("tenant_id")
            business_id = transaction_data.get("business_id")
            outlet_id = transaction_data.get("outlet_id")
            customer_id = transaction_data.get("customer_id")
            payment_method = transaction_data.get("payment_method")
            amount_paid = transaction_data.get("amount_paid")
            device_id = transaction_data.get("device_id")
            notes = transaction_data.get("notes")
            items = transaction_data.get("items", [])
            coupon_code = transaction_data.get("coupon_code")
            cash_session_id = transaction_data.get("cash_session_id")

            # ============================================
            # VALIDATION
            # ============================================
            
            if not outlet_id:
                Log.error(f"{log_tag} OUTLET_ID_REQUIRED")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Outlet ID is required.",
                    errors=["outlet_id is required"],
                )

            if not items:
                Log.error(f"{log_tag} ITEMS_REQUIRED")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="At least one item is required to build a cart.",
                    errors=["items list cannot be empty"],
                )
                
            # ============================================
            # FETCH ACTIVE DISCOUNTS FOR ALL PRODUCTS
            # ============================================
            
            # Extract all unique product IDs from items
            product_ids_in_cart = list(set([item.get("product_id") for item in items if item.get("product_id")]))
            
            # Fetch discounts for all products at once
            all_product_discounts = {}
            for pid in product_ids_in_cart:
                try:
                    discount_data = Discount.get_discount_by_product_id(business_id, pid, outlet_id)
                    
                    # ✅ Convert to list format for consistent handling
                    if not discount_data:
                        continue
                    
                    # Ensure it's always a list
                    if isinstance(discount_data, dict):
                        # Check if it's a wrapped response with 'discounts' key
                        if "discounts" in discount_data:
                            discounts_list = discount_data.get("discounts", [])
                        # Single discount object
                        elif "_id" in discount_data:
                            discounts_list = [discount_data]
                        else:
                            Log.warning(f"{log_tag} UNEXPECTED_DISCOUNT_DICT product={pid}")
                            continue
                    elif isinstance(discount_data, list):
                        # Already a list
                        discounts_list = discount_data
                    else:
                        Log.warning(f"{log_tag} UNEXPECTED_DISCOUNT_FORMAT product={pid} type={type(discount_data)}")
                        continue
                    
                    if discounts_list:
                        all_product_discounts[pid] = discounts_list
                        Log.info(f"{log_tag} DISCOUNTS_FOUND product={pid} count={len(discounts_list)}")
                    
                except Exception as e:
                    Log.error(f"{log_tag} DISCOUNT_FETCH_ERROR product={pid} error={e}", exc_info=True)
                    continue
            
            total_discounts_loaded = sum(len(d) for d in all_product_discounts.values())
            Log.info(f"{log_tag} PRODUCT_DISCOUNTS_LOADED products={len(all_product_discounts)} total_discounts={total_discounts_loaded}")

            # ============================================
            # HANDLE COUPON CODE DISCOUNT
            # ============================================
            
            coupon_discount = None
            if coupon_code:
                coupon_discount = Discount.get_by_code(business_id, coupon_code, outlet_id)
                
                if not coupon_discount:
                    Log.warning(f"{log_tag} INVALID_COUPON_CODE code={coupon_code}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=f"Invalid or expired coupon code: {coupon_code}",
                        errors=[f"Coupon code '{coupon_code}' is not valid"],
                    )
                
                # ✅ Coupon data is already decrypted by get_by_code
                Log.info(f"{log_tag} COUPON_APPLIED code={coupon_code} discount={coupon_discount.get('discount_amount')}")

            # ============================================
            # BUILD CART LINES
            # ============================================
            
            lines = []
            subtotal = 0.0
            total_discount = 0.0
            total_tax = 0.0
            total_cost = 0.0

            for idx, item in enumerate(items):
                product_id = item.get("product_id")
                quantity = item.get("quantity", 1)
                
                # ============================================
                # VALIDATE ITEM
                # ============================================
                
                try:
                    quantity = float(quantity)
                except (ValueError, TypeError):
                    Log.error(f"{log_tag} INVALID_QUANTITY_TYPE item_index={idx} quantity={quantity}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Quantity must be a valid number.",
                        errors=[f"Invalid quantity for item at index {idx}"],
                    )

                if not product_id:
                    Log.error(f"{log_tag} ITEM_MISSING_PRODUCT_ID item_index={idx}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Each item must have a product_id.",
                        errors=[f"Missing product_id for item at index {idx}"],
                    )

                if quantity <= 0:
                    Log.error(f"{log_tag} INVALID_QUANTITY item_index={idx} quantity={quantity}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Quantity must be greater than zero.",
                        errors=[f"Invalid quantity {quantity} for item at index {idx}"],
                    )

                # ============================================
                # FETCH PRODUCT
                # ============================================
                
                product = Product.get_by_id(product_id, business_id)
                if not product:
                    Log.error(f"{log_tag} PRODUCT_NOT_FOUND product_id={product_id}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=f"Product not found: {product_id}",
                        errors=[f"Product {product_id} does not exist"],
                    )

                # Core product fields
                product_name = product.get("name", "Unknown Product")
                sku = product.get("sku")
                category = product.get("category", "Uncategorized")
                images = product.get("images") or []
                

                # ============================================
                # PRICING
                # ============================================
                
                unit_cost = 0.0
                unit_price = 0.0
                raw_prices = product.get("prices")

                if raw_prices:
                    try:
                        parsed_prices = (
                            json.loads(raw_prices)
                            if isinstance(raw_prices, str)
                            else raw_prices or {}
                        )
                        
                        supply_price = parsed_prices.get("supply_price")
                        retail_price = parsed_prices.get("retail_price")

                        if supply_price is not None:
                            unit_cost = float(supply_price)

                        if retail_price is not None:
                            unit_price = float(retail_price)
                        else:
                            unit_price = unit_cost if unit_cost > 0 else 0.0

                        Log.info(f"{log_tag} PRICES product={product_id} cost={unit_cost} price={unit_price}")
                        
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        Log.error(f"{log_tag} INVALID_PRICES product_id={product_id} error={e}")
                        unit_cost = 0.0
                        unit_price = 0.0

                if unit_price <= 0:
                    Log.warning(f"{log_tag} ZERO_PRICE product_id={product_id}")

                # ============================================
                # TAX CALCULATION
                # ============================================
                
                combined_tax_rate = 0.0
                tax_ids = product.get("tax") or []

                for tax_id in tax_ids:
                    try:
                        tax_doc = Tax.get_by_id(tax_id, business_id)
                        
                        if not tax_doc:
                            Log.warning(f"{log_tag} TAX_NOT_FOUND product_id={product_id} tax_id={tax_id}")
                            continue

                        rate_val = tax_doc.get("rate")
                        if rate_val is not None:
                            try:
                                tax_rate = float(rate_val) / 100.0
                                combined_tax_rate += tax_rate
                                Log.info(f"{log_tag} TAX_ADDED tax_id={tax_id} rate={tax_rate}")
                            except (ValueError, TypeError) as e:
                                Log.error(f"{log_tag} INVALID_TAX_RATE tax_id={tax_id} rate={rate_val} error={e}")
                                
                    except Exception as e:
                        Log.error(f"{log_tag} TAX_FETCH_ERROR tax_id={tax_id} error={e}")
                        continue

                # ============================================
                # BASE AMOUNTS
                # ============================================
                
                line_subtotal = unit_price * quantity
                line_discount = 0.0
                applied_discount_meta = None

                # ============================================
                # DISCOUNT APPLICATION
                # ============================================
                
                # Get discounts for this product
                product_discounts = all_product_discounts.get(product_id, [])
                
                # ✅ Ensure it's a list
                if not isinstance(product_discounts, list):
                    if isinstance(product_discounts, dict):
                        product_discounts = [product_discounts]
                    else:
                        product_discounts = []
                
                applicable_discounts = []
                
                # ✅ Filter discounts - data is already decrypted
                for disc in product_discounts:
                    try:
                        # ✅ Validate disc is a dict
                        if not isinstance(disc, dict):
                            Log.warning(f"{log_tag} INVALID_DISCOUNT_TYPE product={product_id} type={type(disc)}")
                            continue
                        
                        # ✅ No need to decrypt - already done by get_discount_by_product_id
                        scope = disc.get("scope", "product")
                        
                        # Product-level discount
                        if scope == "product":
                            product_ids = disc.get("product_ids") or []
                            product_ids_str = {str(pid) for pid in product_ids}
                            
                            if str(product_id) not in product_ids_str:
                                continue
                        
                        # Category-level discount
                        elif scope == "category":
                            category_names = disc.get("category_names") or []
                            
                            if category not in category_names:
                                continue
                        
                        # Cart-level discount - applies to all
                        elif scope == "cart":
                            pass
                        
                        applicable_discounts.append(disc)
                        
                    except Exception as e:
                        disc_id = disc.get("_id") if isinstance(disc, dict) else "unknown"
                        Log.error(f"{log_tag} DISCOUNT_FILTER_ERROR discount_id={disc_id} error={e}", exc_info=True)
                        continue

                # ✅ Add coupon discount if applicable (already decrypted)
                if coupon_discount:
                    # Check if coupon applies to this product/category
                    coupon_scope = coupon_discount.get("scope", "cart")
                    coupon_applies = False
                    
                    if coupon_scope == "cart":
                        coupon_applies = True
                    elif coupon_scope == "product":
                        coupon_product_ids = coupon_discount.get("product_ids", [])
                        coupon_product_ids_str = {str(pid) for pid in coupon_product_ids}
                        if str(product_id) in coupon_product_ids_str:
                            coupon_applies = True
                    elif coupon_scope == "category":
                        coupon_categories = coupon_discount.get("category_names", [])
                        if category in coupon_categories:
                            coupon_applies = True
                    
                    if coupon_applies:
                        applicable_discounts.append(coupon_discount)
                        Log.info(f"{log_tag} COUPON_APPLICABLE product={product_id}")

                Log.info(f"{log_tag} APPLICABLE_DISCOUNTS product={product_id} count={len(applicable_discounts)}")

                # ✅ Select best discount (highest value, then lowest priority)
                if applicable_discounts:
                    best_discount = None
                    best_value = 0.0
                    best_priority = float('inf')

                    for disc in applicable_discounts:
                        try:
                            # ✅ Data already decrypted - use directly
                            disc_type = disc.get("discount_type", "percentage")
                            disc_amount = float(disc.get("discount_amount", 0))
                            priority = int(disc.get("priority", 0))

                            # Calculate discount value
                            discount_value = 0.0
                            
                            if disc_type == "percentage":
                                discount_value = line_subtotal * (disc_amount / 100.0)
                                
                            elif disc_type == "fixed_amount":
                                discount_value = disc_amount * quantity
                                
                            elif disc_type == "buy_x_get_y":
                                buy_qty = int(disc.get("buy_quantity", 0))
                                free_qty = int(disc.get("get_quantity", 0))
                                
                                if buy_qty > 0 and free_qty > 0:
                                    group_size = buy_qty + free_qty
                                    if quantity >= group_size:
                                        full_groups = int(quantity // group_size)
                                        free_units = full_groups * free_qty
                                        discount_value = free_units * unit_price

                            # Cap discount at line subtotal
                            discount_value = min(discount_value, line_subtotal)

                            # Select best discount
                            if discount_value > best_value or (
                                discount_value == best_value and priority < best_priority
                            ):
                                best_discount = disc
                                best_value = discount_value
                                best_priority = priority
                                
                        except Exception as e:
                            disc_id = disc.get("_id") if isinstance(disc, dict) else "unknown"
                            Log.error(f"{log_tag} DISCOUNT_CALC_ERROR discount_id={disc_id} error={e}", exc_info=True)
                            continue

                    # Apply best discount
                    if best_discount and best_value > 0:
                        line_discount = best_value
                        
                        # ✅ Data already decrypted
                        disc_type = best_discount.get("discount_type", "percentage")
                        disc_amount = float(best_discount.get("discount_amount", 0))
                        disc_name = best_discount.get("name", "Discount")
                        
                        applied_discount_meta = {
                            "discount_id": str(best_discount.get("_id")),
                            "discount_name": disc_name,
                            "discount_type": disc_type,
                            "discount_value": disc_amount,
                            "discount_amount": round(line_discount, 2),
                        }
                        
                        Log.info(f"{log_tag} DISCOUNT_APPLIED product={product_id} type={disc_type} amount={line_discount}")

                # ============================================
                # FINAL LINE CALCULATIONS
                # ============================================
                
                taxable_base = max(0, line_subtotal - line_discount)
                line_tax = taxable_base * combined_tax_rate
                line_total = taxable_base + line_tax

                # Update totals
                subtotal += line_subtotal
                total_discount += line_discount
                total_tax += line_tax
                total_cost += unit_cost * quantity

                # Build line object
                line_obj = {
                    "product_id": product_id,
                    "product_name": product_name,
                    "category": category,
                    "quantity": quantity,
                    "unit_price": round(unit_price, 2),
                    "unit_cost": round(unit_cost, 2),
                    "tax_rate": round(combined_tax_rate, 4),
                    "tax_amount": round(line_tax, 2),
                    "discount_amount": round(line_discount, 2),
                    "subtotal": round(line_subtotal, 2),
                    "line_total": round(line_total, 2),
                }
                
                
                transaction_data["subtotal"] = round(line_subtotal, 2)
                transaction_data["total_discount"] = round(total_discount, 2)
                transaction_data["total_tax"] = round(total_tax, 2)
                transaction_data["total_cost"] = round(total_cost, 2)

                
                # Add optional fields
                if sku:
                    line_obj["sku"] = sku
                
                if applied_discount_meta:
                    line_obj["applied_discount"] = applied_discount_meta

                if images:
                    line_obj["image"] = images[0]

                lines.append(line_obj)

            # ============================================
            # BUILD CART TOTALS
            # ============================================
            
            grand_total = subtotal - total_discount + total_tax
            transaction_data["grand_total"] = grand_total
            transaction_data["lines"] = lines

            cart = {
                "lines": lines,
                "totals": {
                    "subtotal": round(subtotal, 2),
                    "total_discount": round(total_discount, 2),
                    "total_tax": round(total_tax, 2),
                    "total_cost": round(total_cost, 2),
                    "grand_total": round(grand_total, 2),
                },
            }
            
            transaction_data["cart"] = cart

            # ============================================
            # STOCK VALIDATION
            # ============================================
            
            try:
                stock_items = [
                    {
                        "product_id": line["product_id"],
                        "composite_variant_id": line.get("composite_variant_id"),
                        "quantity": line["quantity"],
                    }
                    for line in lines
                ]
                
                

                has_stock, insufficient_items = InventoryService.validate_stock_availability(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    items=stock_items,
                )

                if not has_stock:
                    Log.error(f"{log_tag} INSUFFICIENT_STOCK items={len(insufficient_items)}")
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Insufficient stock for one or more items.",
                        data={"insufficient_items": insufficient_items},
                    )

            except Exception as e:
                Log.error(f"{log_tag} STOCK_VALIDATION_ERROR error={str(e)}")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Error validating stock availability.",
                    errors=[str(e)],
                )

            

            Log.info(f"{log_tag} CART_PREVIEW_SUCCESS items={len(lines)} grand_total={grand_total} total_discount={total_discount}")
            
            # ============================================
            # BUILD PAYLOAD IN FACTORY
            # ============================================
            
            order_request = RequestFactory.make_transaction(transaction_data)

            # prepare transaction failed
            if order_request is None:
                Log.info(f"{log_tag} preparing order request failed") 
                return prepared_response(False, "BAD_REQUEST", f"preparing transaction request failed")

            # retrieve prepared data wih getters
            user__id = RequestMaker.get_user__id(order_request)
            user_id = RequestMaker.get_user_id(order_request)
            cashier_id = RequestMaker.get_cashier_id(order_request)
            cash_session_id = RequestMaker.get_cash_session_id(order_request)
            tenant_id = RequestMaker.get_tenant_id(order_request)
            business_id = RequestMaker.get_business_id(order_request)
            outlet_id = RequestMaker.get_outlet_id(order_request)
            customer_id = RequestMaker.get_customer_id(order_request)
            lines = RequestMaker.get_lines(order_request)
            sku = RequestMaker.get_sku(order_request)
            cart = RequestMaker.get_cart(order_request)
            payment_method = RequestMaker.get_payment_method(order_request)
            amount_paid = RequestMaker.get_amount_paid(order_request)
            device_id = RequestMaker.get_device_id(order_request)
            notes = RequestMaker.get_notes(order_request)
            coupon_code = RequestMaker.get_coupon_code(order_request)
            transaction_number = RequestMaker.get_transaction_number(order_request)
            receipt_number = RequestMaker.get_receipt_number(order_request)
            
                        
            
            request_payload = {
                "device_id": device_id,
                "business_id": business_id,
                "outlet_id": outlet_id,
                "cart": cart,
                "customer_id": customer_id,
                "payment_method": payment_method,
                "amount_paid": amount_paid
            }
            
            #attach optional keys
            if coupon_code:
                request_payload["coupon_code"] = coupon_code
            if notes:
                request_payload["notes"] = notes
                
            
            # =====================================================
            # PUSH PAYLOAD TO GATEWAY SERVICE FOR FINAL PREPARATION
            # =====================================================
            
            # initialize gateway service with tenant ID
            gateway_service = GatewayService(tenant_id)
            
            payload = {
                "user__id": user__id,
                "user_id": user_id,
                "cash_session_id": cash_session_id,
                "cashier_id": cashier_id,
                "device_id": device_id,
                "tenant_id": tenant_id,
                "business_id": business_id,
                "outlet_id": outlet_id,
                "customer_id": customer_id,
                "cart": cart,
                "payment_method": payment_method,
                "amount_paid": amount_paid,
            }

            # Only include optional fields if they contain a value
            if sku is not None:
                payload["sku"] = sku

            if notes is not None:
                payload["notes"] = notes

            if coupon_code is not None:
                payload["coupon_code"] = coupon_code
                
            if transaction_number is not None:
                payload["transaction_number"] = transaction_number
            
            if receipt_number is not None:
                payload["receipt_number"] = receipt_number
            

            json_response = gateway_service.process_request_initiate(**payload)
            
            if json_response:
                checksum_private = json_response.get("checksum_private")
            
            #======================
            # PLACING STOCK ON HOLD
            #======================
            hold_id = place_hold_service(
                cart=cart, 
                business_id=business_id,
                outlet_id=outlet_id,
                cashier_id=cashier_id,
                checksum_private=checksum_private,
            )
            
            device_id_str = sanitize_device_id(device_id)
            cashier_id_str = sanitize_device_id(cashier_id)
            customer_id_str = sanitize_device_id(customer_id)
            
            if hold_id:
                # store the hold_id in redis
                redis_key_string = f"{device_id_str}_{cashier_id_str}_{customer_id_str}"
                set_redis_with_expiry(redis_key_string, 600, hold_id)
                
            # remove checksum_private
            json_response.pop("checksum_private", None)
            
            # return the payload
            return jsonify(json_response)
            

        except Exception as e:
            Log.error(f"{log_tag} INTERNAL_ERROR error={str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An error occurred while building cart preview.",
                errors=[str(e)],
            )
        
        
