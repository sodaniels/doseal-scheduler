# services/sale_service.py
from bson import ObjectId
from datetime import datetime
from ....models.admin.sale import Sale
from app import db
from ....models.admin.stock_ledger import StockLedger
from ..inventory_service import InventoryService
from ..cart_service import CartService
from ....utils.logger import Log


class SaleService:
    """
    Enhanced service layer for sale operations.
    Handles sale creation, stock adjustments, and sale modifications.
    Supports comprehensive reporting schema.
    """
    
    @staticmethod
    def create_sale_from_cart(
        business_id,
        outlet_id,
        user_id,
        user__id,
        cart,
        payment_method,
        # Core fields
        cashier_id=None,
        customer_id=None,
        status=None,
        amount_paid=None,
        # Transaction identifiers
        transaction_number=None,
        receipt_number=None,
        # Discount & promotion
        discount_type=None,
        coupon_code=None,
        promotion_id=None,
        # Refund/void tracking
        refund_reason=None,
        void_reason=None,
        authorized_by=None,
        # Operational tracking
        cash_session_id=None,
        device_id=None,
        # Metadata
        notes=None,
        reference_note=None,
        # Legacy fields
        agent_id=None,
        checksum=None,
        admin_id=None,
        hold_id=None,
    ):
        """
        Create a sale from a cart and adjust inventory.
        Enhanced to support comprehensive reporting schema.
        
        Args:
            business_id: Business ObjectId or string (required)
            outlet_id: Outlet ObjectId or string (required)
            user_id: User string ID (required)
            user__id: User ObjectId (required)
            cart: Dict - complete cart with lines and totals (required)
            payment_method: String - payment type (required)
            cashier_id: Cashier ObjectId or string (defaults to user__id)
            customer_id: Optional customer ObjectId or string
            status: String - sale status (defaults to Completed)
            amount_paid: Optional float - amount paid
            transaction_number: Unique transaction identifier
            receipt_number: Receipt/invoice number
            discount_type: Type of discount applied
            coupon_code: Coupon code used
            promotion_id: Promotion ObjectId or string
            refund_reason: Reason for refund (if applicable)
            void_reason: Reason for void (if applicable)
            authorized_by: Manager who authorized void/refund
            cash_session_id: Shift/session ObjectId or string
            device_id: POS device identifier
            notes: General notes
            reference_note: Additional notes (legacy)
            agent_id: Optional agent ObjectId (legacy)
            admin_id: Optional admin ObjectId (legacy)
            
        Returns:
            Tuple (success: bool, sale_id: str or None, error: str or None)
        """
        log_tag = f"[sale_service.py][SaleService][create_sale_from_cart][{business_id}][{outlet_id}]"
        
        try:
            # Step 1: Validate cart structure
            is_valid, validation_errors = CartService.validate_cart(cart)
            if not is_valid:
                Log.error(f"{log_tag} Cart validation failed: {validation_errors}")
                return False, None, f"Cart validation failed: {', '.join(validation_errors)}"
            
            # Step 2: Validate required cart fields for reporting
            required_totals = ["subtotal", "total_discount", "total_tax", "total_cost", "grand_total"]
            missing_totals = [field for field in required_totals if field not in cart.get("totals", {})]
            if missing_totals:
                Log.error(f"{log_tag} Missing cart totals: {missing_totals}")
                return False, None, f"Missing cart totals: {', '.join(missing_totals)}"
            
            # Validate line items have required fields
            required_line_fields = ["product_id", "product_name", "category", "quantity", 
                                   "unit_price", "unit_cost", "tax_rate", "tax_amount"]
            for idx, line in enumerate(cart.get("lines", [])):
                missing_fields = [field for field in required_line_fields if field not in line]
                if missing_fields:
                    Log.error(f"{log_tag} Line {idx} missing fields: {missing_fields}")
                    return False, None, f"Line {idx} missing: {', '.join(missing_fields)}"
            
            # Step 3: Build stock validation items
            stock_items = []
            for line in cart.get("lines", []):
                stock_items.append({
                    "product_id": line["product_id"],
                    "composite_variant_id": line.get("composite_variant_id"),
                    "quantity": line["quantity"]
                })
            
            # Step 4: Validate stock availability
            has_stock, insufficient_items = InventoryService.validate_stock_availability(
                business_id=business_id,
                outlet_id=outlet_id,
                items=stock_items
            )
            
            if not has_stock:
                Log.error(f"{log_tag} Insufficient stock for sale")
                return False, None, f"Insufficient stock: {insufficient_items}"
            
            # Step 5: Generate transaction number if not provided
            if not transaction_number:
                transaction_number = SaleService._generate_transaction_number(business_id, outlet_id)
                
            if not receipt_number:
                receipt_number = SaleService._generate_receipt_number(business_id, outlet_id)
            
            # Step 6: Create enhanced sale record
            sale = Sale(
                # Core - required
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                cart=cart,
                payment_method=payment_method,
                # Core - optional
                cashier_id=cashier_id,
                customer_id=customer_id,
                status=status or Sale.STATUS_COMPLETED,
                amount_paid=amount_paid,
                # Transaction identifiers
                transaction_number=transaction_number,
                receipt_number=receipt_number,
                # Discount & promotion
                discount_type=discount_type,
                coupon_code=coupon_code,
                promotion_id=promotion_id,
                # Refund/void tracking
                refund_reason=refund_reason,
                void_reason=void_reason,
                authorized_by=authorized_by,
                # Operational tracking
                cash_session_id=cash_session_id,
                device_id=device_id,
                # Metadata
                notes=notes,
                checksum=checksum,
                reference_note=reference_note,
                # Legacy
                agent_id=agent_id,
                admin_id=admin_id,
                hold_id=hold_id,
            )
            
            sale_id = sale.save()
            
            if not sale_id:
                Log.error(f"{log_tag} Failed to create sale record")
                return False, None, "Failed to create sale record"
            
            Log.info(f"{log_tag} Sale created: {sale_id} (txn: {transaction_number})")
            
            # Step 7: Create stock ledger entries (decrease stock for each line)
            ledger_ids = []
            for line in cart.get("lines", []):
                ledger_id = InventoryService.decrease_stock(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    reference_type=StockLedger.REF_TYPE_SALE,
                    user_id=user_id,
                    user__id=user__id,
                    composite_variant_id=line.get("composite_variant_id"),
                    reference_id=sale_id,
                    note=f"Sale {transaction_number} - {line.get('product_name', 'Product')}",
                    unit_cost=line.get("unit_cost"),  # Use cost from cart line
                    agent_id=agent_id,
                    admin_id=admin_id
                )
                
                if ledger_id:
                    ledger_ids.append(ledger_id)
                else:
                    Log.error(f"{log_tag} Failed to create ledger entry for product {line['product_id']}")
            
            Log.info(f"{log_tag} Created {len(ledger_ids)} stock ledger entries for sale {sale_id}")
            
            return True, str(sale_id), None, transaction_number, receipt_number
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def void_sale(sale_id, business_id, outlet_id, user_id, user__id, reason=None, authorized_by=None, agent_id=None, admin_id=None):
        """
        Void a sale and reverse stock movements.
        Enhanced to track authorization and reason.
        
        Args:
            sale_id: Sale ObjectId or string
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            reason: Reason for voiding (required for reporting)
            authorized_by: Manager who authorized the void
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, error: str or None)
        """
        log_tag = f"[sale_service.py][SaleService][void_sale][{sale_id}][{business_id}]"
        
        try:
            # Step 1: Fetch sale
            sale = Sale.get_by_id(sale_id=sale_id, business_id=business_id)
            
            if not sale:
                Log.error(f"{log_tag} Sale not found")
                return False, "Sale not found"
            
            # Step 2: Verify sale can be voided
            if sale.get("status") == Sale.STATUS_VOIDED:
                Log.error(f"{log_tag} Sale already voided")
                return False, "Sale is already voided"
            
            if sale.get("status") == Sale.STATUS_REFUNDED:
                Log.error(f"{log_tag} Sale already refunded")
                return False, "Sale is already refunded"
            
            # Step 3: Verify outlet matches (security check)
            if str(sale.get("outlet_id")) != str(outlet_id):
                Log.error(f"{log_tag} Outlet mismatch")
                return False, "Sale outlet does not match"
            
            # Step 4: Reverse stock for each line (increase stock)
            cart = sale.get("cart", {})
            ledger_ids = []
            
            for line in cart.get("lines", []):
                ledger_id = InventoryService.increase_stock(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    reference_type=StockLedger.REF_TYPE_SALE_VOID,
                    user_id=user_id,
                    user__id=user__id,
                    composite_variant_id=line.get("composite_variant_id"),
                    reference_id=sale_id,
                    note=f"Void of sale {sale.get('transaction_number', sale_id)} - {line.get('product_name', 'Product')}. Reason: {reason or 'Not specified'}",
                    agent_id=agent_id,
                    admin_id=admin_id
                )
                
                if ledger_id:
                    ledger_ids.append(ledger_id)
                else:
                    Log.error(f"{log_tag} Failed to create void ledger entry for product {line['product_id']}")
            
            Log.info(f"{log_tag} Created {len(ledger_ids)} void ledger entries")
            
            # Step 5: Update sale status with reason and authorization
            success = Sale.update_status(
                sale_id=sale_id,
                business_id=business_id,
                new_status=Sale.STATUS_VOIDED,
                reason=reason,
                authorized_by=authorized_by
            )
            
            if success:
                Log.info(f"{log_tag} Sale voided successfully")
                return True, None
            else:
                Log.error(f"{log_tag} Failed to update sale status")
                return False, "Failed to update sale status"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def refund_sale(sale_id, business_id, outlet_id, user_id, user__id, reason=None, authorized_by=None, partial_amount=None, agent_id=None, admin_id=None):
        """
        Refund a sale (full or partial) and reverse stock movements.
        
        Args:
            sale_id: Sale ObjectId or string
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            reason: Reason for refund (required for reporting)
            authorized_by: Manager who authorized the refund
            partial_amount: Optional float for partial refund
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, error: str or None)
        """
        log_tag = f"[sale_service.py][SaleService][refund_sale][{sale_id}][{business_id}]"
        
        try:
            # Fetch sale
            sale = Sale.get_by_id(sale_id=sale_id, business_id=business_id)
            
            if not sale:
                Log.error(f"{log_tag} Sale not found")
                return False, "Sale not found"
            
            # Verify sale can be refunded
            if sale.get("status") == Sale.STATUS_VOIDED:
                Log.error(f"{log_tag} Cannot refund voided sale")
                return False, "Cannot refund a voided sale"
            
            if sale.get("status") == Sale.STATUS_REFUNDED:
                Log.error(f"{log_tag} Sale already fully refunded")
                return False, "Sale is already fully refunded"
            
            # Determine refund type
            grand_total = sale.get("cart", {}).get("totals", {}).get("grand_total", 0)
            is_partial = partial_amount is not None and partial_amount < grand_total
            new_status = Sale.STATUS_PARTIALLY_REFUNDED if is_partial else Sale.STATUS_REFUNDED
            
            # Reverse stock for full refund (for partial, you might need custom logic)
            if not is_partial:
                cart = sale.get("cart", {})
                ledger_ids = []
                
                for line in cart.get("lines", []):
                    ledger_id = InventoryService.increase_stock(
                        business_id=business_id,
                        outlet_id=outlet_id,
                        product_id=line["product_id"],
                        quantity=line["quantity"],
                        reference_type=StockLedger.REF_TYPE_SALE_REFUND,
                        user_id=user_id,
                        user__id=user__id,
                        composite_variant_id=line.get("composite_variant_id"),
                        reference_id=sale_id,
                        note=f"Refund of sale {sale.get('transaction_number', sale_id)} - {line.get('product_name', 'Product')}. Reason: {reason or 'Not specified'}",
                        agent_id=agent_id,
                        admin_id=admin_id
                    )
                    
                    if ledger_id:
                        ledger_ids.append(ledger_id)
                
                Log.info(f"{log_tag} Created {len(ledger_ids)} refund ledger entries")
            
            # Update sale status
            success = Sale.update_status(
                sale_id=sale_id,
                business_id=business_id,
                new_status=new_status,
                reason=reason,
                authorized_by=authorized_by
            )
            
            if success:
                Log.info(f"{log_tag} Sale refunded successfully (status: {new_status})")
                return True, None
            else:
                Log.error(f"{log_tag} Failed to update sale status")
                return False, "Failed to update sale status"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def get_sale_summary(business_id, outlet_id=None, start_date=None, end_date=None, status=None):
        """
        Get enhanced sales summary for reporting.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Optional outlet filter
            start_date: Optional datetime start
            end_date: Optional datetime end
            status: Optional status filter
            
        Returns:
            Dict with enhanced summary metrics
        """
        log_tag = f"[sale_service.py][SaleService][get_sale_summary][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection("sales")
            
            # Build match query
            match_query = {"business_id": business_id}
            
            if status:
                match_query["status"] = status
            else:
                match_query["status"] = {"$ne": Sale.STATUS_VOIDED}  # Exclude voided by default
            
            if outlet_id:
                outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
                match_query["outlet_id"] = outlet_id
            
            if start_date or end_date:
                match_query["created_at"] = {}
                if start_date:
                    match_query["created_at"]["$gte"] = start_date
                if end_date:
                    match_query["created_at"]["$lte"] = end_date
            
            # Enhanced aggregation pipeline
            pipeline = [
                {"$match": match_query},
                {"$group": {
                    "_id": None,
                    "total_sales": {"$sum": 1},
                    "total_revenue": {"$sum": "$cart.totals.grand_total"},
                    "total_cost": {"$sum": "$cart.totals.total_cost"},
                    "total_tax": {"$sum": "$cart.totals.total_tax"},
                    "total_discount": {"$sum": "$cart.totals.total_discount"},
                    "total_items": {"$sum": {"$size": "$cart.lines"}}
                }}
            ]
            
            result = list(collection.aggregate(pipeline))
            
            if result and len(result) > 0:
                data = result[0]
                total_revenue = float(data.get("total_revenue", 0))
                total_cost = float(data.get("total_cost", 0))
                gross_profit = total_revenue - total_cost
                profit_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
                
                summary = {
                    "total_sales": data.get("total_sales", 0),
                    "total_revenue": round(total_revenue, 2),
                    "total_cost": round(total_cost, 2),
                    "gross_profit": round(gross_profit, 2),
                    "profit_margin": round(profit_margin, 2),
                    "total_tax": round(float(data.get("total_tax", 0)), 2),
                    "total_discount": round(float(data.get("total_discount", 0)), 2),
                    "total_items": data.get("total_items", 0),
                    "average_sale": round(total_revenue / data.get("total_sales", 1), 2) if data.get("total_sales", 0) > 0 else 0
                }
            else:
                summary = {
                    "total_sales": 0,
                    "total_revenue": 0.0,
                    "total_cost": 0.0,
                    "gross_profit": 0.0,
                    "profit_margin": 0.0,
                    "total_tax": 0.0,
                    "total_discount": 0.0,
                    "total_items": 0,
                    "average_sale": 0.0
                }
            
            Log.info(f"{log_tag} Summary: {summary}")
            return summary
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "total_sales": 0,
                "total_revenue": 0.0,
                "total_cost": 0.0,
                "gross_profit": 0.0,
                "profit_margin": 0.0,
                "total_tax": 0.0,
                "total_discount": 0.0,
                "total_items": 0,
                "average_sale": 0.0
            }
    
    @staticmethod
    def _generate_transaction_number(business_id, outlet_id):
        """
        Generate unique transaction number.
        Format: TXN-YYYYMMDD-OUTLET-SEQUENCE
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            
        Returns:
            String transaction number
        """
        try:
            # Get today's date
            today = datetime.utcnow().strftime("%Y%m%d")
            
            # Get outlet short code (last 4 chars of outlet_id)
            outlet_code = str(outlet_id)[-4:].upper()
            
            # Get today's sequence number
            collection = db.get_collection(Sale.collection_name)
            count = collection.count_documents({
                "business_id": ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id,
                "created_at": {
                    "$gte": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                }
            })
            
            sequence = str(count + 1).zfill(4)
            
            return f"TXN-{today}-{outlet_code}-{sequence}"
            
        except Exception as e:
            Log.error(f"[_generate_transaction_number] Error: {str(e)}")
            # Fallback to timestamp-based
            return f"TXN-{int(datetime.utcnow().timestamp())}"

    # Add this method to SaleService class in services/sale_service.py

    @staticmethod
    def _generate_receipt_number(business_id, outlet_id):
        """
        Generate unique receipt number.
        Format: RCP-OUTLET-YYYYMMDD-SEQUENCE
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            
        Returns:
            String receipt number
        """
        try:
            from datetime import datetime
            
            # Get today's date
            today = datetime.utcnow().strftime("%Y%m%d")
            
            # Get outlet short code (last 4 chars of outlet_id)
            outlet_code = str(outlet_id)[-4:].upper()
            
            # Get today's sequence number for this outlet
            collection = db.get_collection("sales")
            
            # Count receipts for today at this outlet
            start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999)
            
            count = collection.count_documents({
                "business_id": ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id,
                "outlet_id": ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id,
                "created_at": {
                    "$gte": start_of_day,
                    "$lte": end_of_day
                }
            })
            
            sequence = str(count + 1).zfill(5)  # 5 digits with leading zeros
            
            return f"RCP-{outlet_code}-{today}-{sequence}"
            
        except Exception as e:
            Log.error(f"[_generate_receipt_number] Error: {str(e)}")
            # Fallback to timestamp-based
            import time
            return f"RCP-{int(time.time())}"

















