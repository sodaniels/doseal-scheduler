# models/stock_count.py
from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log


class StockCount(BaseModel):
    """
    Stock Count model for physical inventory audits.
    Tracks counted quantities vs system quantities and generates adjustments.
    """
    
    collection_name = "stock_counts"
    
    # Count statuses
    STATUS_OPEN = "Open"
    STATUS_IN_PROGRESS = "In_Progress"
    STATUS_COMPLETED = "Completed"
    STATUS_CANCELLED = "Cancelled"
    
    def __init__(
        self,
        business_id,
        outlet_id,
        user_id,
        user__id,
        status=STATUS_OPEN,
        notes=None,
        agent_id=None,
        admin_id=None,
        **kwargs
    ):
        """
        Initialize a stock count session.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string where count is performed
            user_id: User string ID
            user__id: User ObjectId or string
            status: String - count status (plain text)
            notes: Optional notes (plain text)
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
        self.status = status
        
        # Count items (populated as counts are entered)
        self.items = []
        
        # Summary statistics
        self.total_items_counted = 0
        self.total_variance_items = 0
        self.total_positive_variance = 0.0
        self.total_negative_variance = 0.0
        
        # Optional fields
        self.notes = notes
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.completed_at = None
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "status": self.status,
            "items": self.items,
            "total_items_counted": self.total_items_counted,
            "total_variance_items": self.total_variance_items,
            "total_positive_variance": self.total_positive_variance,
            "total_negative_variance": self.total_negative_variance,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        
        # Optional fields
        if self.notes:
            doc["notes"] = self.notes
        if self.completed_at:
            doc["completed_at"] = self.completed_at
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
            
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_count_doc(count: dict) -> dict:
        """Normalise ObjectId fields to strings for API responses."""
        if not count:
            return None

        count["_id"] = str(count["_id"])
        if count.get("business_id") is not None:
            count["business_id"] = str(count["business_id"])
        if count.get("outlet_id") is not None:
            count["outlet_id"] = str(count["outlet_id"])
        if count.get("user__id") is not None:
            count["user__id"] = str(count["user__id"])
        if count.get("agent_id") is not None:
            count["agent_id"] = str(count["agent_id"])
        if count.get("admin_id") is not None:
            count["admin_id"] = str(count["admin_id"])
        
        # Normalize item IDs
        for item in count.get("items", []):
            if "product_id" in item:
                item["product_id"] = str(item["product_id"])
            if "composite_variant_id" in item and item["composite_variant_id"]:
                item["composite_variant_id"] = str(item["composite_variant_id"])

        # All other fields are already plain
        return count
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, count_id, business_id):
        """
        Retrieve a stock count by ID.
        
        Args:
            count_id: Count ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Normalised count dict or None
        """
        log_tag = f"[stock_count.py][StockCount][get_by_id][{count_id}][{business_id}]"
        
        try:
            count_id = ObjectId(count_id) if not isinstance(count_id, ObjectId) else count_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            count = collection.find_one({
                "_id": count_id,
                "business_id": business_id
            })
            
            if not count:
                Log.error(f"{log_tag} Stock count not found")
                return None
            
            count = cls._normalise_count_doc(count)
            Log.info(f"{log_tag} Stock count retrieved successfully")
            return count
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_by_outlet(cls, business_id, outlet_id, page=None, per_page=None, status=None):
        """
        List stock counts for an outlet with optional filtering.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter (plain string)
            
        Returns:
            Dict with paginated counts
        """
        log_tag = f"[stock_count.py][StockCount][get_by_outlet][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            query = {
                "business_id": business_id,
                "outlet_id": outlet_id
            }
            
            if status:
                query["status"] = status
            
            # Use BaseModel.paginate
            result = cls.paginate(query, page, per_page)
            
            # Normalise all counts
            counts = [cls._normalise_count_doc(c) for c in result.get("items", [])]
            
            result["stock_counts"] = counts
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(result['stock_counts'])} stock counts")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "stock_counts": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50
            }
    
    @classmethod
    def update_status(cls, count_id, business_id, new_status):
        """
        Update stock count status.
        
        Args:
            count_id: Count ObjectId or string
            business_id: Business ObjectId or string
            new_status: String - new status value (plain)
            
        Returns:
            Bool - success status
        """
        log_tag = f"[stock_count.py][StockCount][update_status][{count_id}][{business_id}]"
        
        try:
            count_id = ObjectId(count_id) if not isinstance(count_id, ObjectId) else count_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            update_doc = {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
            
            if new_status == cls.STATUS_COMPLETED:
                update_doc["completed_at"] = datetime.utcnow()
            
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": count_id, "business_id": business_id},
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