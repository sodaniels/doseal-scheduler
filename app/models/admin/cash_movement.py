# models/cash_movement.py
from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log



class CashMovement(BaseModel):
    """
    Cash Movement model for non-sale cash transactions.
    Tracks manual cash additions and removals from drawer.
    """
    
    collection_name = "cash_movements"
    
    # Movement types
    TYPE_CASH_IN = "IN"
    TYPE_CASH_OUT = "OUT"
    
    # Common reasons
    REASON_BANK_DEPOSIT = "Bank_Deposit"
    REASON_BANK_WITHDRAWAL = "Bank_Withdrawal"
    REASON_PETTY_CASH = "Petty_Cash"
    REASON_EXPENSE_PAYMENT = "Expense_Payment"
    REASON_FLOAT_ADJUSTMENT = "Float_Adjustment"
    REASON_CORRECTION = "Correction"
    REASON_OTHER = "Other"
    
    def __init__(
        self,
        business_id,
        outlet_id,
        session_id,
        user_id,
        user__id,
        movement_type,
        amount,
        reason,
        notes=None,
        agent_id=None,
        admin_id=None,
        **kwargs
    ):
        """
        Initialize a cash movement.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            session_id: Cash session ObjectId or string
            user_id: User string ID
            user__id: User ObjectId or string
            movement_type: "IN" or "OUT"
            amount: Float - amount moved (positive)
            reason: String - reason for movement
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
        self.session_id = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
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
        self.movement_type = movement_type
        self.amount = float(amount)
        self.reason = reason
        self.notes = notes
        
        # Timestamp
        self.created_at = datetime.utcnow()
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "movement_type": self.movement_type,
            "amount": self.amount,
            "reason": self.reason,
            "created_at": self.created_at
        }
        
        # Optional fields
        if self.notes:
            doc["notes"] = self.notes
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
            
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_movement_doc(movement: dict) -> dict:
        """Normalise ObjectId fields to strings for API responses."""
        if not movement:
            return None

        movement["_id"] = str(movement["_id"])
        if movement.get("business_id") is not None:
            movement["business_id"] = str(movement["business_id"])
        if movement.get("outlet_id") is not None:
            movement["outlet_id"] = str(movement["outlet_id"])
        if movement.get("session_id") is not None:
            movement["session_id"] = str(movement["session_id"])
        if movement.get("user__id") is not None:
            movement["user__id"] = str(movement["user__id"])
        if movement.get("agent_id") is not None:
            movement["agent_id"] = str(movement["agent_id"])
        if movement.get("admin_id") is not None:
            movement["admin_id"] = str(movement["admin_id"])

        # All other fields are already plain
        return movement
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_session(cls, session_id, business_id):
        """
        Get all cash movements for a session.
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            List of normalised movement dicts
        """
        log_tag = f"[cash_movement.py][CashMovement][get_by_session][{session_id}][{business_id}]"
        
        try:
            session_id = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            movements = list(collection.find({
                "session_id": session_id,
                "business_id": business_id
            }).sort("created_at", -1))
            
            # Normalise all movements
            result = [cls._normalise_movement_doc(m) for m in movements]
            
            Log.info(f"{log_tag} Found {len(result)} movements")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []
    
    @classmethod
    def get_by_outlet(cls, business_id, outlet_id, page=None, per_page=None):
        """
        Get all cash movements for an outlet with pagination.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            
        Returns:
            Dict with paginated movements
        """
        log_tag = f"[cash_movement.py][CashMovement][get_by_outlet][{business_id}][{outlet_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            
            query = {
                "business_id": business_id,
                "outlet_id": outlet_id
            }
            
            # Use BaseModel.paginate
            result = cls.paginate(query, page, per_page)
            
            # Normalise all movements
            movements = [cls._normalise_movement_doc(m) for m in result.get("items", [])]
            
            result["cash_movements"] = movements
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(result['cash_movements'])} movements")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "cash_movements": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50
            }