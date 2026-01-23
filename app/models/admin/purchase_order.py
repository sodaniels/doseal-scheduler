# models/purchase_order.py
from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log


class PurchaseOrder(BaseModel):
    """
    Purchase Order model for supplier ordering workflow.
    Tracks orders from creation through receiving.
    """
    
    collection_name = "purchase_orders"
    
    # PO Statuses
    STATUS_DRAFT = "Draft"
    STATUS_ISSUED = "Issued"
    STATUS_PARTIALLY_RECEIVED = "Partially_Received"
    STATUS_COMPLETED = "Completed"
    STATUS_CANCELLED = "Cancelled"
    
    def __init__(
        self,
        business_id,
        outlet_id,
        supplier_id,
        user_id,
        user__id,
        ordered_items,
        expected_date=None,
        status=STATUS_DRAFT,
        notes=None,
        po_number=None,
        agent_id=None,
        admin_id=None,
        **kwargs
    ):
        """
        Initialize a purchase order.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Receiving outlet ObjectId or string
            supplier_id: Supplier ObjectId or string
            user_id: User string ID
            user__id: User ObjectId or string
            ordered_items: List of dicts with product_id, quantity, unit_cost, line_total
            expected_date: Optional datetime - expected delivery
            status: String - order status (plain text)
            notes: Optional notes (plain text)
            po_number: Auto-generated PO number
            agent_id: Optional agent ObjectId or string
            admin_id: Optional admin ObjectId or string
        """
        super().__init__(
            business_id=business_id,
            user__id=user__id,
            user_id=user_id,
            agent_id=agent_id,
            admin_id=admin_id
        )
        
        # Convert to ObjectId if needed
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
        self.supplier_id = ObjectId(supplier_id) if not isinstance(supplier_id, ObjectId) else supplier_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
        
        if agent_id:
            self.agent_id = ObjectId(agent_id) if not isinstance(agent_id, ObjectId) else agent_id
        else:
            self.agent_id = None
            
        if admin_id:
            self.admin_id = ObjectId(admin_id) if not isinstance(admin_id, ObjectId) else admin_id
        else:
            self.admin_id = None
        
        # Core fields (plain text, no encryption)
        self.user_id = user_id
        self.ordered_items = ordered_items
        self.status = status
        
        # Calculate totals
        self.subtotal = sum(item.get("line_total", 0) for item in ordered_items)
        self.total_items = sum(item.get("quantity", 0) for item in ordered_items)
        
        # Optional fields
        self.expected_date = expected_date if expected_date else None
        self.notes = notes
        
        # Auto-generate PO number if not provided
        if po_number:
            self.po_number = po_number
        else:
            self.po_number = self._generate_po_number()
        
        # Receiving tracking
        self.received_items = []
        self.total_received = 0.0
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.issued_at = None
        self.completed_at = None
    
    def _generate_po_number(self):
        """Generate unique PO number."""
        collection = db.get_collection(self.collection_name)
        
        # Get count of POs for this year
        year = datetime.utcnow().year
        count = collection.count_documents({
            "business_id": self.business_id,
            "created_at": {
                "$gte": datetime(year, 1, 1),
                "$lt": datetime(year + 1, 1, 1)
            }
        })
        
        return f"PO-{year}-{count + 1:06d}"
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "supplier_id": self.supplier_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "po_number": self.po_number,
            "ordered_items": self.ordered_items,
            "status": self.status,
            "subtotal": self.subtotal,
            "total_items": self.total_items,
            "received_items": self.received_items,
            "total_received": self.total_received,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        
        # Optional fields
        if self.expected_date:
            doc["expected_date"] = self.expected_date
        if self.notes:
            doc["notes"] = self.notes
        if self.issued_at:
            doc["issued_at"] = self.issued_at
        if self.completed_at:
            doc["completed_at"] = self.completed_at
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
            
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_po_doc(po: dict) -> dict:
        """Normalise ObjectId fields to strings for API responses."""
        if not po:
            return None

        po["_id"] = str(po["_id"])
        if po.get("business_id") is not None:
            po["business_id"] = str(po["business_id"])
        if po.get("outlet_id") is not None:
            po["outlet_id"] = str(po["outlet_id"])
        if po.get("supplier_id") is not None:
            po["supplier_id"] = str(po["supplier_id"])
        if po.get("user__id") is not None:
            po["user__id"] = str(po["user__id"])
        if po.get("agent_id") is not None:
            po["agent_id"] = str(po["agent_id"])
        if po.get("admin_id") is not None:
            po["admin_id"] = str(po["admin_id"])

        # All other fields are already plain
        return po
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, po_id, business_id):
        """
        Retrieve a PO by ID.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Normalised PO dict or None
        """
        log_tag = f"[purchase_order.py][PurchaseOrder][get_by_id][{po_id}][{business_id}]"
        
        try:
            po_id = ObjectId(po_id) if not isinstance(po_id, ObjectId) else po_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            po = collection.find_one({
                "_id": po_id,
                "business_id": business_id
            })
            
            if not po:
                Log.error(f"{log_tag} PO not found")
                return None
            
            po = cls._normalise_po_doc(po)
            Log.info(f"{log_tag} PO retrieved successfully")
            return po
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, status=None, supplier_id=None):
        """
        List POs for a business with optional filtering.
        
        Args:
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter (plain string)
            supplier_id: Optional supplier filter
            
        Returns:
            Dict with paginated POs
        """
        log_tag = f"[purchase_order.py][PurchaseOrder][get_by_business_id][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            query = {"business_id": business_id}
            
            if status:
                query["status"] = status
            if supplier_id:
                supplier_id = ObjectId(supplier_id) if not isinstance(supplier_id, ObjectId) else supplier_id
                query["supplier_id"] = supplier_id
            
            # Use BaseModel.paginate
            result = cls.paginate(query, page, per_page)
            
            # Normalise all POs
            pos = [cls._normalise_po_doc(po) for po in result.get("items", [])]
            
            result["purchase_orders"] = pos
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(result['purchase_orders'])} POs")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "purchase_orders": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50
            }
    
    @classmethod
    def update_status(cls, po_id, business_id, new_status, notes=None):
        """
        Update PO status.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            new_status: String - new status value (plain)
            notes: Optional note about status change (plain)
            
        Returns:
            Bool - success status
        """
        log_tag = f"[purchase_order.py][PurchaseOrder][update_status][{po_id}][{business_id}]"
        
        try:
            po_id = ObjectId(po_id) if not isinstance(po_id, ObjectId) else po_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            update_doc = {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
            
            if new_status == cls.STATUS_ISSUED:
                update_doc["issued_at"] = datetime.utcnow()
            elif new_status == cls.STATUS_COMPLETED:
                update_doc["completed_at"] = datetime.utcnow()
            
            if notes:
                update_doc["status_notes"] = notes
            
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": po_id, "business_id": business_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Status updated to {new_status}")
                return True
            else:
                Log.error(f"{log_tag} Failed to update status")
                return False
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False
    
    @classmethod
    def record_receiving(cls, po_id, business_id, received_items):
        """
        Record items received against PO.
        
        Args:
            po_id: PO ObjectId or string
            business_id: Business ObjectId or string
            received_items: List of dicts with product_id, composite_variant_id, quantity_received
            
        Returns:
            Bool - success status
        """
        log_tag = f"[purchase_order.py][PurchaseOrder][record_receiving][{po_id}][{business_id}]"
        
        try:
            po_id = ObjectId(po_id) if not isinstance(po_id, ObjectId) else po_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            
            # Add to received_items array and update total
            total_received = sum(item.get("quantity_received", 0) for item in received_items)
            
            result = collection.update_one(
                {"_id": po_id, "business_id": business_id},
                {
                    "$push": {"received_items": {"$each": received_items}},
                    "$inc": {"total_received": total_received},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Recorded {len(received_items)} received items")
                return True
            else:
                Log.error(f"{log_tag} Failed to record receiving")
                return False
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False