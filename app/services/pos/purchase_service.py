# services/purchase_service.py
from datetime import datetime
from bson import ObjectId
from ...models.admin.purchase_order import PurchaseOrder
from ...models.admin.stock_ledger import StockLedger
from .inventory_service import InventoryService
from ...utils.logger import Log


class PurchaseService:
    """
    Service layer for purchase order and receiving operations.
    """
    
    @staticmethod
    def create_purchase_order(
        business_id,
        outlet_id,
        supplier_id,
        user_id,
        user__id,
        ordered_items,
        expected_date=None,
        notes=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Create a new purchase order.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Receiving outlet ObjectId or string
            supplier_id: Supplier ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            ordered_items: List of order line items
            expected_date: Optional expected delivery date
            notes: Optional notes
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, po_id: str or None, error: str or None)
        """
        log_tag = f"[purchase_service.py][PurchaseService][create_purchase_order][{business_id}]"
        
        try:
            # Validate ordered items
            if not ordered_items or len(ordered_items) == 0:
                Log.error(f"{log_tag} No items in order")
                return False, None, "Order must contain at least one item"
            
            # Validate each item
            for idx, item in enumerate(ordered_items):
                if not item.get("product_id"):
                    return False, None, f"Item {idx + 1}: Missing product_id"
                if not item.get("quantity") or item.get("quantity") <= 0:
                    return False, None, f"Item {idx + 1}: Invalid quantity"
                if not item.get("unit_cost") or item.get("unit_cost") < 0:
                    return False, None, f"Item {idx + 1}: Invalid unit cost"
                
                # Calculate line total
                item["line_total"] = float(item["quantity"]) * float(item["unit_cost"])
            
            # Create PO
            po = PurchaseOrder(
                business_id=business_id,
                outlet_id=outlet_id,
                supplier_id=supplier_id,
                user_id=user_id,
                user__id=user__id,
                ordered_items=ordered_items,
                expected_date=expected_date,
                status=PurchaseOrder.STATUS_DRAFT,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            po_id = po.save()
            
            if not po_id:
                Log.error(f"{log_tag} Failed to save PO")
                return False, None, "Failed to create purchase order"
            
            Log.info(f"{log_tag} PO created: {po_id}")
            return True, str(po_id), None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def issue_purchase_order(po_id, business_id, user_id, user__id):
        """
        Issue/send a purchase order to supplier.
        Changes status from Draft to Issued.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            
        Returns:
            Tuple (success: bool, error: str or None)
        """
        log_tag = f"[purchase_service.py][PurchaseService][issue_purchase_order][{po_id}]"
        
        try:
            # Fetch PO
            po = PurchaseOrder.get_by_id(po_id=po_id, business_id=business_id)
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return False, "Purchase order not found"
            
            # Verify status
            if po.get("status") != PurchaseOrder.STATUS_DRAFT:
                Log.error(f"{log_tag} PO not in Draft status")
                return False, f"Cannot issue PO with status: {po.get('status')}"
            
            # Update status
            success = PurchaseOrder.update_status(
                po_id=po_id,
                business_id=business_id,
                new_status=PurchaseOrder.STATUS_ISSUED,
                notes=f"Issued by {user_id}"
            )
            
            if success:
                Log.info(f"{log_tag} PO issued successfully")
                # TODO: Send email/notification to supplier
                return True, None
            else:
                Log.error(f"{log_tag} Failed to update PO status")
                return False, "Failed to issue purchase order"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, str(e)
    
    @staticmethod
    def receive_stock(
        po_id,
        business_id,
        outlet_id,
        user_id,
        user__id,
        received_items,
        receive_note=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Receive stock against a purchase order.
        Creates stock ledger entries and updates PO status.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            outlet_id: Receiving outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            received_items: List of dicts with:
                - product_id: Product ObjectId
                - composite_variant_id: Optional variant ObjectId
                - quantity_received: Float - actual quantity received
            receive_note: Optional note about receiving
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, grn_id: str or None, error: str or None)
        """
        log_tag = f"[purchase_service.py][PurchaseService][receive_stock][{po_id}][{business_id}]"
        
        try:
            # Fetch PO
            po = PurchaseOrder.get_by_id(po_id=po_id, business_id=business_id)
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return False, None, "Purchase order not found"
            
            # Verify status
            if po.get("status") not in [
                PurchaseOrder.STATUS_ISSUED,
                PurchaseOrder.STATUS_PARTIALLY_RECEIVED
            ]:
                Log.error(f"{log_tag} PO not in receivable status")
                return False, None, f"Cannot receive stock for PO with status: {po.get('status')}"
            
            # Verify outlet matches
            if str(po.get("outlet_id")) != str(outlet_id):
                Log.error(f"{log_tag} Outlet mismatch")
                return False, None, "Receiving outlet does not match PO outlet"
            
            # Validate received items
            if not received_items or len(received_items) == 0:
                Log.error(f"{log_tag} No items to receive")
                return False, None, "No items to receive"
            
            # Create stock ledger entries for each item
            ledger_ids = []
            for item in received_items:
                if item.get("quantity_received", 0) <= 0:
                    continue
                
                # Find matching ordered item to get unit cost
                ordered_item = next(
                    (oi for oi in po.get("ordered_items", [])
                     if str(oi.get("product_id")) == str(item.get("product_id"))
                     and str(oi.get("composite_variant_id", "")) == str(item.get("composite_variant_id", ""))),
                    None
                )
                
                unit_cost = ordered_item.get("unit_cost") if ordered_item else None
                
                ledger_id = InventoryService.increase_stock(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    product_id=item["product_id"],
                    quantity=item["quantity_received"],
                    reference_type=StockLedger.REF_TYPE_PURCHASE,
                    user_id=user_id,
                    user__id=user__id,
                    composite_variant_id=item.get("composite_variant_id"),
                    reference_id=po_id,
                    note=receive_note or f"Received against PO {po.get('po_number')}",
                    unit_cost=unit_cost,
                    agent_id=agent_id,
                    admin_id=admin_id
                )
                
                if ledger_id:
                    ledger_ids.append(ledger_id)
                    # Add received timestamp to item
                    item["received_at"] = datetime.utcnow()
                else:
                    Log.error(f"{log_tag} Failed to create ledger entry for product {item['product_id']}")
            
            if not ledger_ids:
                Log.error(f"{log_tag} No stock entries created")
                return False, None, "Failed to create stock entries"
            
            Log.info(f"{log_tag} Created {len(ledger_ids)} stock ledger entries")
            
            # Record receiving in PO
            PurchaseOrder.record_receiving(
                po_id=po_id,
                business_id=business_id,
                received_items=received_items
            )
            
            # Update PO status
            # Check if fully received
            ordered_total = po.get("total_items", 0)
            received_total = po.get("total_received", 0) + sum(
                item.get("quantity_received", 0) for item in received_items
            )
            
            if received_total >= ordered_total:
                new_status = PurchaseOrder.STATUS_COMPLETED
            else:
                new_status = PurchaseOrder.STATUS_PARTIALLY_RECEIVED
            
            PurchaseOrder.update_status(
                po_id=po_id,
                business_id=business_id,
                new_status=new_status,
                notes=f"Received {len(received_items)} items"
            )
            
            Log.info(f"{log_tag} Stock received successfully, PO status: {new_status}")
            
            # Return first ledger ID as GRN reference
            return True, ledger_ids[0], None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def cancel_purchase_order(po_id, business_id, reason=None):
        """
        Cancel a purchase order.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            reason: Optional cancellation reason
            
        Returns:
            Tuple (success: bool, error: str or None)
        """
        log_tag = f"[purchase_service.py][PurchaseService][cancel_purchase_order][{po_id}]"
        
        try:
            # Fetch PO
            po = PurchaseOrder.get_by_id(po_id=po_id, business_id=business_id)
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return False, "Purchase order not found"
            
            # Verify status
            if po.get("status") in [PurchaseOrder.STATUS_COMPLETED, PurchaseOrder.STATUS_CANCELLED]:
                Log.error(f"{log_tag} Cannot cancel PO with status: {po.get('status')}")
                return False, f"Cannot cancel PO with status: {po.get('status')}"
            
            if po.get("status") == PurchaseOrder.STATUS_PARTIALLY_RECEIVED:
                Log.error(f"{log_tag} Cannot cancel partially received PO")
                return False, "Cannot cancel purchase order that has been partially received"
            
            # Update status
            success = PurchaseOrder.update_status(
                po_id=po_id,
                business_id=business_id,
                new_status=PurchaseOrder.STATUS_CANCELLED,
                notes=reason or "Purchase order cancelled"
            )
            
            if success:
                Log.info(f"{log_tag} PO cancelled successfully")
                return True, None
            else:
                Log.error(f"{log_tag} Failed to cancel PO")
                return False, "Failed to cancel purchase order"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, str(e)