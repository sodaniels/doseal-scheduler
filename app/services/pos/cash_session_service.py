# services/cash_session_service.py
from datetime import datetime
from bson import ObjectId
from ...models.admin.cash_session import CashSession
from ...models.admin.cash_movement import CashMovement
from ...utils.logger import Log
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data


class CashSessionService:
    """
    Service layer for cash session and drawer management.
    """
    
    @staticmethod
    def open_session(
        business_id,
        outlet_id,
        user_id,
        user__id,
        opening_float,
        notes=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Open a new cash session for a cashier.
        Ensures no existing open session.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            opening_float: Float - starting cash in drawer
            notes: Optional notes
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, session_id: str or None, error: str or None)
        """
        log_tag = f"[cash_session_service.py][CashSessionService][open_session][{business_id}][{outlet_id}]"
        
        try:
            # Check for existing open session
            existing_session = CashSession.get_current_session(
                business_id=business_id,
                outlet_id=outlet_id,
                user__id=user__id
            )
            
            if existing_session:
                Log.error(f"{log_tag} User already has open session: {existing_session['_id']}")
                return False, None, "You already have an open cash session. Please close it first."
            
            # Validate opening float
            if opening_float < 0:
                Log.error(f"{log_tag} Invalid opening float")
                return False, None, "Opening float must be positive"
            
            # Create new session
            session = CashSession(
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                opening_float=opening_float,
                status=CashSession.STATUS_OPEN,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            session_id = session.save()
            
            if not session_id:
                Log.error(f"{log_tag} Failed to save session")
                return False, None, "Failed to create cash session"
            
            Log.info(f"{log_tag} Session opened: {session_id}")
            return True, str(session_id), None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def close_session(
        session_id,
        business_id,
        actual_balance,
        notes=None
    ):
        """
        Close a cash session with counted cash.
        Calculates variance and updates status.
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            actual_balance: Float - actual cash counted in drawer
            notes: Optional closing notes
            
        Returns:
            Tuple (success: bool, variance: float or None, error: str or None)
        """
        log_tag = f"[cash_session_service.py][CashSessionService][close_session][{session_id}]"
        
        try:
            # Fetch session
            session = CashSession.get_by_id(session_id=session_id, business_id=business_id)
            
            if not session:
                Log.error(f"{log_tag} Session not found")
                return False, None, "Cash session not found"
            
            # Verify status
            if session.get("status") != CashSession.STATUS_OPEN:
                Log.error(f"{log_tag} Session not open")
                return False, None, f"Cannot close session with status: {session.get('status')}"
            
            # Calculate expected balance
            # Expected = Opening + Cash Sales - Cash Returns + Cash In - Cash Out
            expected_balance = (
                session.get("opening_float", 0) +
                session.get("cash_sales_total", 0) -
                session.get("cash_returns_total", 0) +
                session.get("cash_in_total", 0) -
                session.get("cash_out_total", 0)
            )
            
            # Calculate variance
            variance = float(actual_balance) - float(expected_balance)
            
            # Update session
            session_id = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(CashSession.collection_name)
            
            update_doc = {
                "expected_balance": expected_balance,
                "actual_balance": float(actual_balance),
                "variance": variance,
                "status": CashSession.STATUS_CLOSED,
                "closed_at": datetime.utcnow()
            }
            
            if notes:
                update_doc["closing_notes"] = notes
            
            result = collection.update_one(
                {"_id": session_id, "business_id": business_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Session closed. Variance: {variance}")
                return True, variance, None
            else:
                Log.error(f"{log_tag} Failed to close session")
                return False, None, "Failed to close cash session"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def record_cash_in(
        session_id,
        business_id,
        outlet_id,
        user_id,
        user__id,
        amount,
        reason,
        notes=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Record cash added to drawer (non-sale).
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            amount: Float - amount added
            reason: String - reason for addition
            notes: Optional notes
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, movement_id: str or None, error: str or None)
        """
        log_tag = f"[cash_session_service.py][CashSessionService][record_cash_in][{session_id}]"
        
        try:
            # Validate session is open
            session = CashSession.get_by_id(session_id=session_id, business_id=business_id)
            
            if not session:
                Log.error(f"{log_tag} Session not found")
                return False, None, "Cash session not found"
            
            if session.get("status") != CashSession.STATUS_OPEN:
                Log.error(f"{log_tag} Session not open")
                return False, None, "Can only record movements in open sessions"
            
            # Validate amount
            if amount <= 0:
                Log.error(f"{log_tag} Invalid amount")
                return False, None, "Amount must be positive"
            
            # Create cash movement
            movement = CashMovement(
                business_id=business_id,
                outlet_id=outlet_id,
                session_id=session_id,
                user_id=user_id,
                user__id=user__id,
                movement_type=CashMovement.TYPE_CASH_IN,
                amount=amount,
                reason=reason,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            movement_id = movement.save()
            
            if not movement_id:
                Log.error(f"{log_tag} Failed to save movement")
                return False, None, "Failed to record cash movement"
            
            # Update session totals
            session_id_obj = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(CashSession.collection_name)
            collection.update_one(
                {"_id": session_id_obj, "business_id": business_id_obj},
                {"$inc": {"cash_in_total": amount}}
            )
            
            Log.info(f"{log_tag} Cash in recorded: {movement_id}")
            return True, str(movement_id), None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def record_cash_out(
        session_id,
        business_id,
        outlet_id,
        user_id,
        user__id,
        amount,
        reason,
        notes=None,
        agent_id=None,
        admin_id=None
    ):
        """
        Record cash removed from drawer (non-sale).
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            amount: Float - amount removed
            reason: String - reason for removal
            notes: Optional notes
            agent_id: Optional agent ObjectId
            admin_id: Optional admin ObjectId
            
        Returns:
            Tuple (success: bool, movement_id: str or None, error: str or None)
        """
        log_tag = f"[cash_session_service.py][CashSessionService][record_cash_out][{session_id}]"
        
        try:
            # Validate session is open
            session = CashSession.get_by_id(session_id=session_id, business_id=business_id)
            
            if not session:
                Log.error(f"{log_tag} Session not found")
                return False, None, "Cash session not found"
            
            if session.get("status") != CashSession.STATUS_OPEN:
                Log.error(f"{log_tag} Session not open")
                return False, None, "Can only record movements in open sessions"
            
            # Validate amount
            if amount <= 0:
                Log.error(f"{log_tag} Invalid amount")
                return False, None, "Amount must be positive"
            
            # Create cash movement
            movement = CashMovement(
                business_id=business_id,
                outlet_id=outlet_id,
                session_id=session_id,
                user_id=user_id,
                user__id=user__id,
                movement_type=CashMovement.TYPE_CASH_OUT,
                amount=amount,
                reason=reason,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            movement_id = movement.save()
            
            if not movement_id:
                Log.error(f"{log_tag} Failed to save movement")
                return False, None, "Failed to record cash movement"
            
            # Update session totals
            session_id_obj = ObjectId(session_id) if not isinstance(session_id, ObjectId) else session_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection("cash_sessions")
            collection.update_one(
                {"_id": session_id_obj, "business_id": business_id_obj},
                {"$inc": {"cash_out_total": amount}}
            )
            
            Log.info(f"{log_tag} Cash out recorded: {movement_id}")
            return True, str(movement_id), None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, None, str(e)
    
    @staticmethod
    def get_session_summary(session_id, business_id):
        """
        Get detailed summary of a cash session.
        
        Args:
            session_id: Session ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Dict with session details and movements
        """
        log_tag = f"[cash_session_service.py][CashSessionService][get_session_summary][{session_id}]"
        
        try:
            # Get session
            session = CashSession.get_by_id(session_id=session_id, business_id=business_id)
            
            if not session:
                Log.error(f"{log_tag} Session not found")
                return None
            
            # Get all movements
            movements = CashMovement.get_by_session(session_id=session_id, business_id=business_id)
            
            # Separate movements by type
            cash_in_movements = [m for m in movements if m.get("movement_type") == CashMovement.TYPE_CASH_IN]
            cash_out_movements = [m for m in movements if m.get("movement_type") == CashMovement.TYPE_CASH_OUT]
            
            # Build summary
            summary = {
                "session": session,
                "movements": {
                    "cash_in": cash_in_movements,
                    "cash_out": cash_out_movements,
                    "total_movements": len(movements)
                },
                "totals": {
                    "opening_float": session.get("opening_float", 0),
                    "cash_sales": session.get("cash_sales_total", 0),
                    "cash_returns": session.get("cash_returns_total", 0),
                    "card_sales": session.get("card_sales_total", 0),
                    "other_payments": session.get("other_payments_total", 0),
                    "cash_in": session.get("cash_in_total", 0),
                    "cash_out": session.get("cash_out_total", 0),
                    "expected_balance": session.get("expected_balance"),
                    "actual_balance": session.get("actual_balance"),
                    "variance": session.get("variance"),
                    "total_sales_count": session.get("total_sales_count", 0)
                }
            }
            
            Log.info(f"{log_tag} Summary generated")
            return summary
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None