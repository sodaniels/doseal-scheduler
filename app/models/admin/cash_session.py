# models/cash_session.py
from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log


class CashSession(BaseModel):
    """
    Cash Session model for till/register management.
    Tracks opening float, sales, and closing reconciliation.
    """
    
    collection_name = "cash_sessions"
    
    # Session statuses
    STATUS_OPEN = "Open"
    STATUS_CLOSED = "Closed"
    STATUS_RECONCILED = "Reconciled"
    
    def __init__(
        self,
        business_id,
        outlet_id,
        user_id,
        user__id,
        opening_float,
        status=STATUS_OPEN,
        notes=None,
        agent_id=None,
        admin_id=None,
        **kwargs
    ):
        """
        Initialize a cash session.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID (cashier)
            user__id: User ObjectId (cashier)
            opening_float: Float - starting cash in drawer
            status: String - session status
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
        self.opening_float = float(opening_float)
        self.status = status
        
        # Sales tracking (updated throughout session)
        self.cash_sales_total = 0.0
        self.cash_returns_total = 0.0
        self.card_sales_total = 0.0
        self.other_payments_total = 0.0
        self.total_sales_count = 0
        
        # Cash movements
        self.cash_in_total = 0.0  # Manual cash additions
        self.cash_out_total = 0.0  # Manual cash removals
        
        # Closing (populated when closed)
        self.expected_balance = None  # Calculated
        self.actual_balance = None  # Counted by cashier
        self.variance = None  # Difference
        
        # Optional fields (plain text)
        self.notes = notes
        
        # Timestamps
        self.opened_at = datetime.utcnow()
        self.closed_at = None
        self.reconciled_at = None
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "opening_float": self.opening_float,
            "status": self.status,
            "cash_sales_total": self.cash_sales_total,
            "cash_returns_total": self.cash_returns_total,
            "card_sales_total": self.card_sales_total,
            "other_payments_total": self.other_payments_total,
            "total_sales_count": self.total_sales_count,
            "cash_in_total": self.cash_in_total,
            "cash_out_total": self.cash_out_total,
            "opened_at": self.opened_at
        }
        
        # Optional fields
        if self.expected_balance is not None:
            doc["expected_balance"] = self.expected_balance
        if self.actual_balance is not None:
            doc["actual_balance"] = self.actual_balance
        if self.variance is not None:
            doc["variance"] = self.variance
        if self.notes:
            doc["notes"] = self.notes
        if self.closed_at:
            doc["closed_at"] = self.closed_at
        if self.reconciled_at:
            doc["reconciled_at"] = self.reconciled_at
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
            
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_session_doc(session: dict) -> dict:
        """Normalise ObjectId fields to strings for API responses."""
        if not session:
            return None

        session["_id"] = str(session["_id"])
        if session.get("business_id") is not None:
            session["business_id"] = str(session["business_id"])
        if session.get("outlet_id") is not None:
            session["outlet_id"] = str(session["outlet_id"])
        if session.get("user__id") is not None:
            session["user__id"] = str(session["user__id"])
        if session.get("agent_id") is not None:
            session["agent_id"] = str(session["agent_id"])
        if session.get("admin_id") is not None:
            session["admin_id"] = str(session["admin_id"])

        # All other fields are already plain and left as-is
        return session
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, session_id, business_id):
        """
        Retrieve a session by ID.
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Normalised session dict or None
        """
        log_tag = f"[cash_session.py][CashSession][get_by_id][{session_id}][{business_id}]"
        
        try:
            session_id = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            session = collection.find_one({
                "_id": session_id,
                "business_id": business_id
            })
            
            if not session:
                Log.error(f"{log_tag} Session not found")
                return None
            
            session = cls._normalise_session_doc(session)
            Log.info(f"{log_tag} Session retrieved successfully")
            return session
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_current_session(cls, business_id, outlet_id, user__id):
        """
        Get the current open session for a cashier at an outlet.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user__id: User ObjectId or string
            
        Returns:
            Normalised session dict or None
        """
        log_tag = f"[cash_session.py][CashSession][get_current_session][{business_id}][{outlet_id}][{user__id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
            
            collection = db.get_collection(cls.collection_name)
            session = collection.find_one({
                "business_id": business_id,
                "outlet_id": outlet_id,
                "user__id": user__id,
                "status": cls.STATUS_OPEN
            })
            
            if not session:
                Log.info(f"{log_tag} No open session found")
                return None
            
            session = cls._normalise_session_doc(session)
            Log.info(f"{log_tag} Current session retrieved: {session['_id']}")
            return session
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_by_outlet(cls, business_id, outlet_id, page=None, per_page=None, status=None):
        """
        List sessions for an outlet with optional filtering.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter (plain string)
            
        Returns:
            Dict with paginated sessions
        """
        log_tag = f"[cash_session.py][CashSession][get_by_outlet][{business_id}][{outlet_id}]"
        
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
            
            # Normalise all sessions
            sessions = [cls._normalise_session_doc(s) for s in result.get("items", [])]
            
            result["cash_sessions"] = sessions
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(result['cash_sessions'])} sessions")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "cash_sessions": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50
            }
    
    @classmethod
    def update_sales_totals(cls, session_id, business_id, payment_method, amount, is_return=False):
        """
        Update session sales totals when a sale/return is made.
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            payment_method: String - "Cash", "Card", etc.
            amount: Float - sale/return amount
            is_return: Bool - True if this is a return
            
        Returns:
            Bool - success status
        """
        log_tag = f"[cash_session.py][CashSession][update_sales_totals][{session_id}][{business_id}]"
        
        try:
            session_id = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            
            # Determine which field to update
            if is_return:
                if payment_method == "Cash":
                    update_field = "cash_returns_total"
                else:
                    update_field = "card_sales_total" if payment_method == "Card" else "other_payments_total"
                    amount = -amount  # Subtract for returns
            else:
                if payment_method == "Cash":
                    update_field = "cash_sales_total"
                elif payment_method == "Card":
                    update_field = "card_sales_total"
                else:
                    update_field = "other_payments_total"
            
            result = collection.update_one(
                {"_id": session_id, "business_id": business_id},
                {
                    "$inc": {
                        update_field: amount,
                        "total_sales_count": 1 if not is_return else -1
                    }
                }
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Sales totals updated")
                return True
            else:
                Log.error(f"{log_tag} Failed to update sales totals")
                return False
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False