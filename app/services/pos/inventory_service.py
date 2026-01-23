# services/inventory_service.py
from bson import ObjectId
from ...models.admin.stock_ledger import StockLedger
from ...utils.logger import Log
from ...extensions.db import db


class InventoryService:
    """
    Service layer for inventory/stock management.
    All stock operations go through this service to ensure consistency.
    """
    
    @staticmethod
    def increase_stock(
        business_id,
        outlet_id,
        product_id,
        quantity,
        reference_type,
        user_id,
        user__id,
        composite_variant_id=None,
        reference_id=None,
        note=None,
        unit_cost=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Increase stock (positive quantity_delta).
        Used for: opening stock, purchases, returns, adjustments (positive).
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            product_id: Product ObjectId or string
            quantity: Float - amount to increase (must be positive)
            reference_type: String - StockLedger.REF_TYPE_*
            user_id: User string ID
            user__id: User ObjectId
            composite_variant_id: Optional variant ObjectId or string
            reference_id: Optional reference document ObjectId
            note: Optional note about the movement
            unit_cost: Optional cost per unit
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            String ledger entry ID if successful, None otherwise
        """
        log_tag = f"[inventory_service.py][InventoryService][increase_stock][{business_id}][{outlet_id}]"
        
        try:
            if quantity <= 0:
                Log.error(f"{log_tag} Quantity must be positive, got: {quantity}")
                return None
            
            # Create ledger entry
            ledger = StockLedger(
                business_id=business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                quantity_delta=float(quantity),
                reference_type=reference_type,
                user_id=user_id,
                user__id=user__id,
                composite_variant_id=composite_variant_id,
                reference_id=reference_id,
                note=note,
                unit_cost=unit_cost,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            ledger_id = ledger.save()
            
            if ledger_id:
                Log.info(f"{log_tag} Stock increased by {quantity} for product {product_id}, ledger: {ledger_id}")
                return str(ledger_id)
            else:
                Log.error(f"{log_tag} Failed to create ledger entry")
                return None
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def decrease_stock(
        business_id,
        outlet_id,
        product_id,
        quantity,
        reference_type,
        user_id,
        user__id,
        composite_variant_id=None,
        reference_id=None,
        note=None,
        unit_cost=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Decrease stock (negative quantity_delta).
        Used for: sales, damages, adjustments (negative), transfers out.
        
        Args:
            Same as increase_stock
            quantity: Float - amount to decrease (must be positive, will be negated internally)
            
        Returns:
            String ledger entry ID if successful, None otherwise
        """
        log_tag = f"[inventory_service.py][InventoryService][decrease_stock][{business_id}][{outlet_id}]"
        
        try:
            if quantity <= 0:
                Log.error(f"{log_tag} Quantity must be positive, got: {quantity}")
                return None
            
            # Create ledger entry with negative delta
            ledger = StockLedger(
                business_id=business_id,
                outlet_id=outlet_id,
                product_id=product_id,
                quantity_delta=-float(quantity),
                reference_type=reference_type,
                user_id=user_id,
                user__id=user__id,
                composite_variant_id=composite_variant_id,
                reference_id=reference_id,
                note=note,
                unit_cost=unit_cost,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            ledger_id = ledger.save()
            
            if ledger_id:
                Log.info(f"{log_tag} Stock decreased by {quantity} for product {product_id}, ledger: {ledger_id}")
                return str(ledger_id)
            else:
                Log.error(f"{log_tag} Failed to create ledger entry")
                return None
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def get_available_stock(business_id, outlet_id, product_id, composite_variant_id=None):
        """
        Calculate current available stock by summing all quantity_deltas.
        This is the single source of truth for stock levels.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            product_id: Product ObjectId or string
            composite_variant_id: Optional variant ObjectId or string
            
        Returns:
            Float - current stock quantity (can be negative if oversold)
        """
        log_tag = f"[inventory_service.py][InventoryService][get_available_stock][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            product_id = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
            
            # Build query
            match_query = {
                "business_id": business_id,
                "outlet_id": outlet_id,
                "product_id": product_id
            }
            
            
            if composite_variant_id:
                composite_variant_id = ObjectId(composite_variant_id) if not isinstance(composite_variant_id, ObjectId) else composite_variant_id
                match_query["composite_variant_id"] = composite_variant_id
            
            # Aggregate sum of quantity_delta
            collection = db.get_collection(StockLedger.collection_name)
            pipeline = [
                {"$match": match_query},
                {"$group": {
                    "_id": None,
                    "total_quantity": {"$sum": "$quantity_delta"}
                }}
            ]
            
            result = list(collection.aggregate(pipeline))
            
            if result and len(result) > 0:
                stock = float(result[0].get("total_quantity", 0))
                Log.info(f"{log_tag} Available stock: {stock}")
                return stock
            else:
                Log.info(f"{log_tag} No stock records found, returning 0")
                return 0.0
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return 0.0
    
    @staticmethod
    def get_stock_levels_by_outlet(business_id, outlet_id, low_stock_only=False):
        """
        Get stock levels for all products at an outlet.
        Useful for dashboard/reports.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            low_stock_only: If True, only return items below quantity_alert
            
        Returns:
            List of dicts with product_id, composite_variant_id (if any), and current_stock
        """
        log_tag = f"[inventory_service.py][InventoryService][get_stock_levels_by_outlet][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            collection = db.get_collection(StockLedger.collection_name)
            
            # Aggregate by product and variant
            pipeline = [
                {"$match": {
                    "business_id": business_id,
                    "outlet_id": outlet_id
                }},
                {"$group": {
                    "_id": {
                        "product_id": "$product_id",
                        "composite_variant_id": "$composite_variant_id"
                    },
                    "current_stock": {"$sum": "$quantity_delta"}
                }},
                {"$sort": {"current_stock": 1}}
            ]
            
            results = list(collection.aggregate(pipeline))
            
            stock_levels = []
            for item in results:
                stock_level = {
                    "product_id": str(item["_id"]["product_id"]),
                    "composite_variant_id": str(item["_id"]["composite_variant_id"]) if item["_id"].get("composite_variant_id") else None,
                    "current_stock": float(item["current_stock"])
                }
                
                # TODO: If low_stock_only, fetch quantity_alert from composite_variant and filter
                # For now, include all
                stock_levels.append(stock_level)
            
            Log.info(f"{log_tag} Found {len(stock_levels)} stock items")
            return stock_levels
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []
    
    @staticmethod
    def validate_stock_availability(business_id, outlet_id, items):
        """
        Validate that sufficient stock exists for a list of items.
        Used before creating a sale.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            items: List of dicts with keys:
                - product_id: Product ObjectId or string
                - composite_variant_id: Optional variant ObjectId or string
                - quantity: Float - required quantity
                
        Returns:
            Tuple (bool, list):
                - bool: True if all items have sufficient stock
                - list: List of dicts with insufficient stock details
        """
        log_tag = f"[inventory_service.py][InventoryService][validate_stock_availability][{business_id}][{outlet_id}]"
        
        try:
            insufficient_items = []
            
            for item in items:
                product_id = item.get("product_id")
                composite_variant_id = item.get("composite_variant_id")
                required_qty = float(item.get("quantity", 0))
                
                available = InventoryService.get_available_stock(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    product_id=product_id,
                    composite_variant_id=composite_variant_id
                )
                
                if available < required_qty:
                    insufficient_items.append({
                        "product_id": str(product_id),
                        "composite_variant_id": str(composite_variant_id) if composite_variant_id else None,
                        "required": required_qty,
                        "available": available,
                        "shortfall": required_qty - available
                    })
            
            if insufficient_items:
                Log.error(f"{log_tag} Insufficient stock for {len(insufficient_items)} items")
                return False, insufficient_items
            else:
                Log.info(f"{log_tag} All items have sufficient stock")
                return True, []
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, [{"error": str(e)}]